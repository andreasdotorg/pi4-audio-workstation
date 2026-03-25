//! File playback generator — decodes audio files to f32 PCM for playback.
//!
//! Files are decoded on the RPC thread (non-RT) into a pre-decoded buffer.
//! The RT process callback reads from this buffer via `FilePlaybackGenerator`.
//!
//! Supported formats (via symphonia): MP3, WAV, FLAC, OGG/Vorbis, AAC/M4A.
//! All audio is decoded to mono f32 at 48kHz (simple nearest-sample rate
//! conversion for non-48kHz sources). Playback loops continuously until
//! stopped.

use std::fs;
use std::path::Path;
use std::sync::Arc;

use log::{error, info, warn};
use symphonia::core::audio::SampleBuffer;
use symphonia::core::codecs::DecoderOptions;
use symphonia::core::formats::FormatOptions;
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::probe::Hint;

use crate::generator::SignalGenerator;

/// Maximum file size to decode (50 MB). Prevents OOM from huge files.
const MAX_FILE_SIZE: u64 = 50 * 1024 * 1024;

/// Maximum decoded duration in samples (10 minutes at 48kHz).
const MAX_DECODED_SAMPLES: usize = 48000 * 60 * 10;

/// Shared decoded audio buffer accessible from both RPC and RT threads.
///
/// The RPC thread calls `load_file()` to decode a new file, which atomically
/// swaps the buffer. The RT thread reads samples via `FilePlaybackGenerator`.
pub struct FileBuffer {
    /// The decoded mono f32 samples at 48kHz.
    samples: Arc<Vec<f32>>,
    /// Sample rate of the decoded audio (always 48000 after conversion).
    sample_rate: u32,
}

impl FileBuffer {
    pub fn new() -> Self {
        Self {
            samples: Arc::new(Vec::new()),
            sample_rate: 48000,
        }
    }

    /// Get a clone of the current samples Arc (cheap reference count bump).
    pub fn samples(&self) -> Arc<Vec<f32>> {
        Arc::clone(&self.samples)
    }

    /// Load and decode an audio file. Returns Ok(duration_secs) on success.
    ///
    /// This is called from the RPC thread (non-RT). The decoded samples
    /// are stored and can be retrieved via `samples()`.
    pub fn load_file(&mut self, path: &str, target_rate: u32) -> Result<f32, String> {
        let file_path = Path::new(path);

        // Validate file exists and size.
        let metadata = fs::metadata(file_path)
            .map_err(|e| format!("cannot read file: {}", e))?;
        if metadata.len() > MAX_FILE_SIZE {
            return Err(format!(
                "file too large: {} bytes (max {} MB)",
                metadata.len(),
                MAX_FILE_SIZE / (1024 * 1024)
            ));
        }

        let file = fs::File::open(file_path)
            .map_err(|e| format!("cannot open file: {}", e))?;

        let mss = MediaSourceStream::new(Box::new(file), Default::default());

        // Probe the format.
        let mut hint = Hint::new();
        if let Some(ext) = file_path.extension().and_then(|e| e.to_str()) {
            hint.with_extension(ext);
        }

        let probed = symphonia::default::get_probe()
            .format(&hint, mss, &FormatOptions::default(), &MetadataOptions::default())
            .map_err(|e| format!("unsupported format: {}", e))?;

        let mut format = probed.format;

        // Find the first audio track.
        let track = format
            .tracks()
            .iter()
            .find(|t| {
                t.codec_params.codec != symphonia::core::codecs::CODEC_TYPE_NULL
            })
            .ok_or_else(|| "no audio track found".to_string())?;

        let track_id = track.id;
        let source_rate = track
            .codec_params
            .sample_rate
            .unwrap_or(target_rate) as f64;
        let source_channels = track
            .codec_params
            .channels
            .map(|c| c.count())
            .unwrap_or(1);

        let dec_opts = DecoderOptions::default();
        let mut decoder = symphonia::default::get_codecs()
            .make(&track.codec_params, &dec_opts)
            .map_err(|e| format!("unsupported codec: {}", e))?;

        let mut decoded_samples: Vec<f32> = Vec::new();
        let rate_ratio = target_rate as f64 / source_rate;

        loop {
            let packet = match format.next_packet() {
                Ok(p) => p,
                Err(symphonia::core::errors::Error::IoError(ref e))
                    if e.kind() == std::io::ErrorKind::UnexpectedEof =>
                {
                    break;
                }
                Err(e) => {
                    warn!("decode packet error: {}", e);
                    break;
                }
            };

            if packet.track_id() != track_id {
                continue;
            }

            let decoded = match decoder.decode(&packet) {
                Ok(d) => d,
                Err(e) => {
                    warn!("decode error: {}", e);
                    continue;
                }
            };

            let spec = *decoded.spec();
            let n_frames = decoded.frames();
            let n_channels = spec.channels.count().max(1);

            let mut sample_buf = SampleBuffer::<f32>::new(n_frames as u64, spec);
            sample_buf.copy_interleaved_ref(decoded);
            let samples = sample_buf.samples();

            // Convert to mono and resample (simple nearest-sample).
            for frame_idx in 0..n_frames {
                // Mix to mono by averaging channels.
                let mut mono = 0.0f32;
                for ch in 0..n_channels {
                    mono += samples[frame_idx * n_channels + ch];
                }
                mono /= n_channels as f32;

                decoded_samples.push(mono);
            }

            if decoded_samples.len() > MAX_DECODED_SAMPLES * 2 {
                return Err("file too long (max 10 minutes)".to_string());
            }
        }

        if decoded_samples.is_empty() {
            return Err("no audio samples decoded".to_string());
        }

        // Resample to target rate if needed (simple linear interpolation).
        let final_samples = if (source_rate - target_rate as f64).abs() > 1.0 {
            let out_len = (decoded_samples.len() as f64 * rate_ratio) as usize;
            let out_len = out_len.min(MAX_DECODED_SAMPLES);
            let mut resampled = Vec::with_capacity(out_len);
            for i in 0..out_len {
                let src_pos = i as f64 / rate_ratio;
                let idx = src_pos as usize;
                let frac = src_pos - idx as f64;
                let s0 = decoded_samples[idx.min(decoded_samples.len() - 1)];
                let s1 = decoded_samples[(idx + 1).min(decoded_samples.len() - 1)];
                resampled.push(s0 + (s1 - s0) * frac as f32);
            }
            resampled
        } else {
            if decoded_samples.len() > MAX_DECODED_SAMPLES {
                decoded_samples.truncate(MAX_DECODED_SAMPLES);
            }
            decoded_samples
        };

        let duration_secs = final_samples.len() as f32 / target_rate as f32;
        info!(
            "Decoded {}: {} samples ({:.1}s) at {}Hz, {} source channels",
            path,
            final_samples.len(),
            duration_secs,
            target_rate,
            source_channels,
        );

        self.samples = Arc::new(final_samples);
        self.sample_rate = target_rate;

        Ok(duration_secs)
    }
}

/// RT-safe file playback generator.
///
/// Reads from a pre-decoded `Arc<Vec<f32>>` buffer. Loops continuously.
/// No allocation, no syscalls, no blocking in `generate()`.
pub struct FilePlaybackGenerator {
    samples: Arc<Vec<f32>>,
    position: usize,
}

impl FilePlaybackGenerator {
    /// Create a new file playback generator from pre-decoded samples.
    pub fn new(samples: Arc<Vec<f32>>) -> Self {
        Self {
            samples,
            position: 0,
        }
    }
}

impl SignalGenerator for FilePlaybackGenerator {
    fn generate(
        &mut self,
        buffer: &mut [f32],
        n_frames: usize,
        channels: usize,
        active_channels: u8,
        level_linear: f32,
    ) {
        let src = &*self.samples;
        if src.is_empty() {
            buffer[..n_frames * channels].fill(0.0);
            return;
        }

        for frame in 0..n_frames {
            // Read mono sample from decoded buffer, looping.
            let sample = src[self.position % src.len()] * level_linear;
            self.position += 1;
            if self.position >= src.len() {
                self.position = 0; // Loop back to start.
            }

            let base = frame * channels;
            for ch in 0..channels {
                buffer[base + ch] = if active_channels & (1 << ch) != 0 {
                    sample
                } else {
                    0.0
                };
            }
        }
    }

    fn name(&self) -> &'static str {
        "file"
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn file_playback_generator_loops() {
        let samples = Arc::new(vec![0.1, 0.2, 0.3, 0.4]);
        let mut gen = FilePlaybackGenerator::new(samples);
        let mut buf = vec![0.0f32; 8]; // 8 frames, 1 channel
        gen.generate(&mut buf, 8, 1, 0x01, 1.0);

        // Should loop: 0.1, 0.2, 0.3, 0.4, 0.1, 0.2, 0.3, 0.4
        assert!((buf[0] - 0.1).abs() < 1e-6);
        assert!((buf[1] - 0.2).abs() < 1e-6);
        assert!((buf[4] - 0.1).abs() < 1e-6);
        assert!((buf[7] - 0.4).abs() < 1e-6);
    }

    #[test]
    fn file_playback_generator_empty_produces_silence() {
        let samples = Arc::new(vec![]);
        let mut gen = FilePlaybackGenerator::new(samples);
        let mut buf = vec![1.0f32; 4];
        gen.generate(&mut buf, 4, 1, 0x01, 1.0);
        assert!(buf.iter().all(|&s| s == 0.0));
    }

    #[test]
    fn file_playback_generator_respects_channels() {
        let samples = Arc::new(vec![0.5; 10]);
        let mut gen = FilePlaybackGenerator::new(samples);
        let mut buf = vec![0.0f32; 8]; // 4 frames, 2 channels
        gen.generate(&mut buf, 4, 2, 0b01, 1.0); // only channel 0

        for frame in 0..4 {
            assert!((buf[frame * 2] - 0.5).abs() < 1e-6, "ch0 should have signal");
            assert_eq!(buf[frame * 2 + 1], 0.0, "ch1 should be silent");
        }
    }

    #[test]
    fn file_playback_generator_applies_level() {
        let samples = Arc::new(vec![1.0; 4]);
        let mut gen = FilePlaybackGenerator::new(samples);
        let mut buf = vec![0.0f32; 4];
        gen.generate(&mut buf, 4, 1, 0x01, 0.5);
        for &s in &buf {
            assert!((s - 0.5).abs() < 1e-6);
        }
    }

    #[test]
    fn file_playback_name() {
        let gen = FilePlaybackGenerator::new(Arc::new(vec![]));
        assert_eq!(gen.name(), "file");
    }

    #[test]
    fn file_buffer_new_is_empty() {
        let fb = FileBuffer::new();
        assert!(fb.samples().is_empty());
    }

    #[test]
    fn file_buffer_nonexistent_path_errors() {
        let mut fb = FileBuffer::new();
        let result = fb.load_file("/nonexistent/file.mp3", 48000);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("cannot read file"));
    }

    /// Integration test: decode a real MP3 file with spaces in the path.
    /// Skipped if the test file is not present (CI environments).
    #[test]
    fn file_buffer_decode_real_mp3() {
        let path = "/home/ela/Claudia singt Cole Porter - I love Paris.mp3";
        if !std::path::Path::new(path).exists() {
            eprintln!("Skipping file_buffer_decode_real_mp3: test file not found");
            return;
        }
        let mut fb = FileBuffer::new();
        let duration = fb.load_file(path, 48000).expect("should decode MP3");
        let samples = fb.samples();

        // Sanity checks: file is ~7MB MP3, expect several seconds of audio.
        assert!(duration > 1.0, "expected >1s, got {duration}s");
        assert!(!samples.is_empty(), "decoded samples should not be empty");
        assert!(
            samples.len() > 48000,
            "expected >1s of samples at 48kHz, got {}",
            samples.len()
        );

        // Check that samples are in valid f32 range (not NaN/Inf garbage).
        let mut max_abs: f32 = 0.0;
        for &s in samples.iter().take(48000) {
            assert!(s.is_finite(), "sample must be finite");
            max_abs = max_abs.max(s.abs());
        }
        assert!(max_abs > 0.001, "expected non-silent audio, peak={max_abs}");
        assert!(max_abs <= 1.0, "samples should be normalized, peak={max_abs}");
    }
}
