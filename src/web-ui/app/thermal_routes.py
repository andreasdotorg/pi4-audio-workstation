"""Thermal & mechanical protection API endpoints (T-092-2/T-092-3/T-092-7, US-092).

GET  /api/v1/thermal/status          — Per-channel thermal state snapshot
GET  /api/v1/thermal/limiter         — Limiter state + gain reductions
GET  /api/v1/thermal/limiter/audit   — Limiter audit log
POST /api/v1/thermal/limiter/override — Set/clear operator ceiling override
GET  /api/v1/thermal/protection      — Combined thermal + mechanical protection view
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/thermal", tags=["thermal"])


@router.get("/status")
async def thermal_status(request: Request):
    """Return per-channel thermal state snapshot.

    Returns a list of channel thermal states with power estimates,
    headroom, and warning/limit status.
    """
    monitor = getattr(request.app.state, "thermal_monitor", None)
    if monitor is None:
        return JSONResponse(
            status_code=503,
            content={"error": "not_available",
                     "detail": "Thermal monitor not running"},
        )

    result = {
        "channels": monitor.snapshot(),
        "any_warning": monitor.any_warning(),
        "any_limit": monitor.any_limit(),
    }

    # Include limiter state if available
    limiter = getattr(request.app.state, "thermal_limiter", None)
    if limiter is not None:
        limiter_snap = limiter.snapshot()
        result["limiter"] = limiter_snap

    return result


@router.get("/limiter")
async def limiter_status(request: Request):
    """Return current limiter state: gain reductions, overrides, limiting status."""
    limiter = getattr(request.app.state, "thermal_limiter", None)
    if limiter is None:
        return JSONResponse(
            status_code=503,
            content={"error": "not_available",
                     "detail": "Thermal limiter not running"},
        )
    return limiter.snapshot()


@router.get("/limiter/audit")
async def limiter_audit(request: Request, limit: int = 50):
    """Return recent limiter audit log entries."""
    limiter = getattr(request.app.state, "thermal_limiter", None)
    if limiter is None:
        return JSONResponse(
            status_code=503,
            content={"error": "not_available",
                     "detail": "Thermal limiter not running"},
        )
    limit = max(1, min(limit, 500))
    return {"entries": limiter.audit_log(limit=limit)}


class OverrideRequest(BaseModel):
    channel: str
    ceiling_multiplier: float = 1.5
    duration_seconds: float = 300.0
    acknowledged_by: str = "operator"


@router.post("/limiter/override")
async def set_override(request: Request, body: OverrideRequest):
    """Set a temporary ceiling override for a channel.

    The operator acknowledges the risk; the override is time-limited
    and logged in the audit trail.
    """
    limiter = getattr(request.app.state, "thermal_limiter", None)
    if limiter is None:
        return JSONResponse(
            status_code=503,
            content={"error": "not_available",
                     "detail": "Thermal limiter not running"},
        )
    result = limiter.set_override(
        channel_name=body.channel,
        ceiling_multiplier=body.ceiling_multiplier,
        duration_s=body.duration_seconds,
        acknowledged_by=body.acknowledged_by,
    )
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


class ClearOverrideRequest(BaseModel):
    channel: str


@router.post("/limiter/override/clear")
async def clear_override(request: Request, body: ClearOverrideRequest):
    """Clear an active ceiling override for a channel."""
    limiter = getattr(request.app.state, "thermal_limiter", None)
    if limiter is None:
        return JSONResponse(
            status_code=503,
            content={"error": "not_available",
                     "detail": "Thermal limiter not running"},
        )
    result = limiter.clear_override(channel_name=body.channel)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@router.get("/protection")
async def protection_status(request: Request):
    """Combined thermal + mechanical protection view per channel.

    Returns per-channel protection data including:
    - Thermal: power, ceiling, headroom, limiter state
    - Mechanical: HPF status, Xmax, estimated excursion (when T/S data available)
    """
    import os
    import sys
    from pathlib import Path

    channels = []

    # Get active profile data from speaker_routes
    active_profile = getattr(request.app.state, "active_speaker_profile", None)
    if active_profile is None:
        # Try to read from the active-profile marker
        try:
            from .speaker_routes import _speakers_dir
            base = _speakers_dir()
            if base:
                marker = base / "active-profile.txt"
                if marker.exists():
                    profile_name = marker.read_text().strip()
                    profile_path = base / "profiles" / f"{profile_name}.yml"
                    if profile_path.exists():
                        import yaml
                        active_profile = yaml.safe_load(profile_path.read_text())
        except Exception:
            pass

    if active_profile is None:
        return {"channels": [], "has_thermal": False, "has_mechanical": False}

    # Load identities for HPF and Xmax data
    identities = {}
    try:
        from .speaker_routes import _speakers_dir
        base = _speakers_dir()
        if base:
            ids_dir = base / "identities"
            if ids_dir.is_dir():
                import yaml
                for f in ids_dir.glob("*.yml"):
                    data = yaml.safe_load(f.read_text())
                    if data and isinstance(data, dict):
                        # Key by filename stem (identity name)
                        identities[f.stem] = data
    except Exception:
        pass

    # Get thermal monitor data
    monitor = getattr(request.app.state, "thermal_monitor", None)
    thermal_by_name = {}
    if monitor is not None:
        for ch in monitor.snapshot():
            thermal_by_name[ch["name"]] = ch

    # Get limiter data
    limiter = getattr(request.app.state, "thermal_limiter", None)
    limiter_by_name = {}
    if limiter is not None:
        for ch in limiter.snapshot().get("channels", []):
            limiter_by_name[ch["name"]] = ch

    # Build per-channel protection info
    speakers = active_profile.get("speakers", {})
    for spk_name, spk_cfg in speakers.items():
        if not isinstance(spk_cfg, dict):
            continue

        id_name = spk_cfg.get("identity", "")
        identity = identities.get(id_name, {})

        ch_info = {
            "name": spk_name,
            "channel": spk_cfg.get("channel", -1),
            "identity": id_name,
            "role": spk_cfg.get("role", "satellite"),
            "filter_type": spk_cfg.get("filter_type", ""),
        }

        # Mechanical protection: HPF
        mandatory_hpf = identity.get("mandatory_hpf_hz")
        ch_info["hpf_hz"] = mandatory_hpf
        ch_info["hpf_active"] = mandatory_hpf is not None

        # Mechanical protection: enclosure type and port tuning
        ch_info["enclosure_type"] = identity.get("type", "unknown")
        port_tuning = identity.get("port_tuning_hz")
        if isinstance(port_tuning, dict):
            ch_info["port_tuning_hz"] = min(
                v for v in port_tuning.values()
                if isinstance(v, (int, float)))
        elif isinstance(port_tuning, (int, float)):
            ch_info["port_tuning_hz"] = port_tuning
        else:
            ch_info["port_tuning_hz"] = None

        # Mechanical: Xmax (when T/S data available in identity)
        ch_info["xmax_mm"] = identity.get("xmax_mm")
        ch_info["has_ts_data"] = all(
            identity.get(k) is not None
            for k in ("fs_hz", "qts", "bl_tm", "mms_g", "cms_m_per_n"))

        # Thermal state
        thermal = thermal_by_name.get(spk_name, {})
        ch_info["thermal"] = {
            "power_watts": thermal.get("power_watts", 0),
            "ceiling_watts": thermal.get("ceiling_watts"),
            "headroom_db": thermal.get("headroom_db"),
            "pct_of_ceiling": thermal.get("pct_of_ceiling", 0),
            "status": thermal.get("status", "unknown"),
        }

        # Limiter state
        lim = limiter_by_name.get(spk_name, {})
        ch_info["limiter"] = {
            "is_limiting": lim.get("is_limiting", False),
            "reduction_db": lim.get("reduction_db", 0),
            "override": lim.get("override"),
        }

        # Power handling from identity
        ch_info["max_power_watts"] = identity.get("max_power_watts")
        ch_info["impedance_ohm"] = identity.get("impedance_ohm")

        channels.append(ch_info)

    # Sort by channel index
    channels.sort(key=lambda c: c.get("channel", 999))

    has_thermal = monitor is not None and len(thermal_by_name) > 0
    has_mechanical = any(c.get("hpf_active") or c.get("xmax_mm") for c in channels)

    return {
        "channels": channels,
        "has_thermal": has_thermal,
        "has_mechanical": has_mechanical,
    }
