//! Signal generator trait and waveform implementations.
//!
//! Each generator produces interleaved float32 samples into a provided buffer.
//! The `SignalGenerator` trait is object-safe so generators can be swapped at
//! runtime via RPC commands without restarting the PipeWire stream.

/// Trait for all signal generators.
///
/// Implementations must be RT-safe: no allocation, no syscalls, no blocking.
/// The `fill` method is called from the PipeWire process callback on the
/// SCHED_FIFO data thread.
pub trait SignalGenerator: Send {
    /// Fill `buffer` with interleaved float32 samples for `channels` channels.
    ///
    /// `buffer.len()` is always `n_frames * channels`. The generator writes
    /// raw samples (before safety limiting) -- the caller applies the hard
    /// clip after this returns.
    fn fill(&mut self, buffer: &mut [f32], channels: usize);

    /// Human-readable name for status reporting.
    fn name(&self) -> &'static str;
}

/// Silence generator -- writes zeroes. This is the default at startup.
pub struct SilenceGenerator;

impl SignalGenerator for SilenceGenerator {
    fn fill(&mut self, buffer: &mut [f32], _channels: usize) {
        buffer.fill(0.0);
    }

    fn name(&self) -> &'static str {
        "silence"
    }
}
