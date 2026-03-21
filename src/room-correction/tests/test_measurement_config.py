"""Tests for measurement setup functions (D-040: PipeWire filter-chain).

Replaces the old CamillaDSP config generation tests (TK-143) with tests
for the D-040 measurement setup: speaker profile HPF lookup, digital HPF
application, and convolver gain node mapping.
"""

import os
import sys
import unittest

import numpy as np

# Ensure the parent directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from measure_nearfield import (
    CONVOLVER_GAIN_NODES,
    MEASUREMENT_ATTENUATION_DB,
    MEASUREMENT_ATTENUATION_LINEAR,
    MEASUREMENT_MUTE_LINEAR,
    SWEEP_LEVEL_HARD_CAP_DBFS,
    apply_hpf_to_signal,
    get_mandatory_hpf_hz,
)


class TestGetMandatoryHpfHz(unittest.TestCase):
    """Test get_mandatory_hpf_hz() with the real bose-home-chn50p profile."""

    def test_satellite_channel_0(self):
        """Channel 0 (sat_left) should have HPF at 80Hz."""
        hpf = get_mandatory_hpf_hz(0, "bose-home-chn50p")
        self.assertEqual(hpf, 80)

    def test_satellite_channel_1(self):
        """Channel 1 (sat_right) should also have HPF at 80Hz."""
        hpf = get_mandatory_hpf_hz(1, "bose-home-chn50p")
        self.assertEqual(hpf, 80)

    def test_sub_channel_2(self):
        """Channel 2 (sub1) should have HPF at 42Hz."""
        hpf = get_mandatory_hpf_hz(2, "bose-home-chn50p")
        self.assertEqual(hpf, 42)

    def test_sub_channel_3_inverted(self):
        """Channel 3 (sub2, inverted) should have HPF at 42Hz."""
        hpf = get_mandatory_hpf_hz(3, "bose-home-chn50p")
        self.assertEqual(hpf, 42)

    def test_invalid_channel_raises(self):
        """Channel 7 (headphone) is not a speaker -- should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            get_mandatory_hpf_hz(7, "bose-home-chn50p")
        self.assertIn("Channel 7 not found", str(ctx.exception))

    def test_invalid_profile_raises(self):
        """Non-existent profile should raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            get_mandatory_hpf_hz(0, "nonexistent-profile")


class TestApplyHpfToSignal(unittest.TestCase):
    """Test apply_hpf_to_signal() digital HPF for excursion protection."""

    def test_attenuates_below_hpf(self):
        """Signal below HPF frequency should be significantly attenuated."""
        sr = 48000
        duration = 0.5
        t = np.arange(int(sr * duration)) / sr
        # 20 Hz tone (below 80 Hz HPF)
        signal = np.sin(2 * np.pi * 20 * t)
        filtered = apply_hpf_to_signal(signal, hpf_hz=80, sr=sr)

        # RMS of filtered signal should be much less than input
        input_rms = np.sqrt(np.mean(signal ** 2))
        output_rms = np.sqrt(np.mean(filtered ** 2))
        attenuation_db = 20 * np.log10(output_rms / input_rms)
        # 4th-order Butterworth at 80Hz should attenuate 20Hz by >20dB
        self.assertLess(attenuation_db, -20.0)

    def test_passes_above_hpf(self):
        """Signal well above HPF frequency should pass with minimal loss."""
        sr = 48000
        duration = 0.5
        t = np.arange(int(sr * duration)) / sr
        # 1000 Hz tone (well above 80 Hz HPF)
        signal = np.sin(2 * np.pi * 1000 * t)
        filtered = apply_hpf_to_signal(signal, hpf_hz=80, sr=sr)

        # RMS should be nearly identical (within 0.5 dB)
        input_rms = np.sqrt(np.mean(signal ** 2))
        output_rms = np.sqrt(np.mean(filtered ** 2))
        attenuation_db = 20 * np.log10(output_rms / input_rms)
        self.assertGreater(attenuation_db, -0.5)

    def test_output_shape_matches_input(self):
        """Output should have the same shape as input."""
        signal = np.random.randn(48000)
        filtered = apply_hpf_to_signal(signal, hpf_hz=80)
        self.assertEqual(filtered.shape, signal.shape)


class TestConvolverGainNodes(unittest.TestCase):
    """Verify convolver gain node mapping covers all speaker channels."""

    def test_all_speaker_channels_mapped(self):
        """Channels 0-3 (main L, main R, sub1, sub2) must have gain nodes."""
        for ch in range(4):
            self.assertIn(ch, CONVOLVER_GAIN_NODES,
                          f"Channel {ch} missing from CONVOLVER_GAIN_NODES")

    def test_node_names_are_strings(self):
        """All node names should be non-empty strings."""
        for ch, name in CONVOLVER_GAIN_NODES.items():
            self.assertIsInstance(name, str)
            self.assertTrue(len(name) > 0)


class TestMeasurementConstants(unittest.TestCase):
    """Verify safety-critical measurement constants."""

    def test_attenuation_linear_matches_db(self):
        """MEASUREMENT_ATTENUATION_LINEAR should match MEASUREMENT_ATTENUATION_DB."""
        expected = 10.0 ** (MEASUREMENT_ATTENUATION_DB / 20.0)
        self.assertAlmostEqual(MEASUREMENT_ATTENUATION_LINEAR, expected, places=5)

    def test_mute_is_zero(self):
        """Mute linear value should be exactly 0.0."""
        self.assertEqual(MEASUREMENT_MUTE_LINEAR, 0.0)

    def test_sweep_hard_cap(self):
        """Safety hard cap must be -20 dBFS (S-010 incident)."""
        self.assertEqual(SWEEP_LEVEL_HARD_CAP_DBFS, -20.0)
