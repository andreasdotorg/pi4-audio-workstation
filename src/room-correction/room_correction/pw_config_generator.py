"""
PipeWire filter-chain configuration generator from speaker profiles.

Post-D-040 replacement for CamillaDSP config generation. Reads a speaker
profile (Layer 2) referencing speaker identities (Layer 1) and emits a
PipeWire filter-chain `.conf` drop-in file with the correct topology:

    [HPF biquad nodes ->] convolver nodes -> linear gain nodes

per output channel, with internal links, inputs, outputs, and capture/playback
props matching the GraphManager's expected node names.

Output format is PipeWire SPA JSON (not YAML), matching the structure of
``configs/pipewire/30-filter-chain-convolver.conf``.

Channel naming convention:
    sat_left  -> left_hp    (highpass + room correction)
    sat_right -> right_hp
    sub1      -> sub1_lp    (lowpass + room correction)
    sub2      -> sub2_lp

Gain staging: The ``gain_staging`` section from the profile provides per-role
attenuation in dB. This is converted to a linear Mult value for the PW
``linear`` builtin node: Mult = 10^(dB/20).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from . import dsp_utils

log = logging.getLogger(__name__)

# Try to import YAML loading from the CamillaDSP config generator (same
# profile/identity loaders). Import at module level so we fail fast.
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config_generator import (
    load_profile_with_identities,
    validate_and_raise,
    _classify_speakers,
    ValidationError,
)


# -- Constants ---------------------------------------------------------------

DEFAULT_COEFFS_DIR = "/etc/pi4audio/coeffs"
DEFAULT_NODE_NAME_CAPTURE = "pi4audio-convolver"
DEFAULT_NODE_NAME_PLAYBACK = "pi4audio-convolver-out"

# Speaker key -> channel suffix for node/file naming
_KEY_TO_SUFFIX = {
    "sat_left": "left_hp",
    "sat_right": "right_hp",
    "sub1": "sub1_lp",
    "sub2": "sub2_lp",
}


# 4th-order Butterworth HPF: two cascaded 2nd-order biquads.
# Q values from Butterworth polynomial factorisation for n=4.
_BUTTERWORTH_4_Q = (0.5412, 1.3066)


def _channel_suffix(spk_key: str) -> str:
    """Map a speaker key to a channel suffix for node naming."""
    return _KEY_TO_SUFFIX.get(spk_key, spk_key)


def _get_port_tuning_hz(identity: dict) -> float | None:
    """Extract a scalar port tuning frequency from an identity.

    The field may be a scalar (``port_tuning_hz: 45``) or a dict with
    per-port values (``port_tuning_hz: {upper_port: 58, lower_port: 88}``).
    For safety checks we return the *lowest* port tuning frequency, since
    unloading below any port is dangerous.
    """
    val = identity.get("port_tuning_hz")
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        nums = [v for v in val.values() if isinstance(v, (int, float))]
        return float(min(nums)) if nums else None
    return None


def db_to_linear(db: float) -> float:
    """Convert dB to linear gain (Mult value for PW linear node)."""
    if db <= -120:
        return 0.0
    return 10.0 ** (db / 20.0)


# -- Config text generation --------------------------------------------------

def _indent(text: str, level: int) -> str:
    """Indent each line of text by level * 4 spaces."""
    prefix = "    " * level
    return "\n".join(prefix + line if line.strip() else "" for line in text.split("\n"))


def generate_filter_chain_conf(
    profile_name: str,
    filter_paths: dict[str, str] | None = None,
    gains_db: dict[str, float] | None = None,
    delays_ms: dict[str, float] | None = None,
    coeffs_dir: str = DEFAULT_COEFFS_DIR,
    node_name_capture: str = DEFAULT_NODE_NAME_CAPTURE,
    node_name_playback: str = DEFAULT_NODE_NAME_PLAYBACK,
    profiles_dir=None,
    identities_dir=None,
    validate: bool = True,
) -> str:
    """Generate a PipeWire filter-chain .conf file from a speaker profile.

    Parameters
    ----------
    profile_name : str
        Name of the speaker profile (without .yml).
    filter_paths : dict, optional
        Mapping of speaker keys to FIR WAV file paths. If not provided,
        uses ``{coeffs_dir}/combined_{suffix}.wav`` for each channel.
    gains_db : dict, optional
        Per-channel gain in dB. Overrides gain_staging from profile.
        Keys are speaker keys (e.g., 'sat_left').
    delays_ms : dict, optional
        Per-channel delay in ms. If provided, delay nodes are added.
    coeffs_dir : str
        Base directory for coefficient WAV files (default: /etc/pi4audio/coeffs).
    node_name_capture : str
        PW node name for the capture (sink) side.
    node_name_playback : str
        PW node name for the playback (source) side.
    profiles_dir : str or Path, optional
        Override profiles directory.
    identities_dir : str or Path, optional
        Override identities directory.
    validate : bool
        If True, validate the profile before generating.

    Returns
    -------
    str
        Complete PipeWire filter-chain .conf file content.
    """
    profile, identities = load_profile_with_identities(
        profile_name,
        profiles_dir=profiles_dir,
        identities_dir=identities_dir,
    )

    if validate:
        validate_and_raise(profile, identities, identities_dir=identities_dir)

    satellites, subwoofers = _classify_speakers(profile)
    all_speakers = satellites + subwoofers

    if filter_paths is None:
        filter_paths = {}
    if gains_db is None:
        gains_db = {}
    if delays_ms is None:
        delays_ms = {}

    # Resolve per-channel values
    gain_staging = profile.get("gain_staging", {})
    channels = []
    for spk_key, spk_cfg in all_speakers:
        suffix = _channel_suffix(spk_key)
        role = spk_cfg.get("role", "satellite")
        role_gs = gain_staging.get(role, {})

        # Gain: explicit override > profile power_limit_db > default -60dB
        if spk_key in gains_db:
            ch_gain_db = gains_db[spk_key]
        else:
            ch_gain_db = role_gs.get("power_limit_db", -60.0)

        ch_gain_linear = db_to_linear(ch_gain_db)

        # FIR path: explicit > default
        fir_path = filter_paths.get(
            spk_key,
            f"{coeffs_dir}/combined_{suffix}.wav",
        )

        # Delay
        delay = delays_ms.get(spk_key, 0.0)

        # D-031: Resolve mandatory HPF from speaker identity
        id_name = spk_cfg.get("identity", "")
        identity = identities.get(id_name, {})
        mandatory_hpf_hz = identity.get("mandatory_hpf_hz")

        # Port-tuning safety check (ported enclosures)
        port_tuning = _get_port_tuning_hz(identity)
        if (port_tuning is not None
                and mandatory_hpf_hz is not None
                and mandatory_hpf_hz < port_tuning):
            log.warning(
                "D-031 port safety: speaker '%s' (%s) has mandatory_hpf_hz=%s "
                "below port_tuning_hz=%s. Unloading a ported enclosure below "
                "port tuning destroys drivers.",
                spk_key, id_name, mandatory_hpf_hz, port_tuning,
            )

        channels.append({
            "key": spk_key,
            "suffix": suffix,
            "channel": spk_cfg["channel"],
            "fir_path": fir_path,
            "gain_db": ch_gain_db,
            "gain_linear": ch_gain_linear,
            "delay_ms": delay,
            "filter_type": spk_cfg.get("filter_type", ""),
            "mandatory_hpf_hz": mandatory_hpf_hz,
        })

    # Sort by channel index for consistent output
    channels.sort(key=lambda c: c["channel"])
    n_channels = len(channels)

    # Build node definitions
    nodes_lines = []

    # D-031: Mandatory HPF nodes (subsonic protection, BEFORE convolver).
    # 4th-order Butterworth = two cascaded 2nd-order bq_highpass stages.
    for ch in channels:
        hpf_hz = ch["mandatory_hpf_hz"]
        if hpf_hz is not None:
            for stage, q_val in enumerate(_BUTTERWORTH_4_Q):
                nodes_lines.append(
                    f'                {{\n'
                    f'                    type    = builtin\n'
                    f'                    name    = hpf_{ch["suffix"]}_s{stage}\n'
                    f'                    label   = bq_highpass\n'
                    f'                    control = {{ "Freq" = {hpf_hz:.1f} "Q" = {q_val:.4f} }}\n'
                    f'                }}'
                )

    # Convolver nodes
    for ch in channels:
        nodes_lines.append(
            f'                {{\n'
            f'                    type   = builtin\n'
            f'                    name   = conv_{ch["suffix"]}\n'
            f'                    label  = convolver\n'
            f'                    config = {{\n'
            f'                        filename = "{ch["fir_path"]}"\n'
            f'                    }}\n'
            f'                }}'
        )

    # Gain nodes
    for ch in channels:
        mult_str = f'{ch["gain_linear"]:.6g}'
        nodes_lines.append(
            f'                {{\n'
            f'                    type    = builtin\n'
            f'                    name    = gain_{ch["suffix"]}\n'
            f'                    label   = linear\n'
            f'                    control = {{ "Mult" = {mult_str} "Add" = 0.0 }}\n'
            f'                }}'
        )

    # Delay nodes (only if any channel has delay > 0)
    has_delays = any(ch["delay_ms"] > 0 for ch in channels)
    if has_delays:
        for ch in channels:
            if ch["delay_ms"] > 0:
                nodes_lines.append(
                    f'                {{\n'
                    f'                    type   = builtin\n'
                    f'                    name   = delay_{ch["suffix"]}\n'
                    f'                    label  = delay\n'
                    f'                    control = {{ "Delay" = {ch["delay_ms"]:.3f} }}\n'
                    f'                }}'
                )

    # Build internal links: [hpf_s0 -> hpf_s1 ->] conv -> gain [-> delay]
    links_lines = []
    for ch in channels:
        hpf_hz = ch["mandatory_hpf_hz"]
        if hpf_hz is not None:
            # HPF stage 0 -> stage 1
            links_lines.append(
                f'                {{ output = "hpf_{ch["suffix"]}_s0:Out"  '
                f'input = "hpf_{ch["suffix"]}_s1:In" }}'
            )
            # HPF stage 1 -> convolver
            links_lines.append(
                f'                {{ output = "hpf_{ch["suffix"]}_s1:Out"  '
                f'input = "conv_{ch["suffix"]}:In" }}'
            )
        # conv -> gain
        links_lines.append(
            f'                {{ output = "conv_{ch["suffix"]}:Out"  '
            f'input = "gain_{ch["suffix"]}:In" }}'
        )
        if has_delays and ch["delay_ms"] > 0:
            links_lines.append(
                f'                {{ output = "gain_{ch["suffix"]}:Out"  '
                f'input = "delay_{ch["suffix"]}:In" }}'
            )

    # Build inputs (first node in chain: HPF stage 0 if present, else convolver)
    inputs_lines = []
    for ch in channels:
        if ch["mandatory_hpf_hz"] is not None:
            inputs_lines.append(f'                "hpf_{ch["suffix"]}_s0:In"')
        else:
            inputs_lines.append(f'                "conv_{ch["suffix"]}:In"')

    # Build outputs (last node in chain: delay if present, else gain)
    outputs_lines = []
    for ch in channels:
        if has_delays and ch["delay_ms"] > 0:
            outputs_lines.append(f'                "delay_{ch["suffix"]}:Out"')
        else:
            outputs_lines.append(f'                "gain_{ch["suffix"]}:Out"')

    # Build audio.position array
    positions = " ".join(f"AUX{ch['channel']}" for ch in channels)

    # Assemble the complete conf
    header = (
        f'# PipeWire filter-chain drop-in: {n_channels}-channel FIR convolver.\n'
        f'#\n'
        f'# Auto-generated from speaker profile: {profile_name}\n'
        f'# Profile: {profile.get("name", profile_name)}\n'
        f'# Topology: {profile.get("topology", "unknown")}\n'
        f'#\n'
        f'# Channel assignment:\n'
    )
    for ch in channels:
        header += f'#   AUX{ch["channel"]} = {ch["suffix"]} ({ch["filter_type"]})\n'
    header += (
        f'#\n'
        f'# Deploy to: ~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf\n'
    )

    nodes_str = "\n".join(nodes_lines)
    links_str = "\n".join(links_lines)
    inputs_str = "\n".join(inputs_lines)
    outputs_str = "\n".join(outputs_lines)

    conf = f"""{header}
context.modules = [
{{
    name = libpipewire-module-filter-chain
    args = {{
        node.description = "FIR Convolver ({n_channels}ch x 16k taps)"
        media.name       = "pi4audio FIR Convolver"

        filter.graph = {{
            nodes = [
{nodes_str}
            ]

            links = [
{links_str}
            ]

            inputs  = [
{inputs_str}
            ]
            outputs = [
{outputs_str}
            ]
        }}

        capture.props = {{
            node.name                       = "{node_name_capture}"
            node.description                = "FIR Convolver ({n_channels}ch)"
            media.class                     = Audio/Sink
            audio.channels                  = {n_channels}
            audio.position                  = [ {positions} ]
            node.autoconnect                = false
            session.suspend-timeout-seconds = 0
            node.pause-on-idle              = false
        }}

        playback.props = {{
            node.name                       = "{node_name_playback}"
            node.description                = "FIR Convolver Output"
            node.passive                    = true
            audio.channels                  = {n_channels}
            audio.position                  = [ {positions} ]
            node.autoconnect                = false
            session.suspend-timeout-seconds = 0
            node.pause-on-idle              = false
        }}
    }}
}}
]
"""
    return conf


def write_filter_chain_conf(
    output_path: str | Path,
    profile_name: str,
    **kwargs,
) -> Path:
    """Generate and write a PW filter-chain .conf file.

    Parameters are identical to generate_filter_chain_conf() plus output_path.

    Returns
    -------
    Path
        Path to the written file.
    """
    conf = generate_filter_chain_conf(profile_name, **kwargs)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(conf)
    return output_path
