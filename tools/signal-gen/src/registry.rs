//! PipeWire registry listener for device hot-plug detection.
//!
//! Monitors the PipeWire registry for node add/remove events matching
//! the `--device-watch` pattern (default: "UMIK-1"). When the capture
//! device disappears or reappears, the capture stream is disconnected
//! or reconnected accordingly.
