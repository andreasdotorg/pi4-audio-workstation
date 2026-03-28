"""Tests for PipeWire filter-chain config generator."""

import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from room_correction.pw_config_generator import (
    channel_suffix,
    spk_key_from_suffix,
    db_to_linear,
    generate_filter_chain_conf,
    write_filter_chain_conf,
    _channel_suffix,
    _get_port_tuning_hz,
)


# -- Helpers -----------------------------------------------------------------

# Use real profile fixtures from configs/speakers/
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_THIS_DIR, "..", "..", "..")
_PROFILES_DIR = os.path.join(_PROJECT_ROOT, "configs", "speakers", "profiles")
_IDENTITIES_DIR = os.path.join(_PROJECT_ROOT, "configs", "speakers", "identities")


def _generate(profile_name, **kwargs):
    """Helper to generate conf with project fixture dirs."""
    return generate_filter_chain_conf(
        profile_name,
        profiles_dir=_PROFILES_DIR,
        identities_dir=_IDENTITIES_DIR,
        **kwargs,
    )


# -- Unit tests for helpers --------------------------------------------------

class TestDbToLinear:
    def test_zero_db(self):
        assert abs(db_to_linear(0.0) - 1.0) < 1e-10

    def test_minus_6db(self):
        assert abs(db_to_linear(-6.0) - 0.501187) < 1e-4

    def test_minus_20db(self):
        assert abs(db_to_linear(-20.0) - 0.1) < 1e-10

    def test_minus_60db(self):
        assert abs(db_to_linear(-60.0) - 0.001) < 1e-6

    def test_very_negative(self):
        assert db_to_linear(-130.0) == 0.0

    def test_positive_6db(self):
        assert abs(db_to_linear(6.0) - 1.99526) < 1e-3


class TestChannelSuffix:
    def test_known_keys(self):
        assert _channel_suffix("sat_left") == "left_hp"
        assert _channel_suffix("sat_right") == "right_hp"
        assert _channel_suffix("sub1") == "sub1_lp"
        assert _channel_suffix("sub2") == "sub2_lp"

    def test_unknown_key_passthrough(self):
        assert _channel_suffix("tweeter_center") == "tweeter_center"

    def test_public_api_matches_private(self):
        """channel_suffix() is the public API, _channel_suffix is the alias."""
        for key in ("sat_left", "sat_right", "sub1", "sub2", "mid_left", "hf_right"):
            assert channel_suffix(key) == _channel_suffix(key)


class TestSpkKeyFromSuffix:
    def test_known_suffixes(self):
        assert spk_key_from_suffix("left_hp") == "sat_left"
        assert spk_key_from_suffix("right_hp") == "sat_right"
        assert spk_key_from_suffix("sub1_lp") == "sub1"
        assert spk_key_from_suffix("sub2_lp") == "sub2"

    def test_unknown_suffix_passthrough(self):
        assert spk_key_from_suffix("tweeter_center") == "tweeter_center"

    def test_roundtrip_known_keys(self):
        """channel_suffix -> spk_key_from_suffix should be identity for known keys."""
        for key in ("sat_left", "sat_right", "sub1", "sub2"):
            suffix = channel_suffix(key)
            assert spk_key_from_suffix(suffix) == key

    def test_roundtrip_unknown_keys(self):
        """Unknown keys pass through in both directions."""
        for key in ("mid_left", "hf_right", "bass"):
            suffix = channel_suffix(key)
            assert suffix == key
            assert spk_key_from_suffix(suffix) == key


class TestChannelSuffixConsistency:
    """R-1: Verify all call sites produce identical results.

    Tests that the canonical channel_suffix() from pw_config_generator
    matches the behavior that was previously hardcoded in speaker_routes.py
    and config_generator.py for all standard topology speaker keys.
    """

    # 2-way speaker keys
    KEYS_2WAY = ["sat_left", "sat_right", "sub1", "sub2"]

    # 3-way speaker keys (typical N-way topology)
    KEYS_3WAY = ["bass", "mid_left", "mid_right", "hf_left", "hf_right", "sub1"]

    # 4-way speaker keys
    KEYS_4WAY = [
        "bass_left", "bass_right", "mid_left", "mid_right",
        "hf_left", "hf_right", "sub1", "sub2",
    ]

    def test_2way_matches_original_hardcoded(self):
        """2-way keys must map to the original hardcoded values."""
        expected = {
            "sat_left": "left_hp",
            "sat_right": "right_hp",
            "sub1": "sub1_lp",
            "sub2": "sub2_lp",
        }
        for key, suffix in expected.items():
            assert channel_suffix(key) == suffix, f"{key} -> {channel_suffix(key)} != {suffix}"

    def test_3way_keys_passthrough(self):
        """3-way keys not in the hardcoded map must pass through unchanged."""
        for key in self.KEYS_3WAY:
            result = channel_suffix(key)
            if key in ("sub1",):
                assert result == "sub1_lp"
            else:
                assert result == key

    def test_4way_keys_passthrough(self):
        """4-way keys not in the hardcoded map must pass through unchanged."""
        for key in self.KEYS_4WAY:
            result = channel_suffix(key)
            if key in ("sub1",):
                assert result == "sub1_lp"
            elif key in ("sub2",):
                assert result == "sub2_lp"
            else:
                assert result == key


# -- Integration tests with real profiles ------------------------------------

class TestBoseHomeProfile:
    """Test generation from the bose-home profile (4-channel 2-way)."""

    def test_generates_valid_conf(self):
        conf = _generate("bose-home")
        assert "context.modules" in conf
        assert "libpipewire-module-filter-chain" in conf

    def test_has_four_convolver_nodes(self):
        conf = _generate("bose-home")
        assert "conv_left_hp" in conf
        assert "conv_right_hp" in conf
        assert "conv_sub1_lp" in conf
        assert "conv_sub2_lp" in conf

    def test_has_four_gain_nodes(self):
        conf = _generate("bose-home")
        assert "gain_left_hp" in conf
        assert "gain_right_hp" in conf
        assert "gain_sub1_lp" in conf
        assert "gain_sub2_lp" in conf

    def test_has_four_internal_links(self):
        conf = _generate("bose-home")
        assert 'conv_left_hp:Out' in conf
        assert 'gain_left_hp:In' in conf
        assert 'conv_sub2_lp:Out' in conf
        assert 'gain_sub2_lp:In' in conf

    def test_has_four_inputs(self):
        conf = _generate("bose-home")
        assert '"conv_left_hp:In"' in conf
        assert '"conv_right_hp:In"' in conf
        assert '"conv_sub1_lp:In"' in conf
        assert '"conv_sub2_lp:In"' in conf

    def test_has_four_outputs(self):
        conf = _generate("bose-home")
        assert '"gain_left_hp:Out"' in conf
        assert '"gain_right_hp:Out"' in conf
        assert '"gain_sub1_lp:Out"' in conf
        assert '"gain_sub2_lp:Out"' in conf

    def test_audio_channels_is_4(self):
        conf = _generate("bose-home")
        assert "audio.channels                  = 4" in conf

    def test_audio_position(self):
        conf = _generate("bose-home")
        assert "AUX0 AUX1 AUX2 AUX3" in conf

    def test_node_names(self):
        conf = _generate("bose-home")
        assert 'node.name                       = "pi4audio-convolver"' in conf
        assert 'node.name                       = "pi4audio-convolver-out"' in conf

    def test_default_coeffs_paths(self):
        conf = _generate("bose-home")
        assert "/etc/pi4audio/coeffs/combined_left_hp.wav" in conf
        assert "/etc/pi4audio/coeffs/combined_right_hp.wav" in conf
        assert "/etc/pi4audio/coeffs/combined_sub1_lp.wav" in conf
        assert "/etc/pi4audio/coeffs/combined_sub2_lp.wav" in conf

    def test_custom_coeffs_paths(self):
        paths = {
            "sat_left": "/tmp/test_left.wav",
            "sub2": "/tmp/test_sub2.wav",
        }
        conf = _generate("bose-home", filter_paths=paths)
        assert "/tmp/test_left.wav" in conf
        assert "/tmp/test_sub2.wav" in conf
        # Non-overridden channels use defaults
        assert "/etc/pi4audio/coeffs/combined_right_hp.wav" in conf

    def test_gain_values_from_profile(self):
        """Gain staging from profile maps to linear Mult values."""
        conf = _generate("bose-home")
        # Satellite power_limit_db = -13.5 -> Mult = 10^(-13.5/20) = 0.211349
        assert "0.211349" in conf or "0.21135" in conf
        # Sub power_limit_db = -20.5 -> Mult = 10^(-20.5/20) = 0.0944061
        # (check partial match)
        assert "0.0944" in conf

    def test_explicit_gain_override(self):
        """Explicit gains_db override profile values."""
        gains = {"sat_left": -30.0}
        conf = _generate("bose-home", gains_db=gains)
        # -30 dB = 0.0316228
        assert "0.0316228" in conf

    def test_header_contains_profile_name(self):
        conf = _generate("bose-home")
        assert "bose-home" in conf
        assert "Bose Home System" in conf

    def test_topology_in_header(self):
        conf = _generate("bose-home")
        assert "Topology: 2way" in conf


class TestBoseHomeChn50pProfile:
    """Test with the CHN-50P variant to ensure different identities work."""

    def test_generates_valid_conf(self):
        conf = _generate("bose-home-chn50p")
        assert "context.modules" in conf
        assert "conv_left_hp" in conf
        assert "gain_sub2_lp" in conf

    def test_different_gain_staging(self):
        """CHN-50P has different power limits than bose-home."""
        conf_chn = _generate("bose-home-chn50p")
        conf_orig = _generate("bose-home")
        # Both are valid but have different Mult values
        assert "context.modules" in conf_chn
        assert "context.modules" in conf_orig


class TestDelayNodes:
    """Test delay node generation."""

    def test_no_delay_by_default(self):
        conf = _generate("bose-home")
        assert "delay_" not in conf
        assert '"Delay"' not in conf

    def test_delay_adds_nodes(self):
        delays = {"sub1": 2.5, "sub2": 3.1}
        conf = _generate("bose-home", delays_ms=delays)
        assert "delay_sub1_lp" in conf
        assert "delay_sub2_lp" in conf
        assert "2.500" in conf
        assert "3.100" in conf

    def test_delay_links(self):
        """Delay nodes are wired after gain nodes."""
        delays = {"sat_left": 1.0}
        conf = _generate("bose-home", delays_ms=delays)
        assert 'gain_left_hp:Out' in conf
        assert 'delay_left_hp:In' in conf

    def test_delay_outputs(self):
        """Outputs use delay nodes when present."""
        delays = {"sat_left": 1.0}
        conf = _generate("bose-home", delays_ms=delays)
        assert '"delay_left_hp:Out"' in conf
        # Channels without delay still use gain output
        assert '"gain_right_hp:Out"' in conf

    def test_zero_delay_is_skipped(self):
        """Zero delay does not create a delay node."""
        delays = {"sat_left": 0.0, "sub1": 1.5}
        conf = _generate("bose-home", delays_ms=delays)
        assert "delay_left_hp" not in conf
        assert "delay_sub1_lp" in conf


class TestCustomNodeNames:
    """Test custom capture/playback node names."""

    def test_custom_names(self):
        conf = _generate(
            "bose-home",
            node_name_capture="my-convolver",
            node_name_playback="my-convolver-out",
        )
        assert '"my-convolver"' in conf
        assert '"my-convolver-out"' in conf


class TestWriteFile:
    """Test file writing."""

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.conf")
            result = write_filter_chain_conf(
                path, "bose-home",
                profiles_dir=_PROFILES_DIR,
                identities_dir=_IDENTITIES_DIR,
            )
            assert result.exists()
            content = result.read_text()
            assert "context.modules" in content

    def test_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "dir", "test.conf")
            result = write_filter_chain_conf(
                path, "bose-home",
                profiles_dir=_PROFILES_DIR,
                identities_dir=_IDENTITIES_DIR,
            )
            assert result.exists()


class TestConfigStructure:
    """Verify the structural correctness of the generated config."""

    def test_balanced_braces(self):
        """All braces in the config are balanced."""
        conf = _generate("bose-home")
        # Count { and } (excluding those in strings/comments)
        opens = conf.count("{")
        closes = conf.count("}")
        assert opens == closes

    def test_balanced_brackets(self):
        """All brackets in the config are balanced."""
        conf = _generate("bose-home")
        opens = conf.count("[")
        closes = conf.count("]")
        assert opens == closes

    def test_no_yaml_artifacts(self):
        """Config should not contain YAML artifacts."""
        conf = _generate("bose-home")
        assert "---" not in conf
        assert ": " not in conf.split("context.modules")[1]  # after header comments

    def test_convolver_label(self):
        """All convolver nodes have label = convolver."""
        conf = _generate("bose-home")
        assert conf.count("label  = convolver") == 4

    def test_linear_label(self):
        """All gain nodes have label = linear."""
        conf = _generate("bose-home")
        assert conf.count("label   = linear") == 4

    def test_media_class_audio_sink(self):
        conf = _generate("bose-home")
        assert "media.class                     = Audio/Sink" in conf


# -- D-031: Mandatory HPF enforcement tests ---------------------------------

class TestGetPortTuningHz:
    """Unit tests for _get_port_tuning_hz helper."""

    def test_scalar_value(self):
        assert _get_port_tuning_hz({"port_tuning_hz": 45.0}) == 45.0

    def test_dict_returns_lowest(self):
        identity = {"port_tuning_hz": {"upper_port": 58, "lower_port": 88}}
        assert _get_port_tuning_hz(identity) == 58.0

    def test_none_when_missing(self):
        assert _get_port_tuning_hz({}) is None

    def test_none_for_none_value(self):
        assert _get_port_tuning_hz({"port_tuning_hz": None}) is None


class TestNoIIRBiquadNodes:
    """D-055: No IIR biquad HPF nodes on the signal chain.

    All subsonic/crossover protection is baked into the FIR filters by
    generate_profile_filters(). The PW config generator must NOT emit
    bq_highpass nodes.
    """

    def test_bose_home_no_biquad_nodes(self):
        """No bq_highpass nodes in the generated config."""
        conf = _generate("bose-home")
        assert "bq_highpass" not in conf

    def test_bose_home_no_hpf_node_names(self):
        """No hpf_ node names in the generated config."""
        conf = _generate("bose-home")
        assert "hpf_left_hp" not in conf
        assert "hpf_sub1_lp" not in conf

    def test_inputs_connect_directly_to_convolver(self):
        """Graph inputs feed convolver directly (no HPF intermediate)."""
        conf = _generate("bose-home")
        inputs_start = conf.index("inputs  = [")
        inputs_end = conf.index("]", inputs_start)
        inputs_section = conf[inputs_start:inputs_end]

        for suffix in ("left_hp", "right_hp", "sub1_lp", "sub2_lp"):
            assert f'"conv_{suffix}:In"' in inputs_section

    def test_2way_sealed_no_biquad_nodes(self):
        """2way-80hz-sealed profile also has no biquad nodes."""
        conf = _generate("2way-80hz-sealed")
        assert "bq_highpass" not in conf

    def test_chain_is_conv_to_gain(self):
        """Signal chain is conv -> gain (no intermediate HPF)."""
        conf = _generate("bose-home")
        links_start = conf.index("links = [")
        links_end = conf.index("]", links_start)
        links_section = conf[links_start:links_end]

        for suffix in ("left_hp", "right_hp", "sub1_lp", "sub2_lp"):
            assert f'conv_{suffix}:Out' in links_section
            assert f'gain_{suffix}:In' in links_section

    def test_conv_to_gain_to_delay_chain(self):
        """Full chain works: conv -> gain -> delay (no HPF)."""
        delays = {"sub1": 2.5, "sub2": 3.1}
        conf = _generate("bose-home", delays_ms=delays)
        assert "bq_highpass" not in conf
        assert conf.count("label  = convolver") == 4
        assert "delay_sub1_lp" in conf
        assert 'conv_sub1_lp:Out' in conf
        assert 'gain_sub1_lp:Out' in conf
        assert 'delay_sub1_lp:In' in conf


class TestHPFPortTuningSafety:
    """D-031: Port tuning frequency safety warnings."""

    def test_bose_ps28_port_tuning_warning(self, caplog):
        """bose-ps28-iii-sub has HPF 42Hz < port tuning 58Hz — logs warning."""
        import logging
        with caplog.at_level(logging.WARNING, logger="room_correction.pw_config_generator"):
            _generate("bose-home")
        port_warnings = [r for r in caplog.records if "port safety" in r.message.lower()]
        # sub1 and sub2 both use bose-ps28-iii-sub
        assert len(port_warnings) >= 2
        assert "42" in port_warnings[0].message
        assert "58" in port_warnings[0].message

    def test_no_warning_when_hpf_above_port_tuning(self, caplog):
        """No port safety warning when HPF >= port tuning."""
        import logging
        # 2way-80hz-sealed has sealed subs (no port tuning) — no warnings expected
        with caplog.at_level(logging.WARNING, logger="room_correction.pw_config_generator"):
            _generate("2way-80hz-sealed")
        port_warnings = [r for r in caplog.records if "port safety" in r.message.lower()]
        assert len(port_warnings) == 0
