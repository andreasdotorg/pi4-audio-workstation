"""FIR filter generation and deployment REST endpoints.

POST /api/v1/filters/generate — Generate crossover FIR filters + PW config
from a speaker profile. Runs the full pipeline:

    profile → crossover → combine → export WAV → verify → PW .conf

POST /api/v1/filters/deploy — Deploy generated filters to PipeWire coeffs dir
with D-009 safety interlock (all filters must pass verification).

POST /api/v1/filters/reload-pw — Reload PipeWire filter-chain (requires
explicit confirmation due to USBStreamer transient safety).

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
from typing import Dict, List, Optional

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


class FilterGenerateRequest(BaseModel):
    """Request body for POST /api/v1/filters/generate."""
    profile: str
    mode: str = "crossover_only"
    session_dir: Optional[str] = None
    output_dir: Optional[str] = None
    target_phon: Optional[float] = None
    reference_phon: float = 80.0
    delays_ms: Optional[Dict[str, float]] = None
    gains_db: Optional[Dict[str, float]] = None
    n_taps: int = DEFAULT_N_TAPS
    sample_rate: int = DEFAULT_SAMPLE_RATE
    generate_pw_conf: bool = True

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v):
        if v not in ("crossover_only", "crossover_plus_correction"):
            raise ValueError(
                "mode must be 'crossover_only' or 'crossover_plus_correction'"
            )
        return v

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


class FilterDeployRequest(BaseModel):
    """Request body for POST /api/v1/filters/deploy."""
    output_dir: str
    coeffs_dir: Optional[str] = None
    pw_conf_dir: Optional[str] = None
    dry_run: bool = False


class ReloadPWRequest(BaseModel):
    """Request body for POST /api/v1/filters/reload-pw."""
    confirmed: bool = False


def _load_correction_filters(session_dir: str, speakers: dict, n_taps: int) -> dict:
    """Load per-channel correction IRs from a measurement session directory.

    Looks for WAV files named ``ir_{spk_key}.wav`` in *session_dir*.
    Missing channels get a dirac (flat) placeholder.

    Returns a dict of {spk_key: np.ndarray}.
    """
    import soundfile as sf

    corrections = {}
    for spk_key in speakers:
        ir_path = os.path.join(session_dir, f"ir_{spk_key}.wav")
        if os.path.isfile(ir_path):
            data, _sr = sf.read(ir_path, dtype="float64")
            if data.ndim > 1:
                data = data[:, 0]
            corrections[spk_key] = data
            log.info("Loaded correction IR for %s from %s", spk_key, ir_path)
        else:
            log.info("No correction IR for %s — using dirac", spk_key)
    return corrections


def _run_pipeline(req: FilterGenerateRequest) -> dict:
    """Run the FIR generation pipeline synchronously (called in thread pool).

    Returns a dict with output paths, verification results, and optional
    PW config content.
    """
    from config_generator import (
        load_profile_with_identities,
        validate_and_raise,
    )
    from room_correction.generate_profile_filters import generate_profile_filters
    from room_correction.export import export_filter
    from room_correction.verify import verify_d009, verify_minimum_phase, verify_format
    from room_correction.pw_config_generator import generate_filter_chain_conf

    # Load and validate profile
    profile, identities = load_profile_with_identities(
        req.profile,
        profiles_dir=str(_PROFILES_DIR),
        identities_dir=str(_IDENTITIES_DIR),
    )
    validate_and_raise(profile, identities, identities_dir=str(_IDENTITIES_DIR))

    n_taps = req.n_taps
    sr = req.sample_rate

    # Build correction filters based on mode
    correction_filters = None
    if req.mode == "crossover_plus_correction":
        if not req.session_dir:
            raise ValueError(
                "session_dir is required for crossover_plus_correction mode"
            )
        if not os.path.isdir(req.session_dir):
            raise FileNotFoundError(
                f"Session directory not found: {req.session_dir}"
            )
        from room_correction.correction import generate_correction_filter
        raw_irs = _load_correction_filters(
            req.session_dir, profile["speakers"], n_taps,
        )
        correction_filters = {}
        for spk_key, ir in raw_irs.items():
            correction_filters[spk_key] = generate_correction_filter(
                ir, n_taps=n_taps, sr=sr,
            )

    # Delegate to topology-agnostic pipeline
    output_dir = req.output_dir or os.path.join(DEFAULT_OUTPUT_DIR, req.profile)
    timestamp = datetime.now()

    combined_filters = generate_profile_filters(
        profile=profile,
        identities=identities,
        correction_filters=correction_filters,
        n_taps=n_taps,
        sr=sr,
    )

    # Export WAV files
    os.makedirs(output_dir, exist_ok=True)
    output_paths = {}
    for spk_key, fir in combined_filters.items():
        ts = timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"combined_{spk_key}_{ts}.wav"
        path = os.path.join(output_dir, filename)
        export_filter(fir, path, n_taps=n_taps, sr=sr)
        output_paths[spk_key] = path

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

    # Extract crossover info for response
    crossover_raw = profile.get("crossover", {}).get("frequency_hz")
    if isinstance(crossover_raw, list):
        crossover_freq_hz = crossover_raw
    else:
        crossover_freq_hz = crossover_raw
    slope = profile.get("crossover", {}).get("slope_db_per_oct", 48)

    result = {
        "profile": req.profile,
        "mode": req.mode,
        "output_dir": output_dir,
        "channels": {name: str(path) for name, path in sorted(output_paths.items())},
        "verification": [v.to_dict() for v in verifications],
        "all_pass": all_pass,
        "n_taps": n_taps,
        "sample_rate": sr,
        "crossover_freq_hz": crossover_freq_hz,
        "slope_db_per_oct": slope,
    }

    # Generate PW filter-chain .conf
    if req.generate_pw_conf:
        pw_conf = generate_filter_chain_conf(
            req.profile,
            filter_paths={
                spk_key: str(output_paths.get(spk_key, ""))
                for spk_key in profile["speakers"]
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


# ---------------------------------------------------------------------------
# Deploy endpoints (US-090 T-090-2)
# ---------------------------------------------------------------------------

def _verify_all_wavs(output_dir: str) -> tuple:
    """Verify D-009 compliance on all combined_*.wav files in output_dir.

    Returns (all_pass, results_list) where results_list contains dicts
    with channel name, pass status, and peak gain.
    """
    from room_correction.verify import verify_d009

    import glob as globmod
    wav_files = sorted(globmod.glob(os.path.join(output_dir, "combined_*.wav")))
    if not wav_files:
        return False, []

    all_pass = True
    results = []
    for wav_path in wav_files:
        basename = os.path.basename(wav_path)
        d009 = verify_d009(wav_path)
        entry = {
            "file": basename,
            "d009_pass": d009.passed,
            "d009_peak_db": round(d009.details.get("max_gain_db", 0.0), 2),
        }
        results.append(entry)
        if not d009.passed:
            all_pass = False

    return all_pass, results


def _run_deploy(req: FilterDeployRequest) -> dict:
    """Run filter deployment synchronously (called in thread pool).

    Verifies D-009 on all WAVs, then copies them to the coeffs dir and
    deploys the PW config drop-in if present.
    """
    from room_correction.deploy import (
        deploy_filters,
        deploy_pw_config,
        DEFAULT_COEFFS_DIR,
        DEFAULT_PW_CONF_DIR,
        DEFAULT_PW_CONF_NAME,
    )

    output_dir = req.output_dir
    if not os.path.isdir(output_dir):
        raise FileNotFoundError(f"Output directory not found: {output_dir}")

    # D-009 safety interlock: verify all filters before deploying
    all_pass, verifications = _verify_all_wavs(output_dir)
    if not all_pass:
        return {
            "deployed": False,
            "reason": "d009_failed",
            "detail": "One or more filters exceed D-009 gain ceiling (-0.5 dB). "
                      "Deployment refused for safety.",
            "verification": verifications,
        }

    if not verifications:
        return {
            "deployed": False,
            "reason": "no_filters",
            "detail": f"No combined_*.wav files found in {output_dir}",
            "verification": [],
        }

    # Deploy WAV coefficients
    coeffs_dir = req.coeffs_dir or DEFAULT_COEFFS_DIR
    deployed_paths = deploy_filters(
        output_dir,
        coeffs_dir=coeffs_dir,
        verified=True,
        dry_run=req.dry_run,
    )

    # Deploy PW config if present in output_dir
    pw_conf_path = os.path.join(output_dir, DEFAULT_PW_CONF_NAME)
    pw_conf_deployed = None
    if os.path.isfile(pw_conf_path):
        pw_conf_dir = req.pw_conf_dir or DEFAULT_PW_CONF_DIR
        with open(pw_conf_path, "r") as f:
            conf_content = f.read()
        pw_conf_deployed = deploy_pw_config(
            conf_content,
            pw_conf_dir=pw_conf_dir,
            dry_run=req.dry_run,
        )

    return {
        "deployed": True,
        "dry_run": req.dry_run,
        "deployed_paths": deployed_paths,
        "pw_conf_deployed": pw_conf_deployed,
        "verification": verifications,
        "reload_required": True,
        "reload_warning": (
            "PipeWire must be restarted to load new filters. "
            "WARNING: Restarting PipeWire resets the USBStreamer, producing "
            "transients through the amplifier chain. Ensure amplifiers are "
            "OFF or MUTED before calling POST /api/v1/filters/reload-pw."
        ),
    }


@router.post("/deploy")
async def deploy_filters_endpoint(req: FilterDeployRequest):
    """Deploy generated filters to PipeWire coefficients directory.

    Pre-deploy safety interlock: all filters must pass D-009 verification
    (gain <= -0.5 dB at every frequency). Deployment is refused if any
    filter fails.

    Does NOT auto-reload PipeWire (USBStreamer transient safety).
    Use POST /api/v1/filters/reload-pw separately after confirming amps
    are off/muted.
    """
    try:
        result = await asyncio.to_thread(_run_deploy, req)
    except FileNotFoundError as e:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "detail": str(e)},
        )
    except Exception as e:
        log.exception("Filter deployment failed")
        return JSONResponse(
            status_code=500,
            content={"error": "deploy_failed", "detail": str(e)},
        )

    if not result["deployed"]:
        return JSONResponse(status_code=422, content=result)

    return JSONResponse(content=result, status_code=200)


@router.post("/reload-pw")
async def reload_pw_endpoint(req: ReloadPWRequest):
    """Reload PipeWire filter-chain by restarting the PipeWire user service.

    Requires ``confirmed: true`` in the request body as an explicit safety
    acknowledgment. Restarting PipeWire resets the USBStreamer, producing
    transients through the amplifier chain that can damage speakers.
    """
    if not req.confirmed:
        return JSONResponse(
            status_code=400,
            content={
                "error": "confirmation_required",
                "detail": (
                    "Restarting PipeWire resets the USBStreamer, producing "
                    "transients through the amplifier chain. Set "
                    "'confirmed: true' to acknowledge this risk."
                ),
            },
        )

    from room_correction.deploy import reload_pipewire

    log.warning("PipeWire reload requested via API (confirmed=true)")
    try:
        success = await asyncio.to_thread(reload_pipewire)
    except Exception as e:
        log.exception("PipeWire reload failed")
        return JSONResponse(
            status_code=500,
            content={"error": "reload_failed", "detail": str(e)},
        )

    if success:
        log.info("PipeWire reloaded successfully via API")
        return {"reloaded": True}
    else:
        return JSONResponse(
            status_code=503,
            content={
                "error": "reload_unavailable",
                "detail": "systemctl not available or restart failed. "
                          "Manual reload may be required.",
            },
        )
