"""Regression tests for BM-2 benchmark artifacts (US-058).

Validates:
1. Dirac WAV generator produces correct impulse files
2. Filter-chain config template substitutes correctly
3. Config structure has exactly 4 convolvers
"""

import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class TestDiracGenerator(unittest.TestCase):
    """Test gen_dirac_bm2.py produces valid impulse WAVs."""

    def test_generates_16384_tap_dirac(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.check_call(
                [sys.executable, os.path.join(SCRIPT_DIR, "gen_dirac_bm2.py"),
                 tmpdir, "16384"],
            )
            wav_path = os.path.join(tmpdir, "dirac_16384.wav")
            self.assertTrue(os.path.exists(wav_path))

            data, sr = sf.read(wav_path)
            self.assertEqual(sr, 48000)
            self.assertEqual(len(data), 16384)
            self.assertAlmostEqual(data[0], 1.0, places=5)
            self.assertEqual(np.count_nonzero(data), 1)

    def test_generates_custom_tap_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.check_call(
                [sys.executable, os.path.join(SCRIPT_DIR, "gen_dirac_bm2.py"),
                 tmpdir, "8192"],
            )
            wav_path = os.path.join(tmpdir, "dirac_8192.wav")
            self.assertTrue(os.path.exists(wav_path))

            data, sr = sf.read(wav_path)
            self.assertEqual(len(data), 8192)
            self.assertAlmostEqual(data[0], 1.0, places=5)


class TestFilterChainConfig(unittest.TestCase):
    """Test bm2-filter-chain.conf template structure."""

    def setUp(self):
        self.template_path = os.path.join(SCRIPT_DIR, "bm2-filter-chain.conf")
        with open(self.template_path) as f:
            self.template = f.read()

    def test_template_exists(self):
        self.assertTrue(os.path.exists(self.template_path))

    def test_has_placeholder(self):
        self.assertIn("@COEFF_DIR@", self.template)

    def test_has_four_convolvers(self):
        count = self.template.count("label = convolver")
        self.assertEqual(count, 4, f"Expected 4 convolvers, found {count}")

    def test_convolver_names_match_speaker_pipeline(self):
        self.assertIn("conv_left_hp", self.template)
        self.assertIn("conv_right_hp", self.template)
        self.assertIn("conv_sub1_lp", self.template)
        self.assertIn("conv_sub2_lp", self.template)

    def test_four_channel_capture(self):
        self.assertIn("audio.channels = 4", self.template)

    def test_substitution_produces_valid_paths(self):
        config = self.template.replace("@COEFF_DIR@", "/tmp/bm2-coeffs")
        self.assertIn("/tmp/bm2-coeffs/dirac_16384.wav", config)
        self.assertNotIn("@COEFF_DIR@", config)

    def test_node_name_set(self):
        self.assertIn("bm2-fir-benchmark-capture", self.template)
        self.assertIn("bm2-fir-benchmark-playback", self.template)


class TestBenchmarkScript(unittest.TestCase):
    """Test run_bm2.sh structure (syntax check only -- execution requires Pi)."""

    def test_script_exists_and_executable(self):
        script_path = os.path.join(SCRIPT_DIR, "run_bm2.sh")
        self.assertTrue(os.path.exists(script_path))
        self.assertTrue(os.access(script_path, os.X_OK))

    def test_script_has_bash_shebang(self):
        script_path = os.path.join(SCRIPT_DIR, "run_bm2.sh")
        with open(script_path) as f:
            first_line = f.readline()
        self.assertIn("bash", first_line)

    def test_script_references_both_quantums(self):
        script_path = os.path.join(SCRIPT_DIR, "run_bm2.sh")
        with open(script_path) as f:
            content = f.read()
        self.assertIn("1024", content)
        self.assertIn("256", content)

    def test_script_references_pidstat(self):
        script_path = os.path.join(SCRIPT_DIR, "run_bm2.sh")
        with open(script_path) as f:
            content = f.read()
        self.assertIn("pidstat", content)


if __name__ == "__main__":
    unittest.main()
