//! Safety limits and hard clip logic.
//!
//! `SafetyLimits` holds the immutable `--max-level-dbfs` cap and provides
//! the per-sample hard clip applied after every generator `fill()` call.
//! This is the last line of defense before samples reach PipeWire -- no
//! code path can bypass it.
