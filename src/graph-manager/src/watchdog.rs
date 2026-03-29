//! Filter-chain watchdog — safety mute via native PipeWire API (T-044-4).
//!
//! Monitors critical audio nodes in the PipeWire graph and latches a safety
//! MUTE when any disappear. The mute sets Mult=0.0 on the 4 gain builtins
//! inside the filter-chain convolver node. If the convolver node itself is
//! gone, the fallback destroys ALL links to the USBStreamer input ports.
//!
//! ## Safety model
//!
//! This is SAFETY-CRITICAL code. The design is fail-safe:
//! - Any error in the mute path → attempt mute anyway (best-effort)
//! - Mute is LATCHED: once triggered, stays muted until explicit unlatch
//! - Unlatch requires an RPC command (`watchdog_unlatch`)
//! - The watchdog never increases gain — it only sets Mult to 0.0
//!
//! ## Monitored nodes (2)
//!
//! | Node name                | Role                        |
//! |--------------------------|-----------------------------|
//! | `pi4audio-convolver`     | Filter-chain capture side   |
//! | `pi4audio-convolver-out` | Filter-chain playback side  |
//!
//! The 4 gain builtins (`gain_left_hp`, `gain_right_hp`, `gain_sub1_lp`,
//! `gain_sub2_lp`) are internal to the filter-chain module — they appear
//! as parameters on the `pi4audio-convolver` node, NOT as separate PW
//! graph nodes. They are addressed by prefixed param name (e.g.,
//! `gain_left_hp:Mult`) when setting Mult values.
//!
//! ## Mute mechanism
//!
//! **Primary:** Set Mult parameter to 0.0 on the convolver node for all 4
//! gain builtins using `pw_node_set_param()` via `pipewire-rs` with prefixed
//! param names (e.g., `gain_left_hp:Mult`). Target: <1ms per param, <5ms total.
//!
//! **Fallback:** If the convolver node itself is gone (can't set params on
//! a nonexistent node), destroy ALL links to USBStreamer input ports using
//! `pw_registry::destroy_global()`.
//!
//! ## Thread model
//!
//! All watchdog state lives on the PW main loop thread (single-threaded,
//! `Rc<RefCell<>>`). The `check()` method is called from the registry
//! listener after every graph mutation. The unlatch command arrives via
//! the RPC command channel (processed by the 50ms timer callback).
//!
//! ## Response time
//!
//! Target: <21ms (1 PipeWire graph cycle at quantum 1024). Since registry
//! events are push-based (no polling), the watchdog fires within the same
//! PW main loop iteration that processes the node removal event. The native
//! PW API (`pw_registry_bind` + `pw_node_set_param` via `pipewire-sys` FFI)
//! adds <1ms per node — well within budget. No subprocess is used.

use crate::graph::GraphState;
use crate::routing::NodeMatch;

/// Names of the 2 monitored PW graph nodes.
///
/// If ANY of these disappear from the PW graph, the watchdog triggers.
/// The gain builtins are internal to the filter-chain module and are NOT
/// separate PW nodes — they are accessed as params on the convolver node.
pub const MONITORED_NODES: &[&str] = &[
    "pi4audio-convolver",
    "pi4audio-convolver-out",
];

/// Convolver capture-side node name — used to locate the node for gain
/// param muting (the gain builtins live inside this node).
pub const CONVOLVER_NODE_NAME: &str = "pi4audio-convolver";

/// Prefixed param names for the 4 gain builtins inside the filter-chain.
/// These are used with `pw_node_set_param()` on the convolver node to
/// set Mult=0.0 on each gain stage. Also used by the gain integrity
/// check to verify Mult <= 1.0.
pub const GAIN_PARAM_NAMES: &[&str] = &[
    "gain_left_hp",
    "gain_right_hp",
    "gain_sub1_lp",
    "gain_sub2_lp",
];

/// USBStreamer node name prefix — used for fallback link destruction.
const USBSTREAMER_OUT_PREFIX: &str = "alsa_output.usb-MiniDSP_USBStreamer";

/// Result of a watchdog check cycle.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WatchdogAction {
    /// All monitored nodes present, no action needed.
    AllPresent,
    /// Already latched — no new action (already muted).
    AlreadyLatched,
    /// Convolver node available — set Mult=0.0 on gain builtins via
    /// `pw_node_set_param()` on the convolver node with prefixed param names.
    SetGainMute {
        /// PW node ID of the convolver (target for set_param calls).
        convolver_node_id: u32,
    },
    /// Convolver node gone — destroy USBStreamer links as fallback.
    DestroyUsbLinks {
        /// PW link IDs to destroy.
        link_ids: Vec<u32>,
    },
}

/// Watchdog state machine.
///
/// Tracks whether the safety mute is latched and which nodes were missing
/// when the latch was triggered. Pure state — no PW API calls. The caller
/// (registry listener) applies the returned actions.
///
/// ## Startup grace period
///
/// The watchdog starts **unarmed**. It arms automatically once both
/// monitored nodes have been seen in a single `check()` call. Until
/// armed, `check()` returns `AllPresent` even if nodes are missing.
/// This prevents false latches during PipeWire startup when nodes
/// register incrementally. Once armed, any node disappearance triggers
/// immediately.
pub struct Watchdog {
    /// Whether the watchdog is armed (all nodes seen at least once).
    armed: bool,
    /// Whether the safety mute is currently latched.
    latched: bool,
    /// Node names that were missing when the latch was triggered.
    missing_at_latch: Vec<String>,
    /// Pre-mute Mult values stored for unlatch restoration.
    /// Key: gain node name, Value: Mult value before mute.
    pre_mute_gains: Vec<(String, f64)>,
}

impl Watchdog {
    /// Create a new watchdog in the unarmed, unlatched state.
    pub fn new() -> Self {
        Self {
            armed: false,
            latched: false,
            missing_at_latch: Vec::new(),
            pre_mute_gains: Vec::new(),
        }
    }

    /// Whether the watchdog is armed (all monitored nodes seen at least once).
    pub fn is_armed(&self) -> bool {
        self.armed
    }

    /// Whether the safety mute is currently latched.
    pub fn is_latched(&self) -> bool {
        self.latched
    }

    /// Node names that were missing when the latch was triggered.
    pub fn missing_at_latch(&self) -> &[String] {
        &self.missing_at_latch
    }

    /// Pre-mute gain values (for unlatch restoration).
    pub fn pre_mute_gains(&self) -> &[(String, f64)] {
        &self.pre_mute_gains
    }

    /// Check the graph state and determine what action to take.
    ///
    /// Called after every graph mutation (registry event). This is a pure
    /// function — it reads GraphState and returns an action. The caller
    /// applies the action via PW API calls.
    ///
    /// ## Logic
    ///
    /// 1. If already latched → `AlreadyLatched` (no-op).
    /// 2. Check both monitored nodes. If all present → `AllPresent`.
    /// 3. If any missing → latch the mute and determine mechanism:
    ///    a. If convolver node present → `SetGainMute` (primary: set
    ///       Mult=0.0 on gain builtins via convolver node params).
    ///    b. If convolver node gone → `DestroyUsbLinks` (fallback).
    pub fn check(&mut self, graph: &GraphState) -> WatchdogAction {
        if self.latched {
            return WatchdogAction::AlreadyLatched;
        }

        // Check which monitored nodes are missing.
        let missing: Vec<String> = MONITORED_NODES
            .iter()
            .filter(|name| graph.node_by_name(name).is_none())
            .map(|name| name.to_string())
            .collect();

        if missing.is_empty() {
            if !self.armed {
                self.armed = true;
                log::info!(
                    "WATCHDOG: Armed — all {} monitored nodes present",
                    MONITORED_NODES.len(),
                );
            }
            return WatchdogAction::AllPresent;
        }

        // Grace period: don't latch until armed (all nodes seen once).
        if !self.armed {
            return WatchdogAction::AllPresent;
        }

        // Latch the mute.
        self.latched = true;
        self.missing_at_latch = missing.clone();
        log::error!(
            "WATCHDOG: Safety mute LATCHED — missing nodes: {:?}",
            missing,
        );

        // Determine mute mechanism based on convolver node availability.
        // The gain builtins are params on the convolver node, so we can
        // only set Mult=0.0 if the convolver node is still in the graph.
        if let Some(convolver) = graph.node_by_name(CONVOLVER_NODE_NAME) {
            // Primary path: convolver present — mute via gain params.
            WatchdogAction::SetGainMute {
                convolver_node_id: convolver.id,
            }
        } else {
            // Fallback: convolver gone — destroy all links to USBStreamer.
            let usb_matcher = NodeMatch::Prefix(USBSTREAMER_OUT_PREFIX.to_string());
            let link_ids: Vec<u32> = graph
                .links()
                .filter(|link| {
                    if let Some(node) = graph.node(link.input_node) {
                        usb_matcher.matches(&node.name)
                    } else {
                        false
                    }
                })
                .map(|link| link.id)
                .collect();

            log::error!(
                "WATCHDOG: Convolver gone — fallback: destroying {} USBStreamer links",
                link_ids.len(),
            );
            WatchdogAction::DestroyUsbLinks { link_ids }
        }
    }

    /// Store pre-mute gain values (called by the mute executor before zeroing).
    pub fn store_pre_mute_gains(&mut self, gains: Vec<(String, f64)>) {
        self.pre_mute_gains = gains;
    }

    /// Unlatch the safety mute, returning the pre-mute gains for restoration.
    ///
    /// Returns `None` if not latched. Returns `Some(gains)` with the stored
    /// pre-mute values if latched. The caller is responsible for restoring
    /// the Mult values via PW API calls.
    pub fn unlatch(&mut self) -> Option<Vec<(String, f64)>> {
        if !self.latched {
            return None;
        }

        self.latched = false;
        let gains = std::mem::take(&mut self.pre_mute_gains);
        self.missing_at_latch.clear();

        log::warn!("WATCHDOG: Safety mute UNLATCHED — restoring {} gain values", gains.len());
        Some(gains)
    }

    /// Get the current watchdog status for RPC responses.
    pub fn status(&self) -> WatchdogStatus {
        WatchdogStatus {
            armed: self.armed,
            latched: self.latched,
            missing_nodes: self.missing_at_latch.clone(),
            pre_mute_gains: self.pre_mute_gains.clone(),
        }
    }
}

/// Serializable watchdog status for RPC responses.
#[derive(Debug, Clone, serde::Serialize)]
pub struct WatchdogStatus {
    pub armed: bool,
    pub latched: bool,
    pub missing_nodes: Vec<String>,
    pub pre_mute_gains: Vec<(String, f64)>,
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::{GraphState, TrackedNode};
    use std::collections::HashMap;

    fn make_node(id: u32, name: &str, class: &str) -> TrackedNode {
        TrackedNode {
            id,
            name: name.to_string(),
            media_class: class.to_string(),
            properties: HashMap::new(),
        }
    }

    /// Create a watchdog that has been armed (both monitored nodes seen).
    fn armed_watchdog() -> Watchdog {
        let mut wd = Watchdog::new();
        let g = graph_all_present();
        assert_eq!(wd.check(&g), WatchdogAction::AllPresent);
        assert!(wd.is_armed());
        wd
    }

    /// Build a graph with both monitored nodes present (convolver + convolver-out).
    fn graph_all_present() -> GraphState {
        let mut g = GraphState::new();
        g.add_node(make_node(100, "pi4audio-convolver", "Audio/Sink"));
        g.add_node(make_node(200, "pi4audio-convolver-out", "Stream/Output/Audio"));
        g
    }

    /// Build a graph with USBStreamer and links to it.
    fn graph_with_usb_links() -> GraphState {
        use crate::graph::{TrackedLink, TrackedPort};

        let mut g = graph_all_present();

        g.add_node(make_node(
            400,
            "alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0",
            "Audio/Sink",
        ));
        for ch in 0..4u32 {
            g.add_port(TrackedPort {
                id: 40000 + ch,
                node_id: 400,
                name: format!("playback_AUX{}", ch),
                direction: "in".to_string(),
                properties: HashMap::new(),
            });
        }
        for ch in 0..4u32 {
            g.add_port(TrackedPort {
                id: 20000 + ch,
                node_id: 200,
                name: format!("output_AUX{}", ch),
                direction: "out".to_string(),
                properties: HashMap::new(),
            });
        }
        for ch in 0..4u32 {
            g.add_link(TrackedLink {
                id: 1000 + ch,
                output_node: 200,
                output_port: 20000 + ch,
                input_node: 400,
                input_port: 40000 + ch,
            });
        }

        g
    }

    // -----------------------------------------------------------------------
    // Basic state
    // -----------------------------------------------------------------------

    #[test]
    fn new_watchdog_is_not_latched_and_not_armed() {
        let wd = Watchdog::new();
        assert!(!wd.is_latched());
        assert!(!wd.is_armed());
        assert!(wd.missing_at_latch().is_empty());
    }

    // -----------------------------------------------------------------------
    // All present — no action
    // -----------------------------------------------------------------------

    #[test]
    fn all_nodes_present_returns_all_present_and_arms() {
        let mut wd = Watchdog::new();
        let g = graph_all_present();
        assert_eq!(wd.check(&g), WatchdogAction::AllPresent);
        assert!(!wd.is_latched());
        assert!(wd.is_armed());
    }

    // -----------------------------------------------------------------------
    // Convolver disappears — convolver-out still present → fallback
    // (convolver gone means gain params unreachable → link destruction)
    // -----------------------------------------------------------------------

    #[test]
    fn convolver_disappears_triggers_link_destroy() {
        // Convolver (capture side) is gone — gain params live on this node,
        // so we can't set Mult=0.0 → fallback to link destruction.
        let mut wd = armed_watchdog();
        let mut g = graph_with_usb_links();
        g.remove_node(100); // Remove pi4audio-convolver

        let action = wd.check(&g);
        assert!(wd.is_latched());

        match action {
            WatchdogAction::DestroyUsbLinks { link_ids } => {
                assert_eq!(link_ids.len(), 4);
            }
            other => panic!("expected DestroyUsbLinks, got {:?}", other),
        }
    }

    #[test]
    fn convolver_out_disappears_triggers_gain_mute() {
        // Convolver-out is gone but convolver (capture side with gain params)
        // is still present → primary mute path via convolver node.
        let mut wd = armed_watchdog();
        let mut g = graph_all_present();
        g.remove_node(200); // Remove pi4audio-convolver-out

        let action = wd.check(&g);
        assert!(wd.is_latched());
        assert!(wd.missing_at_latch().contains(&"pi4audio-convolver-out".to_string()));

        match action {
            WatchdogAction::SetGainMute { convolver_node_id } => {
                assert_eq!(convolver_node_id, 100);
            }
            other => panic!("expected SetGainMute, got {:?}", other),
        }
    }

    // -----------------------------------------------------------------------
    // Both nodes disappear — fallback to link destruction
    // -----------------------------------------------------------------------

    #[test]
    fn both_nodes_gone_triggers_usb_link_destroy() {
        let mut wd = armed_watchdog();
        let mut g = graph_with_usb_links();

        g.remove_node(100); // convolver
        g.remove_node(200); // convolver-out

        let action = wd.check(&g);
        assert!(wd.is_latched());

        match action {
            WatchdogAction::DestroyUsbLinks { link_ids } => {
                assert_eq!(link_ids.len(), 4);
                for id in &link_ids {
                    assert!(*id >= 1000 && *id <= 1003);
                }
            }
            other => panic!("expected DestroyUsbLinks, got {:?}", other),
        }
    }

    #[test]
    fn fallback_with_no_usb_links_returns_empty() {
        let mut wd = armed_watchdog();
        let g = GraphState::new();

        let action = wd.check(&g);
        assert!(wd.is_latched());

        match action {
            WatchdogAction::DestroyUsbLinks { link_ids } => {
                assert!(link_ids.is_empty());
            }
            other => panic!("expected DestroyUsbLinks, got {:?}", other),
        }
    }

    // -----------------------------------------------------------------------
    // Latch behavior
    // -----------------------------------------------------------------------

    #[test]
    fn latched_watchdog_returns_already_latched() {
        let mut wd = armed_watchdog();
        let mut g = graph_all_present();
        g.remove_node(200); // Trigger latch (convolver-out gone).

        let _ = wd.check(&g);
        assert!(wd.is_latched());

        assert_eq!(wd.check(&g), WatchdogAction::AlreadyLatched);

        let g2 = graph_all_present();
        assert_eq!(wd.check(&g2), WatchdogAction::AlreadyLatched);
    }

    #[test]
    fn latch_persists_after_nodes_return() {
        let mut wd = armed_watchdog();
        let mut g = graph_all_present();
        g.remove_node(200);
        let _ = wd.check(&g);
        assert!(wd.is_latched());

        let g2 = graph_all_present();
        assert_eq!(wd.check(&g2), WatchdogAction::AlreadyLatched);
        assert!(wd.is_latched());
    }

    // -----------------------------------------------------------------------
    // Unlatch
    // -----------------------------------------------------------------------

    #[test]
    fn unlatch_clears_latch_and_returns_gains() {
        let mut wd = armed_watchdog();
        let mut g = graph_all_present();
        g.remove_node(200);
        let _ = wd.check(&g);

        wd.store_pre_mute_gains(vec![
            ("gain_left_hp".to_string(), 0.001),
            ("gain_right_hp".to_string(), 0.001),
            ("gain_sub1_lp".to_string(), 0.000631),
            ("gain_sub2_lp".to_string(), 0.000631),
        ]);

        let gains = wd.unlatch();
        assert!(!wd.is_latched());
        assert!(gains.is_some());
        let gains = gains.unwrap();
        assert_eq!(gains.len(), 4);
        assert_eq!(gains[0], ("gain_left_hp".to_string(), 0.001));
    }

    #[test]
    fn unlatch_when_not_latched_returns_none() {
        let mut wd = Watchdog::new();
        assert!(wd.unlatch().is_none());
    }

    #[test]
    fn after_unlatch_watchdog_can_trigger_again() {
        let mut wd = armed_watchdog();
        let mut g = graph_all_present();

        g.remove_node(200);
        let _ = wd.check(&g);
        assert!(wd.is_latched());

        wd.unlatch();
        assert!(!wd.is_latched());

        let action = wd.check(&g);
        assert!(wd.is_latched());
        assert!(matches!(action, WatchdogAction::SetGainMute { .. }));
    }

    // -----------------------------------------------------------------------
    // Status
    // -----------------------------------------------------------------------

    #[test]
    fn status_reflects_state() {
        let mut wd = armed_watchdog();
        let status = wd.status();
        assert!(!status.latched);
        assert!(status.armed);
        assert!(status.missing_nodes.is_empty());

        let mut g = graph_all_present();
        g.remove_node(100);
        let _ = wd.check(&g);

        let status = wd.status();
        assert!(status.latched);
        assert!(status.missing_nodes.contains(&"pi4audio-convolver".to_string()));
    }

    #[test]
    fn status_serializable() {
        let wd = Watchdog::new();
        let status = wd.status();
        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("\"latched\":false"));
        assert!(json.contains("\"armed\":false"));
    }

    // -----------------------------------------------------------------------
    // Missing node tracking
    // -----------------------------------------------------------------------

    #[test]
    fn missing_at_latch_tracks_all_missing_nodes() {
        let mut wd = armed_watchdog();
        let mut g = graph_all_present();
        g.remove_node(100);
        g.remove_node(200);

        let _ = wd.check(&g);
        let missing = wd.missing_at_latch();
        assert!(missing.contains(&"pi4audio-convolver".to_string()));
        assert!(missing.contains(&"pi4audio-convolver-out".to_string()));
        assert_eq!(missing.len(), 2);
    }

    // -----------------------------------------------------------------------
    // Pre-mute gain storage
    // -----------------------------------------------------------------------

    #[test]
    fn pre_mute_gains_stored_and_cleared_on_unlatch() {
        let mut wd = armed_watchdog();
        let mut g = graph_all_present();
        g.remove_node(200);
        let _ = wd.check(&g);

        wd.store_pre_mute_gains(vec![
            ("gain_left_hp".to_string(), 0.001),
        ]);
        assert_eq!(wd.pre_mute_gains().len(), 1);

        wd.unlatch();
        assert!(wd.pre_mute_gains().is_empty());
    }

    // -----------------------------------------------------------------------
    // Startup grace period (arming)
    // -----------------------------------------------------------------------

    #[test]
    fn unarmed_watchdog_does_not_latch_on_missing_nodes() {
        let mut wd = Watchdog::new();
        assert!(!wd.is_armed());

        let mut g = GraphState::new();
        g.add_node(make_node(100, "pi4audio-convolver", "Audio/Sink"));
        // Only 1 of 2 monitored nodes present.

        assert_eq!(wd.check(&g), WatchdogAction::AllPresent);
        assert!(!wd.is_latched());
        assert!(!wd.is_armed());
    }

    #[test]
    fn watchdog_arms_when_both_nodes_first_seen() {
        let mut wd = Watchdog::new();
        assert!(!wd.is_armed());

        // Only one node — not armed.
        let mut g = GraphState::new();
        g.add_node(make_node(100, "pi4audio-convolver", "Audio/Sink"));
        assert_eq!(wd.check(&g), WatchdogAction::AllPresent);
        assert!(!wd.is_armed());

        // Both nodes present — arms.
        let g2 = graph_all_present();
        assert_eq!(wd.check(&g2), WatchdogAction::AllPresent);
        assert!(wd.is_armed());
    }

    #[test]
    fn armed_watchdog_latches_immediately_on_node_loss() {
        let mut wd = Watchdog::new();
        let g = graph_all_present();
        assert_eq!(wd.check(&g), WatchdogAction::AllPresent);
        assert!(wd.is_armed());

        let mut g2 = graph_all_present();
        g2.remove_node(200);
        let action = wd.check(&g2);
        assert!(wd.is_latched());
        assert!(matches!(action, WatchdogAction::SetGainMute { .. }));
    }

    #[test]
    fn empty_graph_does_not_latch_when_unarmed() {
        let mut wd = Watchdog::new();
        let g = GraphState::new();
        assert_eq!(wd.check(&g), WatchdogAction::AllPresent);
        assert!(!wd.is_latched());
        assert!(!wd.is_armed());
    }
}
