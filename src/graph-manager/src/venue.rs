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
/// Uses `PI4AUDIO_STATE_DIR` env var if set (for testing), otherwise
/// falls back to `/var/lib/pi4audio`.
fn state_dir() -> PathBuf {
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
pub fn persist_venue_name(name: &str) {
    let dir = state_dir();
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
pub fn load_persisted_venue() -> Option<String> {
    let dir = state_dir();
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
        assert!(venues.len() >= 2, "Expected at least 2 venue files");

        let names: Vec<_> = venues.iter().map(|v| v.name.as_str()).collect();
        assert!(names.contains(&"local-demo"), "Missing local-demo venue");
        assert!(names.contains(&"production"), "Missing production venue");
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
        std::env::set_var("PI4AUDIO_STATE_DIR", &tmp);

        persist_venue_name("test-venue-1");

        let loaded = load_persisted_venue();
        assert_eq!(loaded, Some("test-venue-1".to_string()));

        // Overwrite — should create backup.
        persist_venue_name("test-venue-2");
        let loaded = load_persisted_venue();
        assert_eq!(loaded, Some("test-venue-2".to_string()));

        // Backup file should contain old value.
        let bak = fs::read_to_string(tmp.join("last-venue.bak")).unwrap();
        assert_eq!(bak.trim(), "test-venue-1");

        let _ = fs::remove_dir_all(&tmp);
        std::env::remove_var("PI4AUDIO_STATE_DIR");
    }

    #[test]
    fn load_persisted_venue_fallback_to_backup() {
        let tmp = std::env::temp_dir().join("venue_persist_bak_test");
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("PI4AUDIO_STATE_DIR", &tmp);

        // Write only the backup file.
        fs::write(tmp.join("last-venue.bak"), "backup-venue").unwrap();

        let loaded = load_persisted_venue();
        assert_eq!(loaded, Some("backup-venue".to_string()));

        let _ = fs::remove_dir_all(&tmp);
        std::env::remove_var("PI4AUDIO_STATE_DIR");
    }

    #[test]
    fn load_persisted_venue_returns_none_when_empty() {
        let tmp = std::env::temp_dir().join("venue_persist_empty_test");
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("PI4AUDIO_STATE_DIR", &tmp);

        let loaded = load_persisted_venue();
        assert_eq!(loaded, None);

        let _ = fs::remove_dir_all(&tmp);
        std::env::remove_var("PI4AUDIO_STATE_DIR");
    }
}
