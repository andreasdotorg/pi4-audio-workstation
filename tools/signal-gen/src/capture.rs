//! Capture ring buffer and recording state machine.
//!
//! The PipeWire capture callback writes UMIK-1 input samples into a
//! lock-free ring buffer. The RPC thread reads recorded data on demand
//! (for `playrec` and `capture_level` commands).
