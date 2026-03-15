//! Command and StateSnapshot types, lock-free ring buffers.
//!
//! The RPC thread pushes `Command` values into a lock-free SPSC queue.
//! The PipeWire process callback pops commands each quantum and updates
//! the active generator / parameters. State snapshots flow back from
//! the process callback to the RPC thread for client status responses.
