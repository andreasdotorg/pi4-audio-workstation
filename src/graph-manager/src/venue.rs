//! Venue profile loading and management.
//!
//! A venue profile defines per-channel gain, delay, and coefficient settings
//! for a specific venue or configuration scenario.  Profiles are stored as
//! YAML files in the `configs/venues/` directory.
//!
//! ## YAML schema
//!
//! ```yaml
//! name: "local-demo"
//! description: "Local development and testing"
//! channels:
//!   1_sat_l:
//!     gain_db: -20
//!     delay_ms: 0
//!     coefficients: "dirac.wav"
//!   # ... 8 channels total
//! ```
//!
//! ## Safety
//!
//! - D-009: Gain Mult hard cap at 1.0 (0 dB).  Any `gain_db > 0` is clamped.
//! - D-063: All 8 channels must be present in a valid venue profile.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// Channel names (canonical order, matches GAIN_PARAM_NAMES in watchdog.rs)
// ---------------------------------------------------------------------------

/// The 8 channel keys expected in every venue profile, in canonical order.
pub const CHANNEL_NAMES: &[&str] = &[
    "1_sat_l",
    "2_sat_r",
    "3_sub1_lp",
    "4_sub2_lp",
    "5_eng_l",
    "6_eng_r",
    "7_iem_l",
    "8_iem_r",
];

/// Maps channel keys to the gain builtin param names used by pw-cli.
/// Order matches `CHANNEL_NAMES` and `watchdog::GAIN_PARAM_NAMES`.
pub const GAIN_PARAM_NAMES: &[&str] = &[
    "gain_left_hp",
    "gain_right_hp",
    "gain_sub1_lp",
    "gain_sub2_lp",
    "gain_hp_l",
    "gain_hp_r",
    "gain_iem_l",
    "gain_iem_r",
];

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

/// A single channel's configuration within a venue profile.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ChannelConfig {
    pub gain_db: f64,
    pub delay_ms: f64,
    pub coefficients: String,
}

/// A complete venue profile parsed from YAML.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct VenueProfile {
    pub name: String,
    #[serde(default)]
    pub description: String,
    pub channels: BTreeMap<String, ChannelConfig>,
}

/// Summary of a venue (for list_venues response).
#[derive(Debug, Clone, Serialize)]
pub struct VenueSummary {
    pub name: String,
    pub description: String,
}

// ---------------------------------------------------------------------------
// Gain conversion
// ---------------------------------------------------------------------------

/// Convert dB to linear multiplier: `10^(gain_db / 20)`.
///
/// D-009: Hard cap at 1.0 (0 dB).  Any positive gain_db is clamped to 0 dB.
pub fn gain_db_to_linear(gain_db: f64) -> f64 {
    if gain_db <= -120.0 {
        return 0.0;
    }
    let linear = 10.0_f64.powf(gain_db / 20.0);
    if linear > 1.0 {
        1.0
    } else {
        linear
    }
}

// ---------------------------------------------------------------------------
// Venue name persistence (US-123)
// ---------------------------------------------------------------------------

/// Directory for persistent state that survives reboots.
const STATE_DIR: &str = "/var/lib/pi4audio";

/// State file for the last-used venue name.
const LAST_VENUE_FILE: &str = "last-venue";

/// Resolve the state directory path.
///
/// Uses `PI4AUDIO_STATE_DIR` env var if set, otherwise falls back to
/// `/var/lib/pi4audio`. Call once at startup and pass the result through.
pub fn state_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("PI4AUDIO_STATE_DIR") {
        PathBuf::from(dir)
    } else {
        PathBuf::from(STATE_DIR)
    }
}

/// Persist the venue name to disk via atomic write (US-123 AC #4).
///
/// Writes to a temp file, fsyncs, then renames — crash-safe.
/// Creates a `.bak` backup of the previous file before overwriting.
/// Errors are logged but not fatal (venue persistence is best-effort).
pub fn persist_venue_name(name: &str, dir: &Path) {
    let path = dir.join(LAST_VENUE_FILE);
    let tmp_path = dir.join(format!("{}.tmp", LAST_VENUE_FILE));
    let bak_path = dir.join(format!("{}.bak", LAST_VENUE_FILE));

    // Create state dir if missing (may not exist on first run).
    if let Err(e) = std::fs::create_dir_all(&dir) {
        log::warn!("US-123: cannot create state dir {:?}: {}", dir, e);
        return;
    }

    // Backup existing file before overwriting.
    if path.exists() {
        if let Err(e) = std::fs::copy(&path, &bak_path) {
            log::warn!("US-123: backup copy failed: {}", e);
        }
    }

    // Atomic write: temp file -> fsync -> rename.
    match std::fs::File::create(&tmp_path) {
        Ok(mut f) => {
            use std::io::Write;
            if let Err(e) = f.write_all(name.as_bytes()) {
                log::warn!("US-123: write failed: {}", e);
                return;
            }
            if let Err(e) = f.sync_all() {
                log::warn!("US-123: fsync failed: {}", e);
                return;
            }
        }
        Err(e) => {
            log::warn!("US-123: create temp file failed: {}", e);
            return;
        }
    }

    if let Err(e) = std::fs::rename(&tmp_path, &path) {
        log::warn!("US-123: rename failed: {}", e);
        return;
    }

    log::info!("US-123: persisted venue name '{}' to {:?}", name, path);
}

/// Load the persisted venue name from disk (US-123 AC #5).
///
/// Reads the primary file; falls back to `.bak` if missing or corrupt.
/// Returns None on first boot or if both files are missing/empty.
pub fn load_persisted_venue(dir: &Path) -> Option<String> {
    let path = dir.join(LAST_VENUE_FILE);
    let bak_path = dir.join(format!("{}.bak", LAST_VENUE_FILE));

    // Try primary file.
    if let Ok(content) = std::fs::read_to_string(&path) {
        let name = content.trim().to_string();
        if !name.is_empty() {
            log::info!("US-123: loaded persisted venue '{}' from {:?}", name, path);
            return Some(name);
        }
    }

    // Fallback to backup.
    if let Ok(content) = std::fs::read_to_string(&bak_path) {
        let name = content.trim().to_string();
        if !name.is_empty() {
            log::warn!("US-123: primary state file missing, loaded venue '{}' from backup", name);
            return Some(name);
        }
    }

    log::info!("US-123: no persisted venue found (first boot)");
    None
}

// ---------------------------------------------------------------------------
// Default venue on first boot (US-113)
// ---------------------------------------------------------------------------

/// Default venue name when no persisted venue exists.
const DEFAULT_VENUE_NAME: &str = "foh-passthrough";

/// Env var to override the default venue name.
const DEFAULT_VENUE_ENV: &str = "PI4AUDIO_DEFAULT_VENUE";

/// Validate a venue name: alphanumeric, hyphens, and underscores only.
///
/// Rejects path separators, dots, spaces, and other special characters.
/// This is a defense-in-depth measure — `find_venue()` matches by YAML
/// `name` field, not by filename, so path traversal is not possible via
/// the current lookup. But a future refactor could change that.
pub fn validate_venue_name(name: &str) -> Result<(), String> {
    if name.is_empty() {
        return Err("venue name is empty".to_string());
    }
    if name.len() > 128 {
        return Err(format!("venue name too long ({} chars, max 128)", name.len()));
    }
    for ch in name.chars() {
        if !ch.is_ascii_alphanumeric() && ch != '-' && ch != '_' {
            return Err(format!(
                "venue name contains invalid character '{}' (allowed: a-z, A-Z, 0-9, -, _)",
                ch,
            ));
        }
    }
    Ok(())
}

/// Resolve the default venue name for first boot (US-113).
///
/// Reads `PI4AUDIO_DEFAULT_VENUE` env var if set, otherwise uses
/// `"foh-passthrough"`. Validates the name before returning.
///
/// Call once at startup and pass the result through.
pub fn default_venue_name() -> Result<String, String> {
    let name = std::env::var(DEFAULT_VENUE_ENV)
        .unwrap_or_else(|_| DEFAULT_VENUE_NAME.to_string());
    validate_venue_name(&name)?;
    Ok(name)
}

/// Load the default venue on first boot (US-113).
///
/// When `load_persisted_venue()` returns `None`, this function:
/// 1. Reads the default venue name from env var / built-in default
/// 2. Finds and validates the venue profile
/// 3. Persists the venue name (so subsequent boots use normal restore)
/// 4. Returns the venue name (NOT the gains — gate stays CLOSED per D-063)
///
/// The caller stores the venue name in `active_venue` and computes
/// `pending_gains`, but does NOT open the gate. The operator must
/// explicitly call `open_gate` after confirming the venue.
pub fn load_default_venue(
    venues_dir: &Path,
    state_dir: &Path,
) -> Result<String, String> {
    let name = default_venue_name()?;

    // Verify the venue profile actually exists and parses.
    let _profile = find_venue(venues_dir, &name)?;

    // Persist so subsequent boots use the normal restore path.
    persist_venue_name(&name, state_dir);

    log::info!(
        "US-113: loaded default venue '{}' on first boot (source: {})",
        name,
        if std::env::var(DEFAULT_VENUE_ENV).is_ok() {
            DEFAULT_VENUE_ENV
        } else {
            "built-in default"
        },
    );

    Ok(name)
}

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------

/// Default venues directory relative to project root.
const DEFAULT_VENUES_DIR: &str = "configs/venues";

/// Resolve the venues directory path.
///
/// Uses `PI4AUDIO_VENUES_DIR` env var if set, otherwise falls back to
/// `configs/venues` relative to the working directory.
pub fn venues_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("PI4AUDIO_VENUES_DIR") {
        PathBuf::from(dir)
    } else {
        PathBuf::from(DEFAULT_VENUES_DIR)
    }
}

/// List all venue profiles found in the venues directory.
///
/// Returns a sorted list of venue summaries (name + description).
/// Silently skips files that fail to parse.
pub fn list_venues(dir: &Path) -> Vec<VenueSummary> {
    let mut venues = Vec::new();

    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(e) => {
            log::warn!("Cannot read venues directory {:?}: {}", dir, e);
            return venues;
        }
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map_or(false, |ext| ext == "yml" || ext == "yaml") {
            match load_venue(&path) {
                Ok(profile) => {
                    venues.push(VenueSummary {
                        name: profile.name,
                        description: profile.description,
                    });
                }
                Err(e) => {
                    log::warn!("Skipping venue file {:?}: {}", path, e);
                }
            }
        }
    }

    venues.sort_by(|a, b| a.name.cmp(&b.name));
    venues
}

/// Load and validate a single venue profile from a YAML file.
pub fn load_venue(path: &Path) -> Result<VenueProfile, String> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| format!("read error: {}", e))?;
    parse_venue(&content)
}

/// Parse and validate a venue profile from a YAML string.
pub fn parse_venue(yaml: &str) -> Result<VenueProfile, String> {
    let profile: VenueProfile = serde_yaml::from_str(yaml)
        .map_err(|e| format!("YAML parse error: {}", e))?;

    // Validate: all 8 channels must be present.
    for name in CHANNEL_NAMES {
        if !profile.channels.contains_key(*name) {
            return Err(format!("missing channel: {}", name));
        }
    }

    Ok(profile)
}

/// Find a venue profile by name in the venues directory.
///
/// Scans all `.yml`/`.yaml` files and returns the first match.
pub fn find_venue(dir: &Path, name: &str) -> Result<VenueProfile, String> {
    let entries = std::fs::read_dir(dir)
        .map_err(|e| format!("cannot read venues directory: {}", e))?;

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map_or(false, |ext| ext == "yml" || ext == "yaml") {
            if let Ok(profile) = load_venue(&path) {
                if profile.name == name {
                    return Ok(profile);
                }
            }
        }
    }

    Err(format!("venue not found: \"{}\"", name))
}

/// Compute the 8 linear gain values for a venue profile.
///
/// Returns `(param_name, linear_mult)` pairs in canonical channel order.
/// D-009: All values capped at 1.0.
pub fn venue_gains(profile: &VenueProfile) -> Vec<(String, f64)> {
    CHANNEL_NAMES
        .iter()
        .zip(GAIN_PARAM_NAMES.iter())
        .map(|(ch_name, param_name)| {
            let gain_db = profile
                .channels
                .get(*ch_name)
                .map(|c| c.gain_db)
                .unwrap_or(-60.0); // Safe fallback
            (param_name.to_string(), gain_db_to_linear(gain_db))
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn gain_db_to_linear_unity() {
        let result = gain_db_to_linear(0.0);
        assert!((result - 1.0).abs() < 1e-10);
    }

    #[test]
    fn gain_db_to_linear_minus_20() {
        let result = gain_db_to_linear(-20.0);
        assert!((result - 0.1).abs() < 1e-10);
    }

    #[test]
    fn gain_db_to_linear_minus_60() {
        let result = gain_db_to_linear(-60.0);
        assert!((result - 0.001).abs() < 1e-6);
    }

    #[test]
    fn gain_db_to_linear_minus_64() {
        // -64 dB = 10^(-64/20) = 10^(-3.2) ≈ 0.000631
        let result = gain_db_to_linear(-64.0);
        assert!((result - 0.000630957).abs() < 1e-6);
    }

    #[test]
    fn gain_db_to_linear_positive_capped_d009() {
        // D-009: positive gain is capped at 1.0
        let result = gain_db_to_linear(6.0);
        assert_eq!(result, 1.0);
    }

    #[test]
    fn gain_db_to_linear_large_positive_capped() {
        let result = gain_db_to_linear(20.0);
        assert_eq!(result, 1.0);
    }

    #[test]
    fn parse_valid_venue_yaml() {
        let yaml = r#"
name: "test-venue"
description: "Test venue for unit tests"
channels:
  1_sat_l:
    gain_db: -20
    delay_ms: 0
    coefficients: "dirac.wav"
  2_sat_r:
    gain_db: -20
    delay_ms: 0
    coefficients: "dirac.wav"
  3_sub1_lp:
    gain_db: -20
    delay_ms: 0
    coefficients: "dirac.wav"
  4_sub2_lp:
    gain_db: -20
    delay_ms: 0
    coefficients: "dirac.wav"
  5_eng_l:
    gain_db: 0
    delay_ms: 0
    coefficients: "dirac.wav"
  6_eng_r:
    gain_db: 0
    delay_ms: 0
    coefficients: "dirac.wav"
  7_iem_l:
    gain_db: 0
    delay_ms: 0
    coefficients: "dirac.wav"
  8_iem_r:
    gain_db: 0
    delay_ms: 0
    coefficients: "dirac.wav"
"#;
        let profile = parse_venue(yaml).unwrap();
        assert_eq!(profile.name, "test-venue");
        assert_eq!(profile.channels.len(), 8);
    }

    #[test]
    fn parse_venue_missing_channel_rejected() {
        let yaml = r#"
name: "incomplete"
description: "Missing channels"
channels:
  1_sat_l:
    gain_db: -20
    delay_ms: 0
    coefficients: "dirac.wav"
"#;
        let err = parse_venue(yaml).unwrap_err();
        assert!(err.contains("missing channel"), "Error: {}", err);
    }

    #[test]
    fn parse_venue_invalid_yaml() {
        let err = parse_venue("not: [valid: yaml: {{").unwrap_err();
        assert!(err.contains("YAML parse error"), "Error: {}", err);
    }

    #[test]
    fn venue_gains_computes_correctly() {
        let yaml = r#"
name: "gains-test"
description: "test"
channels:
  1_sat_l:
    gain_db: -60
    delay_ms: 0
    coefficients: "dirac.wav"
  2_sat_r:
    gain_db: -60
    delay_ms: 0
    coefficients: "dirac.wav"
  3_sub1_lp:
    gain_db: -64
    delay_ms: 0
    coefficients: "dirac.wav"
  4_sub2_lp:
    gain_db: -64
    delay_ms: 0
    coefficients: "dirac.wav"
  5_eng_l:
    gain_db: 0
    delay_ms: 0
    coefficients: "dirac.wav"
  6_eng_r:
    gain_db: 0
    delay_ms: 0
    coefficients: "dirac.wav"
  7_iem_l:
    gain_db: 0
    delay_ms: 0
    coefficients: "dirac.wav"
  8_iem_r:
    gain_db: 0
    delay_ms: 0
    coefficients: "dirac.wav"
"#;
        let profile = parse_venue(yaml).unwrap();
        let gains = venue_gains(&profile);
        assert_eq!(gains.len(), 8);

        // Check param names match
        assert_eq!(gains[0].0, "gain_left_hp");
        assert_eq!(gains[4].0, "gain_hp_l");
        assert_eq!(gains[7].0, "gain_iem_r");

        // Check gain values
        assert!((gains[0].1 - 0.001).abs() < 1e-6); // -60 dB
        assert!((gains[2].1 - 0.000630957).abs() < 1e-6); // -64 dB
        assert!((gains[4].1 - 1.0).abs() < 1e-10); // 0 dB
    }

    #[test]
    fn venue_gains_positive_db_capped() {
        let yaml = r#"
name: "overcook"
description: "test"
channels:
  1_sat_l:
    gain_db: 6
    delay_ms: 0
    coefficients: "dirac.wav"
  2_sat_r:
    gain_db: 6
    delay_ms: 0
    coefficients: "dirac.wav"
  3_sub1_lp:
    gain_db: 6
    delay_ms: 0
    coefficients: "dirac.wav"
  4_sub2_lp:
    gain_db: 6
    delay_ms: 0
    coefficients: "dirac.wav"
  5_eng_l:
    gain_db: 6
    delay_ms: 0
    coefficients: "dirac.wav"
  6_eng_r:
    gain_db: 6
    delay_ms: 0
    coefficients: "dirac.wav"
  7_iem_l:
    gain_db: 6
    delay_ms: 0
    coefficients: "dirac.wav"
  8_iem_r:
    gain_db: 6
    delay_ms: 0
    coefficients: "dirac.wav"
"#;
        let profile = parse_venue(yaml).unwrap();
        let gains = venue_gains(&profile);
        for (_, mult) in &gains {
            assert_eq!(*mult, 1.0, "D-009: all gains must be capped at 1.0");
        }
    }

    #[test]
    fn list_venues_reads_real_configs() {
        // Test against the actual configs/venues/ directory.
        let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("configs/venues");

        if !dir.exists() {
            // Skip if not running from project root.
            return;
        }

        let venues = list_venues(&dir);
        assert!(venues.len() >= 3, "Expected at least 3 venue files");

        let names: Vec<_> = venues.iter().map(|v| v.name.as_str()).collect();
        assert!(names.contains(&"local-demo"), "Missing local-demo venue");
        assert!(names.contains(&"production"), "Missing production venue");
        assert!(names.contains(&"foh-passthrough"), "Missing foh-passthrough venue");
    }

    #[test]
    fn find_venue_by_name() {
        let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("configs/venues");

        if !dir.exists() {
            return;
        }

        let profile = find_venue(&dir, "local-demo").unwrap();
        assert_eq!(profile.name, "local-demo");
        assert_eq!(profile.channels.len(), 8);
    }

    #[test]
    fn find_venue_not_found() {
        let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("configs/venues");

        if !dir.exists() {
            return;
        }

        let err = find_venue(&dir, "nonexistent-venue").unwrap_err();
        assert!(err.contains("venue not found"), "Error: {}", err);
    }

    #[test]
    fn list_venues_empty_dir() {
        let tmp = std::env::temp_dir().join("venue_test_empty");
        let _ = fs::create_dir_all(&tmp);
        let venues = list_venues(&tmp);
        assert!(venues.is_empty());
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn list_venues_nonexistent_dir() {
        let venues = list_venues(Path::new("/tmp/venue_test_nonexistent_dir_xyz"));
        assert!(venues.is_empty());
    }

    #[test]
    fn channel_names_match_gain_param_names_count() {
        assert_eq!(CHANNEL_NAMES.len(), GAIN_PARAM_NAMES.len());
        assert_eq!(CHANNEL_NAMES.len(), 8);
    }

    // -----------------------------------------------------------------------
    // Venue persistence (US-123)
    // -----------------------------------------------------------------------

    #[test]
    fn persist_and_load_venue_name() {
        let tmp = std::env::temp_dir().join("venue_persist_test");
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();

        persist_venue_name("test-venue-1", &tmp);

        let loaded = load_persisted_venue(&tmp);
        assert_eq!(loaded, Some("test-venue-1".to_string()));

        // Overwrite — should create backup.
        persist_venue_name("test-venue-2", &tmp);
        let loaded = load_persisted_venue(&tmp);
        assert_eq!(loaded, Some("test-venue-2".to_string()));

        // Backup file should contain old value.
        let bak = fs::read_to_string(tmp.join("last-venue.bak")).unwrap();
        assert_eq!(bak.trim(), "test-venue-1");

        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn load_persisted_venue_fallback_to_backup() {
        let tmp = std::env::temp_dir().join("venue_persist_bak_test");
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();

        // Write only the backup file.
        fs::write(tmp.join("last-venue.bak"), "backup-venue").unwrap();

        let loaded = load_persisted_venue(&tmp);
        assert_eq!(loaded, Some("backup-venue".to_string()));

        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn load_persisted_venue_returns_none_when_empty() {
        let tmp = std::env::temp_dir().join("venue_persist_empty_test");
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();

        let loaded = load_persisted_venue(&tmp);
        assert_eq!(loaded, None);

        let _ = fs::remove_dir_all(&tmp);
    }

    // -----------------------------------------------------------------------
    // Venue name validation (US-113)
    // -----------------------------------------------------------------------

    #[test]
    fn validate_venue_name_accepts_valid() {
        assert!(validate_venue_name("foh-passthrough").is_ok());
        assert!(validate_venue_name("local-demo").is_ok());
        assert!(validate_venue_name("production").is_ok());
        assert!(validate_venue_name("my_venue_2").is_ok());
        assert!(validate_venue_name("ABC123").is_ok());
    }

    #[test]
    fn validate_venue_name_rejects_empty() {
        let err = validate_venue_name("").unwrap_err();
        assert!(err.contains("empty"), "Error: {}", err);
    }

    #[test]
    fn validate_venue_name_rejects_path_traversal() {
        let err = validate_venue_name("../../../etc/passwd").unwrap_err();
        assert!(err.contains("invalid character"), "Error: {}", err);
    }

    #[test]
    fn validate_venue_name_rejects_path_separator() {
        assert!(validate_venue_name("foo/bar").is_err());
        assert!(validate_venue_name("foo\\bar").is_err());
    }

    #[test]
    fn validate_venue_name_rejects_dots() {
        assert!(validate_venue_name("foo.bar").is_err());
        assert!(validate_venue_name("..").is_err());
    }

    #[test]
    fn validate_venue_name_rejects_spaces() {
        assert!(validate_venue_name("foo bar").is_err());
    }

    #[test]
    fn validate_venue_name_rejects_too_long() {
        let long_name = "a".repeat(129);
        let err = validate_venue_name(&long_name).unwrap_err();
        assert!(err.contains("too long"), "Error: {}", err);
    }

    // -----------------------------------------------------------------------
    // Default venue loading (US-113)
    // -----------------------------------------------------------------------

    #[test]
    fn load_default_venue_on_first_boot() {
        let venues_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("configs/venues");

        if !venues_dir.exists() {
            return;
        }

        let state_dir = std::env::temp_dir().join("us113_default_venue_test");
        let _ = fs::remove_dir_all(&state_dir);

        let name = load_default_venue(&venues_dir, &state_dir).unwrap();
        assert_eq!(name, "foh-passthrough");

        // Verify it was persisted.
        let persisted = load_persisted_venue(&state_dir);
        assert_eq!(persisted, Some("foh-passthrough".to_string()));

        let _ = fs::remove_dir_all(&state_dir);
    }

    #[test]
    fn load_default_venue_nonexistent_venue_dir() {
        let state_dir = std::env::temp_dir().join("us113_nodir_test");
        let _ = fs::remove_dir_all(&state_dir);

        let err = load_default_venue(
            Path::new("/tmp/us113_nonexistent_venues_xyz"),
            &state_dir,
        )
        .unwrap_err();
        assert!(
            err.contains("venue not found") || err.contains("cannot read"),
            "Error: {}",
            err,
        );

        let _ = fs::remove_dir_all(&state_dir);
    }

    // -----------------------------------------------------------------------
    // FOH passthrough venue config (US-113)
    // -----------------------------------------------------------------------

    #[test]
    fn foh_passthrough_venue_parses_and_validates() {
        let venues_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("configs/venues");

        if !venues_dir.exists() {
            return;
        }

        let profile = find_venue(&venues_dir, "foh-passthrough").unwrap();
        assert_eq!(profile.name, "foh-passthrough");
        assert_eq!(profile.channels.len(), 8);

        // Verify all 8 channels exist.
        for ch in CHANNEL_NAMES {
            assert!(
                profile.channels.contains_key(*ch),
                "Missing channel: {}",
                ch,
            );
        }
    }

    #[test]
    fn foh_passthrough_unity_gains() {
        let venues_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("configs/venues");

        if !venues_dir.exists() {
            return;
        }

        let profile = find_venue(&venues_dir, "foh-passthrough").unwrap();
        let gains = venue_gains(&profile);
        assert_eq!(gains.len(), 8);

        // All channels should be unity gain (0 dB = Mult 1.0).
        for (param_name, mult) in &gains {
            assert!(
                (*mult - 1.0).abs() < 1e-10,
                "Expected unity gain for {}, got {}",
                param_name,
                mult,
            );
        }
    }

    #[test]
    fn foh_passthrough_all_dirac_coefficients() {
        let venues_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("configs/venues");

        if !venues_dir.exists() {
            return;
        }

        let profile = find_venue(&venues_dir, "foh-passthrough").unwrap();
        for (ch_name, ch_config) in &profile.channels {
            assert_eq!(
                ch_config.coefficients, "dirac.wav",
                "Channel {} should use dirac.wav, got {}",
                ch_name, ch_config.coefficients,
            );
        }
    }

    #[test]
    fn foh_passthrough_zero_delay() {
        let venues_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("configs/venues");

        if !venues_dir.exists() {
            return;
        }

        let profile = find_venue(&venues_dir, "foh-passthrough").unwrap();
        for (ch_name, ch_config) in &profile.channels {
            assert!(
                ch_config.delay_ms.abs() < 1e-10,
                "Channel {} should have zero delay, got {}",
                ch_name, ch_config.delay_ms,
            );
        }
    }
}
