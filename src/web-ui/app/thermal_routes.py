"""Thermal protection API endpoints (T-092-2/T-092-3, US-092).

GET  /api/v1/thermal/status          — Per-channel thermal state snapshot
GET  /api/v1/thermal/limiter         — Limiter state + gain reductions
GET  /api/v1/thermal/limiter/audit   — Limiter audit log
POST /api/v1/thermal/limiter/override — Set/clear operator ceiling override
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
