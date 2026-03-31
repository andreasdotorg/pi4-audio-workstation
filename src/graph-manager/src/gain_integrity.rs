//! Gain integrity check — periodic Mult <= 1.0 verification (T-044-5).
//!
//! Polls gain builtin parameters via `pw-dump` every 30s and verifies all
//! Mult values are <= 1.0. If any Mult > 1.0 (which would indicate
//! amplification rather than attenuation), triggers the watchdog's safety
//! mute mechanism.
//!
//! This is a **control-plane** check — not on the safety-critical path.
//! The watchdog (T-044-4) handles the actual mute. This module detects
//! a different failure mode: accidental `pw-cli set-param` errors that
//! set Mult > 1.0, which would bypass the gain staging limits.
//!
//! ## Design
//!
//! - **Pure logic:** `GainIntegrityCheck` is a state machine that takes
//!   parsed gain values and returns a check result. No PW API calls.
//! - **Subprocess:** The caller runs `pw-dump` and parses the output.
//!   This is the control plane — 30s interval, subprocess overhead is
//!   acceptable (AE approved).
//! - **Threshold:** Mult must be <= 1.0. Values > 1.0 represent
//!   amplification. Production values are 0.001 (mains) and 0.000631
//!   (subs) — well below 1.0.

use crate::watchdog::GAIN_PARAM_NAMES;

/// Result of a single gain integrity check cycle.
#[derive(Debug, Clone, PartialEq)]
pub enum GainCheckResult {
    /// All gain params present with Mult <= 1.0.
    AllOk {
        /// (gain_name, mult_value) pairs for all checked params.
        values: Vec<(String, f64)>,
    },
    /// One or more gain params have Mult > 1.0.
    Violation {
        /// (gain_name, mult_value) pairs for violating params.
        violating: Vec<(String, f64)>,
        /// (gain_name, mult_value) pairs for all checked params.
        all_values: Vec<(String, f64)>,
    },
    /// One or more gain params are missing from the graph.
    /// The watchdog (T-044-4) handles missing nodes — this module
    /// does not duplicate that responsibility.
    MissingNodes {
        missing: Vec<String>,
    },
    /// pw-dump subprocess failed (timeout, parse error, etc).
    /// Logged as a warning, not a safety event.
    CheckFailed {
        reason: String,
    },
}

/// Gain integrity check state.
///
/// Tracks the most recent check result and consecutive violation count.
/// Pure state — no PW API calls. The caller (main loop timer) drives
/// the checks and applies any mute actions.
pub struct GainIntegrityCheck {
    /// Most recent check result.
    last_result: Option<GainCheckResult>,
    /// Number of consecutive successful checks.
    consecutive_ok: u32,
    /// Number of consecutive violations (resets on OK).
    consecutive_violations: u32,
    /// Total number of checks performed.
    total_checks: u32,
}

impl GainIntegrityCheck {
    /// Create a new gain integrity check in the initial state.
    pub fn new() -> Self {
        Self {
            last_result: None,
            consecutive_ok: 0,
            consecutive_violations: 0,
            total_checks: 0,
        }
    }

    /// Evaluate gain values and return the check result.
    ///
    /// `gains` is a list of (gain_name, mult_value) pairs from pw-dump.
    /// Only gain names listed in `GAIN_PARAM_NAMES` are checked.
    ///
    /// Returns the check result and updates internal state.
    pub fn check(&mut self, gains: &[(String, f64)]) -> GainCheckResult {
        self.total_checks += 1;

        // Check which expected gain params are present.
        let missing: Vec<String> = GAIN_PARAM_NAMES
            .iter()
            .filter(|name| !gains.iter().any(|(n, _)| n == *name))
            .map(|name| name.to_string())
            .collect();

        if !missing.is_empty() {
            let result = GainCheckResult::MissingNodes { missing };
            self.last_result = Some(result.clone());
            return result;
        }

        // Check for violations (Mult > 1.0).
        let violating: Vec<(String, f64)> = gains
            .iter()
            .filter(|(name, mult)| {
                GAIN_PARAM_NAMES.contains(&name.as_str()) && *mult > 1.0
            })
            .cloned()
            .collect();

        let result = if violating.is_empty() {
            self.consecutive_ok += 1;
            self.consecutive_violations = 0;
            GainCheckResult::AllOk {
                values: gains.to_vec(),
            }
        } else {
            self.consecutive_ok = 0;
            self.consecutive_violations += 1;
            log::error!(
                "GAIN INTEGRITY: Mult > 1.0 detected on {} param(s): {:?}",
                violating.len(),
                violating,
            );
            GainCheckResult::Violation {
                violating,
                all_values: gains.to_vec(),
            }
        };

        self.last_result = Some(result.clone());
        result
    }

    /// Record a check failure (subprocess error, parse error, etc).
    pub fn record_failure(&mut self, reason: String) {
        self.total_checks += 1;
        let result = GainCheckResult::CheckFailed { reason };
        self.last_result = Some(result);
    }

    /// Get the current status for RPC responses.
    pub fn status(&self) -> GainIntegrityStatus {
        GainIntegrityStatus {
            last_result: self.last_result.as_ref().map(describe_result),
            consecutive_ok: self.consecutive_ok,
            consecutive_violations: self.consecutive_violations,
            total_checks: self.total_checks,
        }
    }
}

/// Describe a check result as a string for RPC responses.
fn describe_result(result: &GainCheckResult) -> String {
    match result {
        GainCheckResult::AllOk { values } => {
            let pairs: Vec<String> = values
                .iter()
                .map(|(n, v)| format!("{}={:.6}", n, v))
                .collect();
            format!("ok: {}", pairs.join(", "))
        }
        GainCheckResult::Violation { violating, .. } => {
            let pairs: Vec<String> = violating
                .iter()
                .map(|(n, v)| format!("{}={:.6}", n, v))
                .collect();
            format!("VIOLATION: {}", pairs.join(", "))
        }
        GainCheckResult::MissingNodes { missing } => {
            format!("missing: {}", missing.join(", "))
        }
        GainCheckResult::CheckFailed { reason } => {
            format!("failed: {}", reason)
        }
    }
}

/// Serializable gain integrity status for RPC responses.
#[derive(Debug, Clone, serde::Serialize)]
pub struct GainIntegrityStatus {
    pub last_result: Option<String>,
    pub consecutive_ok: u32,
    pub consecutive_violations: u32,
    pub total_checks: u32,
}

/// Parse gain builtin Mult values from `pw-dump` JSON output.
///
/// Finds the `pi4audio-convolver` node and extracts prefixed gain
/// param values (e.g., `gain_left_hp:Mult`) from its `Props[].params`
/// flat array. Returns `(gain_name, mult_value)` pairs where
/// `gain_name` matches `GAIN_PARAM_NAMES` (without the `:Mult` suffix).
///
/// The gain builtins are internal to the filter-chain module — they
/// appear as prefixed params on the convolver node, NOT as separate
/// PW nodes.
///
/// `pw-dump` outputs a JSON array of PipeWire objects. The convolver
/// node's Props params array contains alternating key-value entries:
/// ```json
/// {
///   "type": "PipeWire:Interface:Node",
///   "info": {
///     "props": { "node.name": "pi4audio-convolver", ... },
///     "params": {
///       "Props": [
///         { "params": [
///             "gain_left_hp:Mult", 0.001,
///             "gain_right_hp:Mult", 0.001,
///             "gain_sub1_lp:Mult", 0.000631,
///             "gain_sub2_lp:Mult", 0.000631
///         ] }
///       ]
///     }
///   }
/// }
/// ```
pub fn parse_pw_dump_gains(json_str: &str) -> Result<Vec<(String, f64)>, String> {
    use crate::watchdog::CONVOLVER_NODE_NAME;

    let objects: serde_json::Value =
        serde_json::from_str(json_str).map_err(|e| format!("JSON parse error: {}", e))?;

    let array = objects
        .as_array()
        .ok_or_else(|| "pw-dump output is not a JSON array".to_string())?;

    // Find the convolver node.
    let convolver_info = array
        .iter()
        .filter(|obj| {
            obj.get("type").and_then(|t| t.as_str()) == Some("PipeWire:Interface:Node")
        })
        .find_map(|obj| {
            let info = obj.get("info")?;
            let node_name = info
                .get("props")
                .and_then(|p| p.get("node.name"))
                .and_then(|n| n.as_str())?;
            if node_name == CONVOLVER_NODE_NAME {
                Some(info)
            } else {
                None
            }
        });

    let info = match convolver_info {
        Some(i) => i,
        None => return Ok(Vec::new()), // Convolver not in dump — watchdog handles this.
    };

    Ok(extract_gain_params_from_convolver(info))
}

/// Extract prefixed gain Mult values from the convolver node's Props params.
///
/// Scans `info.params.Props[].params` for entries matching
/// `"<gain_name>:Mult"` where `<gain_name>` is in `GAIN_PARAM_NAMES`.
/// The params array is a flat alternating list: [key, value, key, value, ...].
fn extract_gain_params_from_convolver(info: &serde_json::Value) -> Vec<(String, f64)> {
    let mut gains = Vec::new();

    let props_array = match info
        .get("params")
        .and_then(|p| p.get("Props"))
        .and_then(|p| p.as_array())
    {
        Some(a) => a,
        None => return gains,
    };

    for prop_obj in props_array {
        let prop_params = match prop_obj.get("params").and_then(|p| p.as_array()) {
            Some(a) => a,
            None => continue,
        };

        // Flat alternating array: ["gain_left_hp:Mult", 0.001, "gain_right_hp:Mult", 0.001, ...]
        let mut iter = prop_params.iter();
        while let Some(key) = iter.next() {
            if let Some(key_str) = key.as_str() {
                // Check if this is a "<gain_name>:Mult" entry.
                if let Some(gain_name) = key_str.strip_suffix(":Mult") {
                    if GAIN_PARAM_NAMES.contains(&gain_name) {
                        if let Some(val) = iter.next() {
                            if let Some(f) = val.as_f64() {
                                gains.push((gain_name.to_string(), f));
                            }
                        }
                        continue;
                    }
                }
            }
            // Skip the value for non-matching keys.
            let _ = iter.next();
        }
    }

    gains
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------------
    // GainIntegrityCheck state machine
    // -----------------------------------------------------------------------

    fn production_gains() -> Vec<(String, f64)> {
        vec![
            ("gain_left_hp".to_string(), 0.001),
            ("gain_right_hp".to_string(), 0.001),
            ("gain_sub1_lp".to_string(), 0.000631),
            ("gain_sub2_lp".to_string(), 0.000631),
            ("gain_hp_l".to_string(), 1.0),
            ("gain_hp_r".to_string(), 1.0),
            ("gain_iem_l".to_string(), 1.0),
            ("gain_iem_r".to_string(), 1.0),
        ]
    }

    #[test]
    fn new_check_is_empty() {
        let check = GainIntegrityCheck::new();
        assert!(check.last_result.is_none());
        assert_eq!(check.total_checks, 0);
        assert_eq!(check.consecutive_ok, 0);
        assert_eq!(check.consecutive_violations, 0);
    }

    #[test]
    fn all_ok_with_production_values() {
        let mut check = GainIntegrityCheck::new();
        let result = check.check(&production_gains());
        assert!(matches!(result, GainCheckResult::AllOk { .. }));
        assert_eq!(check.consecutive_ok, 1);
        assert_eq!(check.total_checks, 1);
    }

    #[test]
    fn violation_detected_when_mult_exceeds_one() {
        let mut check = GainIntegrityCheck::new();
        let mut gains = production_gains();
        gains[0] = ("gain_left_hp".to_string(), 1.5);
        let result = check.check(&gains);
        match result {
            GainCheckResult::Violation { violating, .. } => {
                assert_eq!(violating.len(), 1);
                assert_eq!(violating[0].0, "gain_left_hp");
                assert_eq!(violating[0].1, 1.5);
            }
            other => panic!("expected Violation, got {:?}", other),
        }
        assert_eq!(check.consecutive_violations, 1);
        assert_eq!(check.consecutive_ok, 0);
    }

    #[test]
    fn mult_exactly_one_is_ok() {
        let mut check = GainIntegrityCheck::new();
        let gains: Vec<(String, f64)> = GAIN_PARAM_NAMES
            .iter()
            .map(|n| (n.to_string(), 1.0))
            .collect();
        let result = check.check(&gains);
        assert!(matches!(result, GainCheckResult::AllOk { .. }));
    }

    #[test]
    fn mult_slightly_above_one_is_violation() {
        let mut check = GainIntegrityCheck::new();
        let mut gains = production_gains();
        gains[0] = ("gain_left_hp".to_string(), 1.0001);
        let result = check.check(&gains);
        assert!(matches!(result, GainCheckResult::Violation { .. }));
    }

    #[test]
    fn multiple_violations() {
        let mut check = GainIntegrityCheck::new();
        let mut gains = production_gains();
        gains[0] = ("gain_left_hp".to_string(), 2.0);
        gains[1] = ("gain_right_hp".to_string(), 3.0);
        let result = check.check(&gains);
        match result {
            GainCheckResult::Violation { violating, .. } => {
                assert_eq!(violating.len(), 2);
            }
            other => panic!("expected Violation, got {:?}", other),
        }
    }

    #[test]
    fn missing_nodes_detected() {
        let mut check = GainIntegrityCheck::new();
        let gains = vec![
            ("gain_left_hp".to_string(), 0.001),
            // Missing: 7 other gain params
        ];
        let result = check.check(&gains);
        match result {
            GainCheckResult::MissingNodes { missing } => {
                assert_eq!(missing.len(), 7);
                assert!(missing.contains(&"gain_right_hp".to_string()));
                assert!(missing.contains(&"gain_sub1_lp".to_string()));
                assert!(missing.contains(&"gain_sub2_lp".to_string()));
                assert!(missing.contains(&"gain_hp_l".to_string()));
                assert!(missing.contains(&"gain_hp_r".to_string()));
                assert!(missing.contains(&"gain_iem_l".to_string()));
                assert!(missing.contains(&"gain_iem_r".to_string()));
            }
            other => panic!("expected MissingNodes, got {:?}", other),
        }
    }

    #[test]
    fn consecutive_counters_track_correctly() {
        let mut check = GainIntegrityCheck::new();

        // 3 OK checks.
        for _ in 0..3 {
            check.check(&production_gains());
        }
        assert_eq!(check.consecutive_ok, 3);
        assert_eq!(check.consecutive_violations, 0);

        // 1 violation resets ok counter.
        let mut violation_gains = production_gains();
        violation_gains[0] = ("gain_left_hp".to_string(), 2.0);
        check.check(&violation_gains);
        assert_eq!(check.consecutive_ok, 0);
        assert_eq!(check.consecutive_violations, 1);

        // OK resets violation counter.
        check.check(&production_gains());
        assert_eq!(check.consecutive_ok, 1);
        assert_eq!(check.consecutive_violations, 0);
        assert_eq!(check.total_checks, 5);
    }

    #[test]
    fn record_failure() {
        let mut check = GainIntegrityCheck::new();
        check.record_failure("pw-dump timeout".to_string());
        assert_eq!(check.total_checks, 1);
        match &check.last_result {
            Some(GainCheckResult::CheckFailed { reason }) => {
                assert_eq!(reason, "pw-dump timeout");
            }
            other => panic!("expected CheckFailed, got {:?}", other),
        }
    }

    #[test]
    fn ignores_non_gain_params() {
        let mut check = GainIntegrityCheck::new();
        let mut gains = production_gains();
        gains.push(("some_other_param".to_string(), 5.0)); // not a gain param
        let result = check.check(&gains);
        // The non-gain param with Mult 5.0 should be ignored.
        assert!(matches!(result, GainCheckResult::AllOk { .. }));
    }

    // -----------------------------------------------------------------------
    // Status serialization
    // -----------------------------------------------------------------------

    #[test]
    fn status_serializable() {
        let mut check = GainIntegrityCheck::new();
        check.check(&production_gains());
        let status = check.status();
        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("\"consecutive_ok\":1"));
        assert!(json.contains("\"total_checks\":1"));
    }

    #[test]
    fn status_describes_violation() {
        let mut check = GainIntegrityCheck::new();
        let mut gains = production_gains();
        gains[0] = ("gain_left_hp".to_string(), 2.0);
        check.check(&gains);
        let status = check.status();
        assert!(status.last_result.as_ref().unwrap().contains("VIOLATION"));
    }

    // -----------------------------------------------------------------------
    // pw-dump parsing — convolver node with prefixed gain params
    // -----------------------------------------------------------------------

    #[test]
    fn parse_pw_dump_gains_empty_array() {
        let json = "[]";
        let gains = parse_pw_dump_gains(json).unwrap();
        assert!(gains.is_empty());
    }

    #[test]
    fn parse_pw_dump_gains_convolver_with_gain_params() {
        let json = r#"[
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": { "node.name": "pi4audio-convolver" },
                    "params": {
                        "Props": [
                            { "params": [
                                "gain_left_hp:Mult", 0.001,
                                "gain_right_hp:Mult", 0.001,
                                "gain_sub1_lp:Mult", 0.000631,
                                "gain_sub2_lp:Mult", 0.000631,
                                "gain_hp_l:Mult", 1.0,
                                "gain_hp_r:Mult", 1.0,
                                "gain_iem_l:Mult", 1.0,
                                "gain_iem_r:Mult", 1.0
                            ] }
                        ]
                    }
                }
            },
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": { "node.name": "pi4audio-convolver-out" },
                    "params": {}
                }
            }
        ]"#;

        let gains = parse_pw_dump_gains(json).unwrap();
        assert_eq!(gains.len(), 8);

        let left = gains.iter().find(|(n, _)| n == "gain_left_hp").unwrap();
        assert_eq!(left.1, 0.001);

        let sub1 = gains.iter().find(|(n, _)| n == "gain_sub1_lp").unwrap();
        assert_eq!(sub1.1, 0.000631);

        let hp_l = gains.iter().find(|(n, _)| n == "gain_hp_l").unwrap();
        assert_eq!(hp_l.1, 1.0);
    }

    #[test]
    fn parse_pw_dump_gains_no_convolver_returns_empty() {
        let json = r#"[
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": { "node.name": "some-other-node" },
                    "params": {}
                }
            }
        ]"#;

        let gains = parse_pw_dump_gains(json).unwrap();
        assert!(gains.is_empty());
    }

    #[test]
    fn parse_pw_dump_gains_ignores_non_node_objects() {
        let json = r#"[
            {
                "type": "PipeWire:Interface:Link",
                "info": {}
            },
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": { "node.name": "pi4audio-convolver" },
                    "params": {
                        "Props": [
                            { "params": [
                                "gain_left_hp:Mult", 0.001
                            ] }
                        ]
                    }
                }
            }
        ]"#;

        let gains = parse_pw_dump_gains(json).unwrap();
        assert_eq!(gains.len(), 1);
        assert_eq!(gains[0].0, "gain_left_hp");
    }

    #[test]
    fn parse_pw_dump_gains_invalid_json() {
        let result = parse_pw_dump_gains("not json");
        assert!(result.is_err());
    }

    #[test]
    fn parse_pw_dump_gains_convolver_without_gain_params() {
        let json = r#"[
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": { "node.name": "pi4audio-convolver" },
                    "params": {
                        "Props": [
                            { "volume": 0.5 }
                        ]
                    }
                }
            }
        ]"#;

        let gains = parse_pw_dump_gains(json).unwrap();
        // Convolver found but no gain params — empty.
        assert!(gains.is_empty());
    }

    #[test]
    fn parse_pw_dump_gains_ignores_non_gain_prefixed_params() {
        let json = r#"[
            {
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": { "node.name": "pi4audio-convolver" },
                    "params": {
                        "Props": [
                            { "params": [
                                "gain_left_hp:Mult", 0.001,
                                "convolver_left:blocksize", 8192,
                                "gain_right_hp:Mult", 0.001
                            ] }
                        ]
                    }
                }
            }
        ]"#;

        let gains = parse_pw_dump_gains(json).unwrap();
        assert_eq!(gains.len(), 2);
        assert_eq!(gains[0].0, "gain_left_hp");
        assert_eq!(gains[1].0, "gain_right_hp");
    }
}
