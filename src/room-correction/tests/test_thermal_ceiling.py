"""Tests for thermal ceiling computation module (D-040: PW filter-chain)."""

import logging
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import thermal_ceiling


# Convenience: Mult for -20 dB attenuation (equivalent to old CamillaDSP tests).
MULT_MINUS_20DB = 10 ** (-20.0 / 20.0)  # 0.1
# Production Mult values from PW config.
MULT_MAINS = 0.001       # -60 dB
MULT_SUBS = 0.000631     # ~-64 dB


class TestMultToDb(unittest.TestCase):
    """Tests for the _mult_to_db helper."""

    def test_unity_gain(self):
        self.assertAlmostEqual(thermal_ceiling._mult_to_db(1.0), 0.0)

    def test_minus_20db(self):
        self.assertAlmostEqual(thermal_ceiling._mult_to_db(0.1), -20.0, places=5)

    def test_minus_60db(self):
        self.assertAlmostEqual(thermal_ceiling._mult_to_db(0.001), -60.0, places=5)

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            thermal_ceiling._mult_to_db(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            thermal_ceiling._mult_to_db(-0.5)


class TestComputeThermalCeilingDbfs(unittest.TestCase):
    """Tests for the core compute_thermal_ceiling_dbfs function (raw, no cap)."""

    def test_chn50p_ceiling_with_pw_mult(self):
        """CHN-50P: 7W, 4 ohm, Mult=0.1 (-20 dB) -> ~-11.88 dBFS.

        Signal chain (D-040):
          v_max = sqrt(7 * 4) = 5.2915 V
          v_at_dac = 5.2915 / 42.4 = 0.1248 V
          dbfs_at_dac = 20*log10(0.1248 / 4.9) = -31.88 dBFS
          pw_gain_db = 20*log10(0.1) = -20.0 dB
          ceiling = -31.88 - (-20.0) = -11.88 dBFS
          sensitivity_offset = 87.5 - 87 = +0.5 dB
          final = -11.88 + 0.5 = -11.38 dBFS
        """
        ceiling = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            pw_gain_mult=MULT_MINUS_20DB,
            sensitivity_db_spl=87.5,
        )
        self.assertAlmostEqual(ceiling, -11.38, places=1)

    def test_chn50p_ceiling_default_sensitivity(self):
        """CHN-50P at default sensitivity (87 dB) for direct comparison."""
        ceiling = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            pw_gain_mult=MULT_MINUS_20DB,
            sensitivity_db_spl=87.0,  # reference = no offset
        )
        # Same as old test: -11.88 dBFS (no sensitivity offset)
        v_max = math.sqrt(7 * 4)
        v_dac = v_max / 42.4
        expected = 20 * math.log10(v_dac / 4.9) - 20 * math.log10(MULT_MINUS_20DB)
        self.assertAlmostEqual(ceiling, expected, places=10)
        self.assertAlmostEqual(ceiling, -11.88, places=1)

    def test_ps28iii_ceiling(self):
        """PS28 III: 62W, 2.33 ohm, Mult=0.1 (-20 dB), sens=85 -> ~-6.75 dBFS."""
        ceiling = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=62,
            impedance_ohm=2.33,
            pw_gain_mult=MULT_MINUS_20DB,
            sensitivity_db_spl=85.0,
        )
        # Base: -4.75, sensitivity offset: 85 - 87 = -2 dB -> -4.75 + (-2) = -6.75
        self.assertAlmostEqual(ceiling, -6.75, places=1)

    def test_returns_none_when_pe_max_is_none(self):
        result = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=None,
            impedance_ohm=4,
            pw_gain_mult=MULT_MINUS_20DB,
        )
        self.assertIsNone(result)

    def test_returns_none_when_pe_max_is_zero(self):
        result = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=0,
            impedance_ohm=4,
            pw_gain_mult=MULT_MINUS_20DB,
        )
        self.assertIsNone(result)

    def test_unity_gain_mult(self):
        """With Mult=1.0 (0 dB), ceiling equals the DAC-level limit."""
        ceiling = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            pw_gain_mult=1.0,
            sensitivity_db_spl=87.0,
        )
        # v_max = sqrt(28) = 5.2915V, v_dac = 0.1248V
        # dbfs = 20*log10(0.1248/4.9) = -31.88 dBFS
        # gain_db = 0, ceiling = -31.88 - 0 = -31.88 dBFS
        self.assertAlmostEqual(ceiling, -31.88, places=1)

    def test_production_mains_mult(self):
        """CHN-50P with production Mult=0.001 (-60 dB) gives high ceiling."""
        ceiling = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            pw_gain_mult=MULT_MAINS,
            sensitivity_db_spl=87.5,
        )
        # -31.88 - (-60) + 0.5 = 28.62 dBFS (well above 0, will be capped)
        self.assertAlmostEqual(ceiling, 28.62, places=1)

    def test_horn_sub_high_sensitivity(self):
        """Horn sub: 600W, 8 ohm, sens=103 dB — sensitivity adds 16 dB."""
        ceiling_horn = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=600,
            impedance_ohm=8,
            pw_gain_mult=MULT_MINUS_20DB,
            sensitivity_db_spl=103.0,
        )
        ceiling_direct = thermal_ceiling.compute_thermal_ceiling_dbfs(
            pe_max_watts=600,
            impedance_ohm=8,
            pw_gain_mult=MULT_MINUS_20DB,
            sensitivity_db_spl=87.0,
        )
        # Horn should be 16 dB higher than direct-radiating
        self.assertAlmostEqual(ceiling_horn - ceiling_direct, 16.0, places=5)

    def test_invalid_impedance_raises(self):
        with self.assertRaises(ValueError):
            thermal_ceiling.compute_thermal_ceiling_dbfs(
                pe_max_watts=7, impedance_ohm=0,
                pw_gain_mult=MULT_MINUS_20DB)

    def test_invalid_gain_raises(self):
        with self.assertRaises(ValueError):
            thermal_ceiling.compute_thermal_ceiling_dbfs(
                pe_max_watts=7, impedance_ohm=4,
                pw_gain_mult=MULT_MINUS_20DB,
                amp_voltage_gain=0)

    def test_invalid_mult_raises(self):
        with self.assertRaises(ValueError):
            thermal_ceiling.compute_thermal_ceiling_dbfs(
                pe_max_watts=7, impedance_ohm=4,
                pw_gain_mult=0.0)


class TestSafeCeilingDbfs(unittest.TestCase):
    """Tests for safe_ceiling_dbfs (with hard cap enforcement)."""

    def test_chn50p_capped(self):
        """CHN-50P raw ceiling exceeds -20 cap -> returns -20."""
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            pw_gain_mult=MULT_MINUS_20DB,
        )
        self.assertEqual(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_ps28iii_capped(self):
        """PS28 III raw ceiling exceeds -20 cap -> returns -20."""
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=62,
            impedance_ohm=2.33,
            pw_gain_mult=MULT_MINUS_20DB,
        )
        self.assertEqual(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_fallback_when_pe_max_is_none(self):
        """When pe_max_watts is None, return the hard cap as fallback."""
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=None,
            impedance_ohm=4,
            pw_gain_mult=MULT_MINUS_20DB,
        )
        self.assertEqual(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_fallback_logs_warning(self):
        """When pe_max_watts is None, a warning should be logged."""
        with self.assertLogs(thermal_ceiling.log, level="WARNING") as cm:
            thermal_ceiling.safe_ceiling_dbfs(
                pe_max_watts=None,
                impedance_ohm=4,
                pw_gain_mult=MULT_MINUS_20DB,
            )
        self.assertTrue(any("pe_max_watts" in msg for msg in cm.output))

    def test_hard_cap_never_exceeded(self):
        """Hard cap must never be exceeded, even with high power ratings."""
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=1000,
            impedance_ohm=8,
            pw_gain_mult=MULT_MINUS_20DB,
        )
        self.assertLessEqual(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_low_ceiling_not_raised(self):
        """When thermal ceiling is below the cap, it should pass through.

        CHN-50P with Mult=1.0 (0 dB) -> -31.88 dBFS (well below -20 cap).
        """
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            pw_gain_mult=1.0,
            sensitivity_db_spl=87.0,
        )
        self.assertAlmostEqual(ceiling, -31.88, places=1)
        self.assertLess(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)

    def test_custom_hard_cap(self):
        """Custom hard cap should be respected."""
        # With cap at -5, PS28 III raw ceiling is capped
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=62,
            impedance_ohm=2.33,
            pw_gain_mult=MULT_MINUS_20DB,
            sensitivity_db_spl=87.0,
            hard_cap_dbfs=-5.0,
        )
        self.assertLessEqual(ceiling, -5.0)

        # With cap at -3, PS28 III raw ceiling (-4.75) passes through
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=62,
            impedance_ohm=2.33,
            pw_gain_mult=MULT_MINUS_20DB,
            sensitivity_db_spl=87.0,
            hard_cap_dbfs=-3.0,
        )
        self.assertAlmostEqual(ceiling, -4.75, places=1)

    def test_production_mult_always_capped(self):
        """Production Mult values give very high raw ceiling -> always capped."""
        ceiling = thermal_ceiling.safe_ceiling_dbfs(
            pe_max_watts=7,
            impedance_ohm=4,
            pw_gain_mult=MULT_MAINS,
        )
        self.assertEqual(ceiling, thermal_ceiling.DEFAULT_HARD_CAP_DBFS)


class TestLoadHardwareConfig(unittest.TestCase):
    """Tests for hardware config loading."""

    def test_load_from_project_root(self):
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        hw = thermal_ceiling.load_hardware_config(project_root)
        self.assertAlmostEqual(hw["amp_voltage_gain"], 42.4)
        self.assertAlmostEqual(hw["ada8200_0dbfs_vrms"], 4.9)

    def test_defaults_when_no_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hw = thermal_ceiling.load_hardware_config(tmpdir)
            self.assertEqual(hw["amp_voltage_gain"],
                             thermal_ceiling.DEFAULT_AMP_VOLTAGE_GAIN)
            self.assertEqual(hw["ada8200_0dbfs_vrms"],
                             thermal_ceiling.DEFAULT_ADA8200_0DBFS_VRMS)


class TestLoadSpeakerIdentity(unittest.TestCase):
    """Tests for speaker identity loading including sensitivity."""

    def test_chn50p_identity(self):
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        identity = thermal_ceiling.load_speaker_identity(
            "markaudio-chn-50p-sealed-1l16", project_root)
        self.assertEqual(identity["pe_max_watts"], 7)
        self.assertEqual(identity["impedance_ohm"], 4)
        self.assertAlmostEqual(identity["sensitivity_db_spl"], 87.5)

    def test_ps28iii_identity(self):
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        identity = thermal_ceiling.load_speaker_identity(
            "bose-ps28-iii-sub", project_root)
        self.assertEqual(identity["pe_max_watts"], 62)
        self.assertAlmostEqual(identity["impedance_ohm"], 2.33)
        self.assertAlmostEqual(identity["sensitivity_db_spl"], 85.0)

    def test_horn_sub_high_sensitivity(self):
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        identity = thermal_ceiling.load_speaker_identity(
            "generic-15-horn-sub", project_root)
        self.assertAlmostEqual(identity["sensitivity_db_spl"], 103.0)

    def test_missing_identity_raises(self):
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        with self.assertRaises(FileNotFoundError):
            thermal_ceiling.load_speaker_identity(
                "nonexistent-driver", project_root)


class TestLoadChannelCeilings(unittest.TestCase):
    """Tests for profile-based channel ceiling loading (D-040 PW Mult)."""

    def test_bose_home_chn50p_with_pw_mults(self):
        """Load ceilings with production Mult values.

        All channels are capped at -20 dBFS because the raw ceilings
        at Mult=0.001/-60 dB are far above 0 dBFS.
        """
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        mults = {
            "sat_left": MULT_MAINS,
            "sat_right": MULT_MAINS,
            "sub1": MULT_SUBS,
            "sub2": MULT_SUBS,
        }
        ceilings = thermal_ceiling.load_channel_ceilings(
            "bose-home-chn50p",
            pw_gain_mults=mults,
            project_root=project_root,
        )

        self.assertEqual(len(ceilings), 4)

        for name, info in ceilings.items():
            self.assertLessEqual(info["ceiling_dbfs"],
                                 thermal_ceiling.DEFAULT_HARD_CAP_DBFS,
                                 f"{name}: ceiling should not exceed hard cap")

        # Verify channel assignments
        self.assertEqual(ceilings["sat_left"]["channel"], 0)
        self.assertEqual(ceilings["sat_right"]["channel"], 1)
        self.assertEqual(ceilings["sub1"]["channel"], 2)
        self.assertEqual(ceilings["sub2"]["channel"], 3)

        # Verify identity names
        self.assertEqual(ceilings["sat_left"]["identity"],
                         "markaudio-chn-50p-sealed-1l16")
        self.assertEqual(ceilings["sub1"]["identity"],
                         "bose-ps28-iii-sub")

        # Verify sensitivity is included
        self.assertAlmostEqual(
            ceilings["sat_left"]["sensitivity_db_spl"], 87.5)
        self.assertAlmostEqual(
            ceilings["sub1"]["sensitivity_db_spl"], 85.0)

        # Verify Mult values are stored
        self.assertEqual(ceilings["sat_left"]["pw_gain_mult"], MULT_MAINS)
        self.assertEqual(ceilings["sub1"]["pw_gain_mult"], MULT_SUBS)

    def test_default_mult_is_unity(self):
        """When no Mult map is provided, default to 1.0 (0 dB, conservative)."""
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        ceilings = thermal_ceiling.load_channel_ceilings(
            "bose-home-chn50p",
            pw_gain_mults=None,
            project_root=project_root,
        )

        # With Mult=1.0 (0 dB), satellites should have low ceiling
        # CHN-50P: -31.88 + 0.5 (sens) = -31.38 dBFS
        self.assertAlmostEqual(
            ceilings["sat_left"]["ceiling_dbfs"], -31.38, places=1)
        self.assertEqual(ceilings["sat_left"]["pw_gain_mult"], 1.0)

    def test_partial_mult_map(self):
        """Missing keys in Mult map default to 1.0."""
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        mults = {"sat_left": MULT_MAINS}  # Only one channel specified
        ceilings = thermal_ceiling.load_channel_ceilings(
            "bose-home-chn50p",
            pw_gain_mults=mults,
            project_root=project_root,
        )

        # sat_left has Mult=0.001, sat_right defaults to 1.0
        self.assertEqual(ceilings["sat_left"]["pw_gain_mult"], MULT_MAINS)
        self.assertEqual(ceilings["sat_right"]["pw_gain_mult"], 1.0)

    def test_missing_profile_raises(self):
        project_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "..")
        with self.assertRaises(FileNotFoundError):
            thermal_ceiling.load_channel_ceilings(
                "nonexistent-profile",
                project_root=project_root,
            )


if __name__ == "__main__":
    unittest.main()
