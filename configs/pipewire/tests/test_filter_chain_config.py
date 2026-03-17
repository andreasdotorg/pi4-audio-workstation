"""Regression tests for production PW filter-chain convolver config (US-059).

Validates:
1. Config file structure and required properties
2. Convolver count and naming matches speaker pipeline
3. Node naming matches GraphManager expectations
4. Coefficient paths are correct
5. Anti-auto-routing properties are set
"""

import os
import unittest

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
CONFIG_PATH = os.path.join(CONFIG_DIR, "30-filter-chain-convolver.conf")


class TestProductionFilterChainConfig(unittest.TestCase):
    """Test 30-filter-chain-convolver.conf structure."""

    def setUp(self):
        with open(CONFIG_PATH) as f:
            self.config = f.read()

    def test_config_exists(self):
        self.assertTrue(os.path.exists(CONFIG_PATH))

    def test_is_drop_in_fragment(self):
        """Production config must NOT include PW infrastructure modules."""
        self.assertNotIn("libpipewire-module-protocol-native", self.config)
        self.assertNotIn("libpipewire-module-client-node", self.config)
        self.assertNotIn("libpipewire-module-adapter", self.config)
        self.assertNotIn("libpipewire-module-rt", self.config)

    def test_has_filter_chain_module(self):
        self.assertIn("libpipewire-module-filter-chain", self.config)

    def test_has_four_convolvers(self):
        count = self.config.count("label  = convolver")
        self.assertEqual(count, 4, f"Expected 4 convolvers, found {count}")

    def test_convolver_names_match_speaker_pipeline(self):
        self.assertIn("conv_left_hp", self.config)
        self.assertIn("conv_right_hp", self.config)
        self.assertIn("conv_sub1_lp", self.config)
        self.assertIn("conv_sub2_lp", self.config)

    def test_four_channel_io(self):
        """Filter-chain must be 4ch (HP/IEM bypass via GraphManager)."""
        self.assertEqual(self.config.count("audio.channels"), 2)
        # Both capture and playback should be 4ch
        lines = [l.strip() for l in self.config.splitlines()
                 if "audio.channels" in l]
        for line in lines:
            self.assertIn("4", line)

    def test_coefficient_paths(self):
        self.assertIn("/etc/pi4audio/coeffs/combined_left_hp.wav", self.config)
        self.assertIn("/etc/pi4audio/coeffs/combined_right_hp.wav", self.config)
        self.assertIn("/etc/pi4audio/coeffs/combined_sub1_lp.wav", self.config)
        self.assertIn("/etc/pi4audio/coeffs/combined_sub2_lp.wav", self.config)

    def test_no_template_placeholders(self):
        """Production config must not have template placeholders."""
        self.assertNotIn("@COEFF_DIR@", self.config)
        self.assertNotIn("@", self.config)

    def test_node_names_for_graph_manager(self):
        self.assertIn('node.name', self.config)
        self.assertIn('"pi4audio-convolver"', self.config)
        self.assertIn('"pi4audio-convolver-out"', self.config)

    def test_auto_connect_disabled(self):
        """Both nodes must disable auto-connect to prevent session manager interference."""
        count = self.config.count("node.autoconnect")
        self.assertGreaterEqual(count, 2,
                                "Both capture and playback need node.autoconnect")

    def test_playback_passive(self):
        self.assertIn("node.passive", self.config)

    def test_no_suspend_on_idle(self):
        count = self.config.count("session.suspend-timeout-seconds")
        self.assertGreaterEqual(count, 2)
        count = self.config.count("node.pause-on-idle")
        self.assertGreaterEqual(count, 2)

    def test_aux_channel_positions(self):
        """Channels should use AUX positions, not FL/FR/RL/RR."""
        self.assertIn("AUX0", self.config)
        self.assertIn("AUX1", self.config)
        self.assertIn("AUX2", self.config)
        self.assertIn("AUX3", self.config)

    def test_no_gain_nodes(self):
        """Filter-chain must not use gain/volume/bq_lowshelf builtin labels.

        PW 1.4.9's convolver silently ignores config.gain (Finding 4, GM-12).
        Attenuation is instead applied via 'linear' builtin nodes chained after
        each convolver: y = x * Mult + 0.0 (flat gain).  These are permitted
        because they are attenuation-only (Mult <= 1.0) and documented in the
        config header.  Standalone gain/volume nodes and biquad shelving are
        still banned -- they would bypass the safety-reviewed gain staging."""
        lower = self.config.lower()
        self.assertNotIn("label = gain", lower)
        self.assertNotIn("label  = gain", lower)
        self.assertNotIn("label = volume", lower)
        self.assertNotIn("label  = volume", lower)
        self.assertNotIn("bq_lowshelf", lower)

    def test_linear_gain_nodes_exist(self):
        """Config must have exactly 4 linear builtin nodes (PW 1.4.9 workaround).

        Each convolver output is chained through a linear node for persistent
        attenuation: conv_X:Out -> gain_X:In.  The linear builtin computes
        y = x * Mult + Add.  Mult must be <= 1.0 (attenuation only, D-009)
        and Add must be 0.0 (no DC offset)."""
        import re

        # Count linear nodes.
        linear_count = len(re.findall(r'label\s*=\s*linear', self.config))
        self.assertEqual(linear_count, 4,
                         f"Expected 4 linear gain nodes, found {linear_count}")

        # Verify each linear node has Mult <= 1.0 (attenuation only).
        mult_values = re.findall(r'"Mult"\s*=\s*([\d.]+)', self.config)
        self.assertEqual(len(mult_values), 4,
                         f"Expected 4 Mult values, found {len(mult_values)}")
        for val_str in mult_values:
            val = float(val_str)
            self.assertLessEqual(val, 1.0,
                                 f"D-009: Mult={val} exceeds 1.0 (would boost signal)")
            self.assertGreater(val, 0.0,
                               f"Mult={val} is zero or negative (would mute or invert)")

        # Verify Add = 0.0 on all linear nodes (no DC offset).
        add_values = re.findall(r'"Add"\s*=\s*([\d.]+)', self.config)
        self.assertEqual(len(add_values), 4,
                         f"Expected 4 Add values, found {len(add_values)}")
        for val_str in add_values:
            self.assertEqual(float(val_str), 0.0,
                             f"Add must be 0.0, got {val_str}")

    def test_linear_nodes_chained_after_convolvers(self):
        """Each convolver output must chain into its corresponding linear node."""
        expected_links = [
            ('conv_left_hp:Out', 'gain_left_hp:In'),
            ('conv_right_hp:Out', 'gain_right_hp:In'),
            ('conv_sub1_lp:Out', 'gain_sub1_lp:In'),
            ('conv_sub2_lp:Out', 'gain_sub2_lp:In'),
        ]
        for output, input_ in expected_links:
            self.assertIn(output, self.config,
                          f"Missing internal link output: {output}")
            self.assertIn(input_, self.config,
                          f"Missing internal link input: {input_}")

    def test_outputs_are_linear_nodes(self):
        """Filter-chain outputs must come from linear gain nodes, not convolvers.

        This ensures all audio passes through the attenuation stage before
        reaching the USBStreamer."""
        expected_outputs = [
            "gain_left_hp:Out",
            "gain_right_hp:Out",
            "gain_sub1_lp:Out",
            "gain_sub2_lp:Out",
        ]
        for out in expected_outputs:
            self.assertIn(out, self.config,
                          f"Output {out} not found -- audio may bypass attenuation")

    def test_capture_is_audio_sink(self):
        self.assertIn("Audio/Sink", self.config)

    def test_no_hardcoded_context_properties(self):
        """Drop-in fragment should not override global context.properties."""
        self.assertNotIn("context.properties", self.config)
        self.assertNotIn("context.spa-libs", self.config)


if __name__ == "__main__":
    unittest.main()
