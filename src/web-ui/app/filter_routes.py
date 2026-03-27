"""FIR filter generation REST endpoint.

POST /api/v1/filters/generate — Generate crossover FIR filters + PW config
from a speaker profile. Runs the full pipeline:

    profile → crossover → combine → export WAV → verify → PW .conf

The generation runs in a thread pool to avoid blocking the event loop
(FIR computation + FFT is CPU-bound).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import numpy as np
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/filters", tags=["filters"])

# Add room-correction to import path
_RC_DIR = Path(__file__).resolve().parent.parent.parent / "room-correction"
if str(_RC_DIR) not in sys.path:
    sys.path.insert(0, str(_RC_DIR))

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PROFILES_DIR = _PROJECT_ROOT / "configs" / "speakers" / "profiles"
_IDENTITIES_DIR = _PROJECT_ROOT / "configs" / "speakers" / "identities"

# Default output directory (overridable via env var)
DEFAULT_OUTPUT_DIR = os.environ.get(
    "PI4AUDIO_FILTER_OUTPUT_DIR",
    str(_RC_DIR / "output"),
)

DEFAULT_SAMPLE_RATE = 48000
DEFAULT_N_TAPS = 16384
COMBINE_MARGIN_DB = -0.6  # Internal margin for cepstral reconstruction error


class FilterGenerateRequest(BaseModel):
    """Request body for POST /api/v1/filters/generate."""
    profile: str
    output_dir: Optional[str] = None
    target_phon: Optional[float] = None
    reference_phon: float = 80.0
    delays_ms: Optional[Dict[str, float]] = None
    gains_db: Optional[Dict[str, float]] = None
    n_taps: int = DEFAULT_N_TAPS
    sample_rate: int = DEFAULT_SAMPLE_RATE
    generate_pw_conf: bool = True

    @field_validator("n_taps")
    @classmethod
    def validate_n_taps(cls, v):
        if v not in (4096, 8192, 16384, 32768):
            raise ValueError("n_taps must be 4096, 8192, 16384, or 32768")
        return v

    @field_validator("sample_rate")
    @classmethod
    def validate_sample_rate(cls, v):
        if v not in (44100, 48000, 96000):
            raise ValueError("sample_rate must be 44100, 48000, or 96000")
        return v


class VerificationResult:
    """Compact verification result for JSON serialization."""
    def __init__(self, channel: str, d009_pass: bool, d009_peak_db: float,
                 min_phase_pass: bool, format_pass: bool):
        self.channel = channel
        self.d009_pass = d009_pass
        self.d009_peak_db = d009_peak_db
        self.min_phase_pass = min_phase_pass
        self.format_pass = format_pass

    def to_dict(self):
        return {
            "channel": self.channel,
            "d009_pass": self.d009_pass,
            "d009_peak_db": round(self.d009_peak_db, 2),
            "min_phase_pass": self.min_phase_pass,
            "format_pass": self.format_pass,
            "all_pass": self.d009_pass and self.min_phase_pass and self.format_pass,
        }


def _run_pipeline(req: FilterGenerateRequest) -> dict:
    """Run the FIR generation pipeline synchronously (called in thread pool).

    Returns a dict with output paths, verification results, and optional
    PW config content.
    """
    from config_generator import (
        load_profile_with_identities,
        validate_and_raise,
        _classify_speakers,
    )
    from room_correction.crossover import generate_crossover_filter, generate_subsonic_filter
    from room_correction.combine import combine_filters
    from room_correction.export import export_all_filters
    from room_correction.verify import verify_d009, verify_minimum_phase, verify_format
    from room_correction.target_curves import get_target_curve
    from room_correction.pw_config_generator import generate_filter_chain_conf

    # Load and validate profile
    profile, identities = load_profile_with_identities(
        req.profile,
        profiles_dir=str(_PROFILES_DIR),
        identities_dir=str(_IDENTITIES_DIR),
    )
    validate_and_raise(profile, identities, identities_dir=str(_IDENTITIES_DIR))

    crossover_freq = profile["crossover"]["frequency_hz"]
    slope = profile["crossover"]["slope_db_per_oct"]
    n_taps = req.n_taps
    sr = req.sample_rate

    satellites, subwoofers = _classify_speakers(profile)
    all_speakers = satellites + subwoofers

    # Generate crossover component filters
    hp_crossover = generate_crossover_filter(
        filter_type="highpass",
        crossover_freq=crossover_freq,
        slope_db_per_oct=slope,
        n_taps=n_taps,
        sr=sr,
    )
    lp_crossover = generate_crossover_filter(
        filter_type="lowpass",
        crossover_freq=crossover_freq,
        slope_db_per_oct=slope,
        n_taps=n_taps,
        sr=sr,
    )

    # Subsonic protection filters (per identity)
    subsonic_filters = {}
    for spk_key, spk_cfg in all_speakers:
        id_name = spk_cfg["identity"]
        identity = identities.get(id_name, {})
        hpf_hz = identity.get("mandatory_hpf_hz")
        if hpf_hz and spk_cfg.get("role") == "subwoofer":
            if hpf_hz not in subsonic_filters:
                subsonic_filters[hpf_hz] = generate_subsonic_filter(
                    hpf_freq=hpf_hz,
                    slope_db_per_oct=slope,
                    n_taps=n_taps,
                    sr=sr,
                )

    # Correction filter placeholder (dirac = flat)
    # TODO: Replace with actual room correction when measurement data available
    dirac = np.zeros(n_taps)
    dirac[0] = 1.0

    # ISO 226 equal-loudness compensation (magnitude-only, minimum-phase safe)
    # Applied to the correction filter as target curve shaping.
    # For now, applied as a flat deviation since we don't have real correction yet.
    # When room measurement data is available, this will shape the target curve
    # that the correction filter is computed against.

    # Channel suffix mapping
    _KEY_TO_SUFFIX = {
        "sat_left": "left_hp",
        "sat_right": "right_hp",
        "sub1": "sub1_lp",
        "sub2": "sub2_lp",
    }

    # Combine filters per channel
    combined = {}
    for spk_key, spk_cfg in all_speakers:
        suffix = _KEY_TO_SUFFIX.get(spk_key, spk_key)
        role = spk_cfg.get("role", "satellite")
        filter_type = spk_cfg.get("filter_type", "highpass")

        if filter_type == "highpass":
            xo = hp_crossover
        else:
            xo = lp_crossover

        # Subsonic filter for subs
        subsonic = None
        if role == "subwoofer":
            id_name = spk_cfg["identity"]
            identity = identities.get(id_name, {})
            hpf_hz = identity.get("mandatory_hpf_hz")
            if hpf_hz:
                subsonic = subsonic_filters.get(hpf_hz)

        combined[suffix] = combine_filters(
            correction_filter=dirac,
            crossover_filter=xo,
            n_taps=n_taps,
            margin_db=COMBINE_MARGIN_DB,
            subsonic_filter=subsonic,
        )

    # Export WAV files
    output_dir = req.output_dir or os.path.join(DEFAULT_OUTPUT_DIR, req.profile)
    timestamp = datetime.now()
    output_paths = export_all_filters(
        combined, output_dir, n_taps=n_taps, sr=sr, timestamp=timestamp,
    )

    # Verify all generated filters
    verifications = []
    all_pass = True
    for name, path in sorted(output_paths.items()):
        d009 = verify_d009(path)
        min_phase = verify_minimum_phase(path)
        fmt = verify_format(path, expected_taps=n_taps, expected_sr=sr)

        vr = VerificationResult(
            channel=name,
            d009_pass=d009.passed,
            d009_peak_db=d009.details.get("max_gain_db", 0.0),
            min_phase_pass=min_phase.passed,
            format_pass=fmt.passed,
        )
        verifications.append(vr)
        if not vr.to_dict()["all_pass"]:
            all_pass = False

    result = {
        "profile": req.profile,
        "output_dir": output_dir,
        "channels": {name: str(path) for name, path in sorted(output_paths.items())},
        "verification": [v.to_dict() for v in verifications],
        "all_pass": all_pass,
        "n_taps": n_taps,
        "sample_rate": sr,
        "crossover_freq_hz": crossover_freq,
        "slope_db_per_oct": slope,
    }

    # Generate PW filter-chain .conf
    if req.generate_pw_conf:
        pw_conf = generate_filter_chain_conf(
            req.profile,
            filter_paths={
                spk_key: str(output_paths.get(
                    _KEY_TO_SUFFIX.get(spk_key, spk_key), ""))
                for spk_key, _ in all_speakers
            },
            gains_db=req.gains_db,
            delays_ms=req.delays_ms,
            profiles_dir=str(_PROFILES_DIR),
            identities_dir=str(_IDENTITIES_DIR),
            validate=False,  # Already validated above
        )
        pw_conf_path = os.path.join(output_dir, "30-filter-chain-convolver.conf")
        Path(pw_conf_path).write_text(pw_conf)
        result["pw_conf_path"] = pw_conf_path

    return result


@router.post("/generate")
async def generate_filters(req: FilterGenerateRequest):
    """Generate crossover FIR filters and PW config from a speaker profile.

    Runs the full pipeline: crossover generation, filter combination,
    WAV export, D-009/minimum-phase verification, and PW config generation.

    The computation runs in a thread pool to avoid blocking the event loop.
    """
    try:
        result = await asyncio.to_thread(_run_pipeline, req)
    except FileNotFoundError as e:
        return JSONResponse(
            status_code=404,
            content={"error": "profile_not_found", "detail": str(e)},
        )
    except Exception as e:
        log.exception("Filter generation failed for profile %r", req.profile)
        return JSONResponse(
            status_code=500,
            content={"error": "generation_failed", "detail": str(e)},
        )

    status = 200 if result["all_pass"] else 207  # 207 = Multi-Status (partial success)
    return JSONResponse(content=result, status_code=status)


@router.get("/profiles")
async def list_profiles():
    """List available speaker profiles for filter generation."""
    profiles = []
    if _PROFILES_DIR.is_dir():
        for p in sorted(_PROFILES_DIR.glob("*.yml")):
            profiles.append(p.stem)
    return {"profiles": profiles}
