"""Unit tests for the dual-FFT transfer function engine (US-120, T-120-01).

Tests verify:
- Correct transfer function computation for known signals
- Exponential averaging behavior
- Coherence computation (1.0 for deterministic, <1.0 with noise)
- Delay finder accuracy
- Phase computation
- Edge cases (no data, reset, single block)
"""

import numpy as np
import pytest

from app.transfer_function import (
    TransferFunctionConfig,
    TransferFunctionEngine,
    TransferFunctionResult,
    DelayFinder,
    MIN_COHERENCE_BLOCKS,
    PHASE_COHERENCE_GATE,
)


# -- Helpers --

def _generate_sine(freq_hz: float, duration_s: float,
                   sr: int = 48000, amplitude: float = 1.0) -> np.ndarray:
    """Generate a pure sine wave."""
    t = np.arange(int(sr * duration_s)) / sr
    return amplitude * np.sin(2 * np.pi * freq_hz * t)


def _generate_delayed(signal: np.ndarray, delay_samples: int) -> np.ndarray:
    """Delay a signal by prepending zeros and truncating to original length."""
    if delay_samples <= 0:
        return signal.copy()
    padded = np.concatenate([np.zeros(delay_samples), signal])
    return padded[:len(signal)]


# -- TransferFunctionConfig tests --

class TestTransferFunctionConfig:
    def test_defaults(self):
        cfg = TransferFunctionConfig()
        assert cfg.fft_size == 4096
        assert cfg.overlap == 0.5
        assert cfg.alpha == 0.125
        assert cfg.sample_rate == 48000

    def test_hop_size(self):
        cfg = TransferFunctionConfig(fft_size=4096, overlap=0.5)
        assert cfg.hop_size == 2048

    def test_hop_size_75_overlap(self):
        cfg = TransferFunctionConfig(fft_size=4096, overlap=0.75)
        assert cfg.hop_size == 1024

    def test_n_bins(self):
        cfg = TransferFunctionConfig(fft_size=4096)
        assert cfg.n_bins == 2049

    def test_freq_axis_length(self):
        cfg = TransferFunctionConfig(fft_size=4096, sample_rate=48000)
        freqs = cfg.freq_axis()
        assert len(freqs) == 2049
        assert freqs[0] == 0.0
        assert abs(freqs[-1] - 24000.0) < 0.01


# -- TransferFunctionEngine basic tests --

class TestEngineBasic:
    def test_no_data_returns_silence(self):
        engine = TransferFunctionEngine()
        result = engine.compute()
        assert result.blocks_accumulated == 0
        assert np.all(result.magnitude_db == -120.0)
        assert np.all(result.coherence == 0.0)

    def test_reset_clears_state(self):
        engine = TransferFunctionEngine()
        ref = np.random.randn(4096)
        meas = np.random.randn(4096)
        engine.process_block(ref, meas)
        assert engine.blocks_accumulated > 0
        engine.reset()
        assert engine.blocks_accumulated == 0

    def test_single_block_coherence_is_one(self):
        """A single FFT block always gives Cxy = 1.0 (trivially)."""
        engine = TransferFunctionEngine()
        signal = _generate_sine(1000, 0.1)
        engine.process_block(signal, signal)
        result = engine.compute()
        assert result.blocks_accumulated >= 1
        # With a single block and identical signals, coherence should be 1.0.
        assert np.all(result.coherence >= 0.99)

    def test_set_alpha_validates_range(self):
        engine = TransferFunctionEngine()
        with pytest.raises(ValueError):
            engine.set_alpha(0.0)
        with pytest.raises(ValueError):
            engine.set_alpha(-0.1)
        with pytest.raises(ValueError):
            engine.set_alpha(1.5)
        engine.set_alpha(0.5)  # should not raise
        assert engine.config.alpha == 0.5


# -- Identity transfer function tests --

class TestIdentityTransfer:
    """When ref == meas, H(f) should be ~0 dB (unity gain) everywhere."""

    def test_identity_magnitude_near_zero_db(self):
        cfg = TransferFunctionConfig(fft_size=4096, alpha=0.25)
        engine = TransferFunctionEngine(cfg)

        # Feed several blocks of identical pink-ish noise.
        np.random.seed(42)
        for _ in range(16):
            block = np.random.randn(cfg.fft_size)
            engine.process_block(block, block)

        result = engine.compute()
        # Magnitude should be close to 0 dB for all bins (identity).
        # Use a generous tolerance since exponential averaging introduces
        # slight deviations.
        mid_bins = result.magnitude_db[10:-10]  # skip DC and Nyquist edges
        assert np.all(np.abs(mid_bins) < 1.0), (
            f"Expected ~0 dB, got max deviation {np.max(np.abs(mid_bins)):.2f} dB")

    def test_identity_phase_near_zero(self):
        cfg = TransferFunctionConfig(fft_size=4096, alpha=0.25)
        engine = TransferFunctionEngine(cfg)

        np.random.seed(42)
        for _ in range(16):
            block = np.random.randn(cfg.fft_size)
            engine.process_block(block, block)

        result = engine.compute()
        mid_bins = result.phase_deg[10:-10]
        assert np.all(np.abs(mid_bins) < 5.0), (
            f"Expected ~0 deg, got max deviation {np.max(np.abs(mid_bins)):.1f} deg")

    def test_identity_coherence_near_one(self):
        cfg = TransferFunctionConfig(fft_size=4096, alpha=0.25)
        engine = TransferFunctionEngine(cfg)

        np.random.seed(42)
        for _ in range(16):
            block = np.random.randn(cfg.fft_size)
            engine.process_block(block, block)

        result = engine.compute()
        assert np.all(result.coherence > 0.99), (
            f"Expected coherence ~1.0, got min {np.min(result.coherence):.4f}")


# -- Gain transfer function test --

class TestGainTransfer:
    """When meas = gain * ref, magnitude should show the gain."""

    def test_6db_gain(self):
        cfg = TransferFunctionConfig(fft_size=4096, alpha=0.25)
        engine = TransferFunctionEngine(cfg)

        gain_linear = 2.0  # +6 dB
        np.random.seed(42)
        for _ in range(16):
            ref = np.random.randn(cfg.fft_size)
            meas = ref * gain_linear
            engine.process_block(ref, meas)

        result = engine.compute()
        mid_bins = result.magnitude_db[10:-10]
        expected_db = 20.0 * np.log10(gain_linear)  # 6.02 dB
        assert np.all(np.abs(mid_bins - expected_db) < 1.0), (
            f"Expected ~{expected_db:.1f} dB, got mean {np.mean(mid_bins):.2f} dB")


# -- Coherence with noise tests --

class TestCoherenceWithNoise:
    """Coherence should drop when uncorrelated noise is added to measurement."""

    def test_noisy_measurement_lowers_coherence(self):
        cfg = TransferFunctionConfig(fft_size=4096, alpha=0.1)
        engine = TransferFunctionEngine(cfg)

        np.random.seed(42)
        for _ in range(32):
            ref = np.random.randn(cfg.fft_size)
            noise = np.random.randn(cfg.fft_size) * 0.5
            meas = ref + noise  # SNR ~ 6 dB
            engine.process_block(ref, meas)

        result = engine.compute()
        mean_coh = float(np.mean(result.coherence[10:-10]))
        # With equal-power noise (SNR ~6 dB), coherence should be noticeably
        # below 1.0 but well above 0.
        assert 0.3 < mean_coh < 0.95, (
            f"Expected moderate coherence, got {mean_coh:.3f}")

    def test_uncorrelated_signals_low_coherence(self):
        cfg = TransferFunctionConfig(fft_size=4096, alpha=0.1)
        engine = TransferFunctionEngine(cfg)

        np.random.seed(42)
        for _ in range(32):
            ref = np.random.randn(cfg.fft_size)
            meas = np.random.randn(cfg.fft_size)  # completely independent
            engine.process_block(ref, meas)

        result = engine.compute()
        mean_coh = float(np.mean(result.coherence[10:-10]))
        # Uncorrelated signals should give coherence close to 0.
        assert mean_coh < 0.15, (
            f"Expected low coherence for uncorrelated signals, got {mean_coh:.3f}")


# -- Overlap buffering tests --

class TestOverlapBuffering:
    """Verify that feeding data in small chunks produces correct results."""

    def test_small_chunks_match_full_blocks(self):
        cfg = TransferFunctionConfig(fft_size=4096, alpha=1.0)

        # Engine 1: feed full FFT-sized blocks.
        engine1 = TransferFunctionEngine(cfg)
        np.random.seed(42)
        ref_full = np.random.randn(cfg.fft_size * 4)
        meas_full = ref_full * 1.5

        for i in range(0, len(ref_full), cfg.fft_size):
            engine1.process_block(
                ref_full[i:i + cfg.fft_size],
                meas_full[i:i + cfg.fft_size])

        # Engine 2: feed in small chunks (256 samples at a time).
        engine2 = TransferFunctionEngine(cfg)
        chunk = 256
        for i in range(0, len(ref_full), chunk):
            engine2.process_block(
                ref_full[i:i + chunk],
                meas_full[i:i + chunk])

        r1 = engine1.compute()
        r2 = engine2.compute()

        # Both engines should have processed the same number of blocks.
        assert r1.blocks_accumulated == r2.blocks_accumulated
        # Results should be very close.
        np.testing.assert_allclose(
            r1.magnitude_db, r2.magnitude_db, atol=0.01,
            err_msg="Small-chunk feeding should match full-block feeding")


# -- JSON serialization tests --

class TestJsonSerialization:
    def test_to_json_dict_structure(self):
        cfg = TransferFunctionConfig(fft_size=256)
        engine = TransferFunctionEngine(cfg)
        signal = np.random.randn(256 * 4)
        engine.process_block(signal, signal)
        result = engine.compute()

        d = result.to_json_dict(channel=2)
        assert d["channel"] == 2
        assert "magnitude_db" in d
        assert "phase_deg" in d
        assert "coherence" in d
        assert "freq_axis" in d
        assert "blocks_accumulated" in d
        assert "warming_up" in d
        assert isinstance(d["magnitude_db"], list)
        assert len(d["magnitude_db"]) == cfg.n_bins

    def test_phase_gated_by_coherence(self):
        """Phase should be None where coherence < PHASE_COHERENCE_GATE."""
        cfg = TransferFunctionConfig(fft_size=256, alpha=0.1)
        engine = TransferFunctionEngine(cfg)

        np.random.seed(42)
        for _ in range(32):
            ref = np.random.randn(cfg.fft_size)
            meas = np.random.randn(cfg.fft_size)  # uncorrelated
            engine.process_block(ref, meas)

        result = engine.compute()
        d = result.to_json_dict()

        # Most bins should have low coherence for uncorrelated signals.
        # Phase values at those bins should be None.
        null_count = sum(1 for p in d["phase_deg"] if p is None)
        assert null_count > len(d["phase_deg"]) * 0.5, (
            "Expected many null phase values for uncorrelated signals")

    def test_warming_up_flag(self):
        cfg = TransferFunctionConfig(fft_size=256)
        engine = TransferFunctionEngine(cfg)

        # Process fewer blocks than MIN_COHERENCE_BLOCKS.
        for _ in range(2):
            engine.process_block(np.random.randn(256), np.random.randn(256))
        result = engine.compute()
        d = result.to_json_dict()
        assert d["warming_up"] is True

        # Process enough blocks.
        for _ in range(MIN_COHERENCE_BLOCKS + 5):
            engine.process_block(np.random.randn(256), np.random.randn(256))
        result = engine.compute()
        d = result.to_json_dict()
        assert d["warming_up"] is False


# -- DelayFinder tests --

class TestDelayFinder:
    def test_zero_delay(self):
        """Identical signals should give delay = 0."""
        finder = DelayFinder(max_delay_samples=4800, correlation_window=24000)
        signal = np.random.randn(24000)
        finder.accumulate(signal, signal)
        assert finder.has_enough_data()
        delay = finder.compute_delay()
        assert abs(delay) <= 1, f"Expected ~0 delay, got {delay}"

    def test_known_positive_delay(self):
        """Measurement delayed by 480 samples (~10ms at 48kHz)."""
        finder = DelayFinder(max_delay_samples=4800, correlation_window=48000)
        np.random.seed(42)
        ref = np.random.randn(48000)
        expected_delay = 480
        meas = _generate_delayed(ref, expected_delay)

        finder.accumulate(ref, meas)
        delay = finder.compute_delay()
        # Allow +/-2 sample tolerance for cross-correlation peak resolution.
        assert abs(delay - expected_delay) <= 2, (
            f"Expected delay ~{expected_delay}, got {delay}")

    def test_larger_delay(self):
        """Measurement delayed by 4800 samples (~100ms, large room)."""
        finder = DelayFinder(max_delay_samples=9600, correlation_window=48000)
        np.random.seed(42)
        ref = np.random.randn(48000)
        expected_delay = 4800
        meas = _generate_delayed(ref, expected_delay)

        finder.accumulate(ref, meas)
        delay = finder.compute_delay()
        assert abs(delay - expected_delay) <= 2, (
            f"Expected delay ~{expected_delay}, got {delay}")

    def test_insufficient_data(self):
        """Should return 0 (default) when not enough data accumulated."""
        finder = DelayFinder(correlation_window=48000)
        signal = np.random.randn(1000)  # way too short
        finder.accumulate(signal, signal)
        assert not finder.has_enough_data()
        delay = finder.compute_delay()
        assert delay == 0

    def test_confidence_high_for_clean_signal(self):
        finder = DelayFinder(correlation_window=48000)
        np.random.seed(42)
        ref = np.random.randn(48000)
        meas = _generate_delayed(ref, 240)
        finder.accumulate(ref, meas)
        finder.compute_delay()
        assert finder.confidence > 5.0, (
            f"Expected high confidence, got {finder.confidence:.1f}")

    def test_accumulate_trims_to_window(self):
        """Buffer should not grow beyond correlation_window."""
        finder = DelayFinder(correlation_window=10000)
        for _ in range(10):
            finder.accumulate(
                np.random.randn(5000), np.random.randn(5000))
        assert len(finder._ref_buf) == 10000
        assert len(finder._meas_buf) == 10000
