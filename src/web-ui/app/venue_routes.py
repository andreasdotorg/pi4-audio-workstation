"""Venue selection and audio gate REST endpoints (US-113 Phase 4).

Endpoints:
    GET  /api/v1/venue/list       List available venue configs
    GET  /api/v1/venue/current    Get active venue name + gate status
    POST /api/v1/venue/select     Load a venue config by name
    GET  /api/v1/venue/detail     Load venue YAML for display (local parse)
    POST /api/v1/venue/gate/open  Open the audio gate (D-063)
    POST /api/v1/venue/gate/close Close the audio gate (D-063)

All venue/gate operations go through the GraphManager RPC (port 4002).
The detail endpoint parses the venue YAML locally for channel display.

Safety:
    - Gate open requires explicit operator action + confirmation dialog (UI).
    - Gate close is always safe (zeroes all gains immediately).
    - Watchdog mute closes the gate automatically (Phase 3 must-fix).
"""

from __future__ import annotations

import logging
import os
import socket
import sys

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"

GM_HOST = os.environ.get("PI4AUDIO_GM_HOST", "127.0.0.1")
GM_PORT = int(os.environ.get("PI4AUDIO_GM_PORT", "4002"))

# Path to measurement client modules (graph_manager_client).
_MEASUREMENT_SRC = os.path.join(
    os.path.dirname(__file__), "..", "..", "measurement"
)
if _MEASUREMENT_SRC not in sys.path:
    sys.path.insert(0, _MEASUREMENT_SRC)

router = APIRouter(prefix="/api/v1/venue", tags=["venue"])


# -- Request models ---------------------------------------------------------

class VenueSelectRequest(BaseModel):
    venue: str


# -- GM RPC helper ----------------------------------------------------------

def _gm_client():
    """Create and connect a GraphManager client (real or mock)."""
    from graph_manager_client import GraphManagerClient, MockGraphManagerClient

    if MOCK_MODE:
        client = MockGraphManagerClient(host=GM_HOST, port=GM_PORT)
    else:
        client = GraphManagerClient(host=GM_HOST, port=GM_PORT)
    client.connect()
    return client


# -- Endpoints --------------------------------------------------------------

@router.get("/list")
async def list_venues():
    """List available venue configs from GraphManager."""
    try:
        gm = _gm_client()
        try:
            venues = gm.list_venues()
        finally:
            gm.close()
    except (OSError, TimeoutError, ConnectionError) as exc:
        log.warning("GM unreachable for list_venues: %s", exc)
        # Fallback: list from local venue.py
        from .venue import list_venues as local_list
        venues = local_list()

    return {"venues": venues}


@router.get("/current")
async def get_current():
    """Get active venue name and gate status."""
    try:
        gm = _gm_client()
        try:
            gate = gm.get_gate()
        finally:
            gm.close()
    except (OSError, TimeoutError, ConnectionError) as exc:
        log.warning("GM unreachable for get_gate: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unreachable",
                     "detail": f"GraphManager not reachable: {exc}"},
        )

    return {
        "venue": gate.get("venue"),
        "gate_open": gate.get("gate_open", False),
        "has_pending_gains": gate.get("has_pending_gains", False),
    }


@router.post("/select")
async def select_venue(body: VenueSelectRequest):
    """Load a venue config by name via GraphManager RPC."""
    from .venue import _SAFE_NAME

    if not _SAFE_NAME.match(body.venue):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_venue_name",
                     "detail": "Venue name contains invalid characters"},
        )

    try:
        gm = _gm_client()
        try:
            gm.set_venue(body.venue)
            gate = gm.get_gate()
        finally:
            gm.close()
    except (OSError, TimeoutError, ConnectionError) as exc:
        log.warning("GM unreachable for set_venue: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unreachable",
                     "detail": f"GraphManager not reachable: {exc}"},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={"error": "set_venue_failed", "detail": str(exc)},
        )

    return {
        "ok": True,
        "venue": body.venue,
        "gate_open": gate.get("gate_open", False),
        "has_pending_gains": gate.get("has_pending_gains", False),
    }


@router.get("/detail")
async def venue_detail(name: str):
    """Load venue YAML for display (local parse, no GM RPC needed)."""
    from .venue import load_venue, CHANNEL_KEYS, CHANNEL_TO_GAIN_NODE

    try:
        data = load_venue(name)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_venue", "detail": str(exc)},
        )

    channels = []
    for ch_key in CHANNEL_KEYS:
        ch = data["channels"][ch_key]
        channels.append({
            "key": ch_key,
            "gain_node": CHANNEL_TO_GAIN_NODE[ch_key],
            "gain_db": ch["gain_db"],
            "gain_mult": data["gains"][CHANNEL_TO_GAIN_NODE[ch_key]],
            "delay_ms": ch["delay_ms"],
            "coefficients": ch["coefficients"],
        })

    return {
        "name": data.get("name", name),
        "description": data.get("description", ""),
        "channels": channels,
    }


@router.post("/gate/open")
async def gate_open():
    """Open the audio gate (D-063). Requires a venue to be loaded."""
    try:
        gm = _gm_client()
        try:
            gm.open_gate()
            gate = gm.get_gate()
        finally:
            gm.close()
    except (OSError, TimeoutError, ConnectionError) as exc:
        log.warning("GM unreachable for open_gate: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unreachable",
                     "detail": f"GraphManager not reachable: {exc}"},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={"error": "open_gate_failed", "detail": str(exc)},
        )

    return {
        "ok": True,
        "gate_open": gate.get("gate_open", True),
        "venue": gate.get("venue"),
    }


@router.post("/gate/close")
async def gate_close():
    """Close the audio gate (D-063). Zeroes all gains."""
    try:
        gm = _gm_client()
        try:
            gm.close_gate()
        finally:
            gm.close()
    except (OSError, TimeoutError, ConnectionError) as exc:
        log.warning("GM unreachable for close_gate: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unreachable",
                     "detail": f"GraphManager not reachable: {exc}"},
        )

    return {"ok": True, "gate_open": False}
