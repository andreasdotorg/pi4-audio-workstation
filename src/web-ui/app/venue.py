"""Venue configuration loader (US-113 Phase 1).

A venue config defines per-channel gain, delay, and coefficient settings
for a specific performance location.  The 8-channel structure matches the
D-063 filter-chain convolver (4 speaker + 4 monitoring channels).

Functions:
    list_venues()       — List available venue config files.
    load_venue(name)    — Load and validate a venue config by name.
    gain_db_to_linear() — Convert dB gain to linear Mult value.

Venue YAML schema::

    name: "venue-name"
    description: "optional description"
    channels:
      1_sat_l:   { gain_db: -20, delay_ms: 0, coefficients: "dirac.wav" }
      2_sat_r:   { gain_db: -20, delay_ms: 0, coefficients: "dirac.wav" }
      3_sub1_lp: { gain_db: -20, delay_ms: 0, coefficients: "dirac.wav" }
      4_sub2_lp: { gain_db: -20, delay_ms: 0, coefficients: "dirac.wav" }
      5_eng_l:   { gain_db: -20, delay_ms: 0, coefficients: "dirac.wav" }
      6_eng_r:   { gain_db: -20, delay_ms: 0, coefficients: "dirac.wav" }
      7_iem_l:   { gain_db: -20, delay_ms: 0, coefficients: "dirac.wav" }
      8_iem_r:   { gain_db: -20, delay_ms: 0, coefficients: "dirac.wav" }

Channel keys must match the canonical 8-channel set.  gain_db is converted
to linear Mult via ``10^(gain_db/20)``.  Gains are capped at 0 dB (Mult 1.0)
per D-009.
"""

from __future__ import annotations

import logging
import math
import os
import pathlib
import re
from typing import Any

import yaml

log = logging.getLogger(__name__)

# -- Channel mapping ---------------------------------------------------------

# Canonical channel keys in the venue YAML, ordered by channel index.
CHANNEL_KEYS = [
    "1_sat_l",
    "2_sat_r",
    "3_sub1_lp",
    "4_sub2_lp",
    "5_eng_l",
    "6_eng_r",
    "7_iem_l",
    "8_iem_r",
]

# Map venue channel keys to PW filter-chain gain node names.
# Must match the node names in 30-filter-chain-convolver.conf.
CHANNEL_TO_GAIN_NODE = {
    "1_sat_l":   "gain_left_hp",
    "2_sat_r":   "gain_right_hp",
    "3_sub1_lp": "gain_sub1_lp",
    "4_sub2_lp": "gain_sub2_lp",
    "5_eng_l":   "gain_hp_l",
    "6_eng_r":   "gain_hp_r",
    "7_iem_l":   "gain_iem_l",
    "8_iem_r":   "gain_iem_r",
}

# Map venue channel keys to PW filter-chain convolver node names.
CHANNEL_TO_CONV_NODE = {
    "1_sat_l":   "conv_left_hp",
    "2_sat_r":   "conv_right_hp",
    "3_sub1_lp": "conv_sub1_lp",
    "4_sub2_lp": "conv_sub2_lp",
    "5_eng_l":   "conv_hp_l",
    "6_eng_r":   "conv_hp_r",
    "7_iem_l":   "conv_iem_l",
    "8_iem_r":   "conv_iem_r",
}

# Reverse mapping: PW gain node name -> venue channel key.
# Used for status/staleness comparison (reading PW state back to venue model).
GAIN_NODE_TO_CHANNEL = {v: k for k, v in CHANNEL_TO_GAIN_NODE.items()}

REQUIRED_CHANNEL_COUNT = 8

# D-009: gain must never exceed 0 dB (Mult 1.0).
GAIN_DB_HARD_CAP = 0.0

# Below this dB value, treat as muted (Mult = 0.0).
GAIN_DB_MUTE_THRESHOLD = -120.0

# Sanity limit for per-channel delay (ms).
# 50ms = ~17m sound travel distance — any venue delay above this is suspect.
DELAY_MS_MAX = 50.0

# -- Directory resolution ----------------------------------------------------

_PI_VENUES_DIR = pathlib.Path(
    os.environ.get("PI4AUDIO_VENUES_DIR", "/etc/pi4audio/venues")
)
_REPO_VENUES_DIR = (
    pathlib.Path(__file__).resolve().parents[3] / "configs" / "venues"
)

# Allowed filename characters (prevent path traversal).
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _venues_dir() -> pathlib.Path | None:
    """Return the venues config directory, checking Pi path then repo."""
    if _PI_VENUES_DIR.is_dir():
        return _PI_VENUES_DIR
    if _REPO_VENUES_DIR.is_dir():
        return _REPO_VENUES_DIR
    return None


# -- Public API --------------------------------------------------------------

def gain_db_to_linear(db: float) -> float:
    """Convert a dB gain value to a linear Mult value.

    D-009 safety: clamps to [0.0, 1.0].
    Values below -120 dB are treated as muted (returns 0.0).
    """
    if db <= GAIN_DB_MUTE_THRESHOLD:
        return 0.0
    if db > GAIN_DB_HARD_CAP:
        db = GAIN_DB_HARD_CAP
    return 10.0 ** (db / 20.0)


def list_venues() -> list[dict[str, str]]:
    """List available venue config files.

    Returns a list of dicts with 'name' (filename stem) and
    'display_name' (from YAML 'name' field) keys, sorted by name.
    """
    base = _venues_dir()
    if base is None:
        return []
    result = []
    for f in sorted(base.iterdir()):
        if f.suffix in (".yml", ".yaml") and f.is_file():
            try:
                data = yaml.safe_load(f.read_text())
            except Exception:
                data = {}
            display_name = (
                data.get("name", f.stem) if isinstance(data, dict) else f.stem
            )
            result.append({"name": f.stem, "display_name": display_name})
    return result


def load_venue(name: str) -> dict[str, Any]:
    """Load and validate a venue config by filename stem.

    Returns the parsed venue dict with an additional 'gains' key mapping
    PW gain node names to linear Mult values.

    Raises:
        ValueError: If the name is invalid, not found, or the YAML is
            malformed / missing required fields.
    """
    if not _SAFE_NAME.match(name):
        raise ValueError(f"Invalid venue name: {name!r}")

    base = _venues_dir()
    if base is None:
        raise ValueError("No venues directory found")

    # Try .yml first (project convention), then .yaml.
    path = None
    for ext in (".yml", ".yaml"):
        candidate = base / (name + ext)
        if candidate.is_file():
            path = candidate
            break

    if path is None:
        raise ValueError(f"Venue '{name}' not found")

    try:
        data = yaml.safe_load(path.read_text())
    except Exception as exc:
        raise ValueError(f"Failed to parse venue '{name}': {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Venue '{name}' must be a YAML mapping")

    err = validate_venue(data)
    if err is not None:
        raise ValueError(f"Venue '{name}': {err}")

    # Compute linear gains and attach to the venue dict.
    data["gains"] = _compute_gains(data["channels"])
    return data


# -- Validation --------------------------------------------------------------

def validate_venue(data: dict) -> str | None:
    """Validate venue YAML structure.

    Returns an error string if invalid, or None if valid.
    Follows the same pattern as speaker_routes._validate_profile().
    """
    if not isinstance(data, dict):
        return "venue must be a YAML mapping"

    if "name" not in data:
        return "missing required field: name"
    if not isinstance(data["name"], str) or not data["name"].strip():
        return "'name' must be a non-empty string"

    if "channels" not in data:
        return "missing required field: channels"

    channels = data["channels"]
    if not isinstance(channels, dict):
        return "'channels' must be a mapping"

    if len(channels) != REQUIRED_CHANNEL_COUNT:
        return (
            f"expected {REQUIRED_CHANNEL_COUNT} channels, "
            f"got {len(channels)}"
        )

    missing = set(CHANNEL_KEYS) - set(channels.keys())
    if missing:
        return f"missing channel(s): {', '.join(sorted(missing))}"

    extra = set(channels.keys()) - set(CHANNEL_KEYS)
    if extra:
        return f"unknown channel(s): {', '.join(sorted(extra))}"

    for ch_key, ch_data in channels.items():
        if not isinstance(ch_data, dict):
            return f"channel '{ch_key}': must be a mapping"

        # gain_db: required, numeric, <= 0 dB (D-009)
        if "gain_db" not in ch_data:
            return f"channel '{ch_key}': missing 'gain_db'"
        gain = ch_data["gain_db"]
        if not isinstance(gain, (int, float)):
            return (
                f"channel '{ch_key}': 'gain_db' must be a number, "
                f"got {type(gain).__name__}"
            )
        if gain > GAIN_DB_HARD_CAP:
            return (
                f"channel '{ch_key}': gain_db {gain} exceeds "
                f"D-009 hard cap of {GAIN_DB_HARD_CAP} dB"
            )

        # delay_ms: required, numeric, [0, 50]
        if "delay_ms" not in ch_data:
            return f"channel '{ch_key}': missing 'delay_ms'"
        delay = ch_data["delay_ms"]
        if not isinstance(delay, (int, float)):
            return (
                f"channel '{ch_key}': 'delay_ms' must be a number, "
                f"got {type(delay).__name__}"
            )
        if delay < 0:
            return f"channel '{ch_key}': delay_ms must be >= 0, got {delay}"
        if delay > DELAY_MS_MAX:
            return (
                f"channel '{ch_key}': delay_ms {delay} exceeds "
                f"sanity limit of {DELAY_MS_MAX} ms"
            )

        # coefficients: required, safe filename
        if "coefficients" not in ch_data:
            return f"channel '{ch_key}': missing 'coefficients'"
        coeff = ch_data["coefficients"]
        if not isinstance(coeff, str) or not coeff.strip():
            return f"channel '{ch_key}': 'coefficients' must be a non-empty string"
        if not _SAFE_NAME.match(coeff):
            return (
                f"channel '{ch_key}': coefficients filename '{coeff}' "
                f"contains invalid characters"
            )

    return None


def _compute_gains(channels: dict) -> dict[str, float]:
    """Compute PW gain node name -> linear Mult mapping from channel data."""
    gains = {}
    for ch_key, ch_data in channels.items():
        gain_node = CHANNEL_TO_GAIN_NODE[ch_key]
        gains[gain_node] = gain_db_to_linear(ch_data["gain_db"])
    return gains
