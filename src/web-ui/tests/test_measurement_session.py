"""Unit tests for MeasurementSession internals (TK-209, TK-210, US-061).

Tests _check_recording_integrity() -- pure/static methods that don't require
async or audio hardware. TK-209 (CamillaDSP config builder) tests removed
by US-061: _build_measurement_config() deleted in D-040 adaptation.
"""

import os
import sys

# Mock mode must be set before any app imports.
os.environ["PI_AUDIO_MOCK"] = "1"

_RC_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "room-correction"))
if _RC_DIR not in sys.path:
    sys.path.insert(0, _RC_DIR)
_MOCK_DIR = os.path.join(_RC_DIR, "mock")
if _MOCK_DIR not in sys.path:
    sys.path.insert(0, _MOCK_DIR)

import numpy as np
import pytest

from app.measurement.session import (
    ChannelConfig,
    MeasurementSession,
    SessionConfig,
    _MEASUREMENT_ATTENUATION_DB,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(channels=None, **kwargs):
    """Create a MeasurementSession with defaults suitable for unit tests."""
    if channels is None:
        channels = [
            ChannelConfig(index=0, name="Left", mandatory_hpf_hz=80.0),
            ChannelConfig(index=1, name="Right", mandatory_hpf_hz=80.0),
            ChannelConfig(index=2, name="Sub1"),
            ChannelConfig(index=3, name="Sub2"),
        ]
    config = SessionConfig(channels=channels, **kwargs)

    async def _noop_broadcast(msg):
        pass

    return MeasurementSession(config=config, ws_broadcast=_noop_broadcast)


# ===================================================================
# TK-210: Tests for _check_recording_integrity()
# ===================================================================

class TestCheckRecordingIntegrity:
    """Test recording integrity validation with synthetic numpy arrays."""

    @staticmethod
    def _make_recording(peak_dbfs=-20.0, duration_s=1.0, sr=48000,
                        dc_offset=0.0, noise_floor_dbfs=-60.0):
        """Create a synthetic recording with controllable properties.

        The recording is a sine wave at the specified peak level with the
        last 10% replaced by low-level noise (for SNR computation).
        """
        n = int(duration_s * sr)
        peak_linear = 10.0 ** (peak_dbfs / 20.0)
        t = np.linspace(0, duration_s, n, endpoint=False)
        signal = peak_linear * np.sin(2 * np.pi * 1000 * t)

        # Replace last 10% with noise floor
        tail_start = int(n * 0.9)
        noise_linear = 10.0 ** (noise_floor_dbfs / 20.0)
        rng = np.random.RandomState(42)
        signal[tail_start:] = noise_linear * rng.randn(n - tail_start)

        signal += dc_offset
        return signal.astype(np.float64)

    def test_valid_recording_passes(self):
        """A recording with good peak, low DC, and good SNR should pass."""
        recording = self._make_recording(
            peak_dbfs=-20.0, dc_offset=0.0, noise_floor_dbfs=-60.0)
        # Should not raise
        MeasurementSession._check_recording_integrity(recording, "Test Ch")

    def test_silent_recording_fails(self):
        """A recording with peak < -40 dBFS should fail."""
        n = 48000
        # Very quiet signal: -50 dBFS peak
        peak_linear = 10.0 ** (-50.0 / 20.0)
        recording = peak_linear * np.sin(
            2 * np.pi * 1000 * np.linspace(0, 1.0, n, endpoint=False))
        with pytest.raises(RuntimeError, match="Peak too low"):
            MeasurementSession._check_recording_integrity(
                recording, "Silent Ch")

    def test_clipping_recording_fails(self):
        """A recording with peak >= -1 dBFS should fail."""
        recording = self._make_recording(
            peak_dbfs=-0.5, noise_floor_dbfs=-60.0)
        with pytest.raises(RuntimeError, match="Peak too high"):
            MeasurementSession._check_recording_integrity(
                recording, "Clipping Ch")

    def test_high_dc_offset_fails(self):
        """A recording with DC offset > 0.01 should fail."""
        recording = self._make_recording(
            peak_dbfs=-20.0, dc_offset=0.05, noise_floor_dbfs=-60.0)
        with pytest.raises(RuntimeError, match="DC offset"):
            MeasurementSession._check_recording_integrity(
                recording, "DC Offset Ch")

    def test_noisy_recording_fails(self):
        """A recording with SNR < 20 dB should fail."""
        # Signal at -30 dBFS, noise floor at -35 dBFS => ~5 dB SNR
        recording = self._make_recording(
            peak_dbfs=-30.0, noise_floor_dbfs=-35.0)
        with pytest.raises(RuntimeError, match="SNR too low"):
            MeasurementSession._check_recording_integrity(
                recording, "Noisy Ch")
