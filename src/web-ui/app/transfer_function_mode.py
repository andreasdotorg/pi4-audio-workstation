"""Transfer function measurement mode endpoints (US-120 T-120-04).

REST API for the transfer function view's design/verify mode toggle:

    GET  /api/v1/tf/mode          Query current TF measurement mode
    POST /api/v1/tf/mode          Set design or verify mode
    POST /api/v1/tf/start         Start TF measurement (ensure measurement mode)
    POST /api/v1/tf/stop          Stop TF measurement (restore previous GM mode)

Design mode (AC #4): GM loads Dirac (identity) room correction coefficients
into the convolver while preserving crossover slopes and HPF. Shows raw
room response.

Verify mode (AC #4): GM loads real room correction filters into the convolver.
Shows corrected response.

Both modes use the same post-convolver reference tap. Only the convolver
coefficients change between modes.

Safety: Measurement gain profile (AC #5, S-012) requires explicit operator
confirmation before activating. D-009 gain constraints unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tf", tags=["transfer-function"])

# GM RPC connection.
GM_HOST = os.environ.get("PI4AUDIO_GM_HOST", "127.0.0.1")
GM_PORT = int(os.environ.get("PI4AUDIO_GM_PORT", "4002"))
MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"


# -- State --

class _TfModeState:
    """Module-level state for the TF measurement mode."""

    def __init__(self) -> None:
        self.active: bool = False
        self.filter_mode: str = "design"  # "design" or "verify"
        self.previous_gm_mode: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "active": self.active,
            "filter_mode": self.filter_mode,
            "previous_gm_mode": self.previous_gm_mode,
        }


_state = _TfModeState()


# -- GM RPC helpers --

def _gm_rpc(cmd: dict) -> dict:
    """Send a JSON-RPC command to the GraphManager and return the response."""
    if MOCK_MODE:
        return _mock_gm_rpc(cmd)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    try:
        sock.connect((GM_HOST, GM_PORT))
        sock.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode("utf-8").strip())
    finally:
        sock.close()


_mock_gm_mode = "standby"


def _mock_gm_rpc(cmd: dict) -> dict:
    """Mock GM RPC for local development."""
    global _mock_gm_mode
    if cmd.get("cmd") == "get_state":
        return {"type": "response", "cmd": "get_state", "ok": True,
                "mode": _mock_gm_mode}
    if cmd.get("cmd") == "set_mode":
        old = _mock_gm_mode
        _mock_gm_mode = cmd.get("mode", "standby")
        log.info("[mock] GM mode: %s -> %s", old, _mock_gm_mode)
        return {"type": "ack", "cmd": "set_mode", "ok": True}
    return {"type": "ack", "cmd": cmd.get("cmd", "?"), "ok": True}


def _gm_get_mode() -> str:
    """Query the current GM operating mode."""
    resp = _gm_rpc({"cmd": "get_state"})
    return resp.get("mode", "unknown")


def _gm_set_mode(mode: str) -> None:
    """Set the GM operating mode."""
    resp = _gm_rpc({"cmd": "set_mode", "mode": mode})
    if not resp.get("ok", False):
        raise RuntimeError(
            f"GM set_mode failed: {resp.get('error', 'unknown')}")


# -- Endpoints --

@router.get("/mode")
async def get_tf_mode():
    """Query the current transfer function measurement mode."""
    return _state.to_dict()


@router.post("/mode")
async def set_tf_mode(request: Request):
    """Set the filter mode for transfer function measurement.

    Body: {"filter_mode": "design"} or {"filter_mode": "verify"}

    In design mode, the convolver loads Dirac (identity) coefficients
    so the transfer function shows the raw room response.

    In verify mode, the convolver loads real correction filters so the
    transfer function shows the corrected response.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400,
                            content={"error": "invalid_json"})

    filter_mode = data.get("filter_mode", "design")
    if filter_mode not in ("design", "verify"):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_filter_mode",
                     "detail": "Must be 'design' or 'verify'"},
        )

    old = _state.filter_mode
    _state.filter_mode = filter_mode
    log.info("TF filter mode: %s -> %s", old, filter_mode)

    return {
        "filter_mode": filter_mode,
        "switched": old != filter_mode,
        "active": _state.active,
    }


@router.post("/start")
async def start_tf_measurement(request: Request):
    """Start transfer function measurement (AC #5, S-012).

    Switches GM to measurement mode. Requires operator confirmation.
    Body: {"confirmed": true, "filter_mode": "design"}
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    if not data.get("confirmed", False):
        return JSONResponse(
            status_code=400,
            content={
                "error": "confirmation_required",
                "detail": (
                    "Starting transfer function measurement switches the "
                    "audio routing to measurement mode. Any active DJ or "
                    "live audio will stop. Set 'confirmed: true' to proceed."
                ),
            },
        )

    # Query current GM mode.
    try:
        current_mode = await asyncio.to_thread(_gm_get_mode)
    except Exception as exc:
        log.warning("Failed to query GM mode: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unavailable", "detail": str(exc)},
        )

    # Save previous mode for restoration.
    if current_mode != "measurement":
        _state.previous_gm_mode = current_mode

    # Switch to measurement mode if needed.
    if current_mode != "measurement":
        try:
            await asyncio.to_thread(_gm_set_mode, "measurement")
            log.info("TF: GM %s -> measurement", current_mode)
        except Exception as exc:
            log.error("Failed to switch GM to measurement: %s", exc)
            return JSONResponse(
                status_code=502,
                content={"error": "gm_mode_switch_failed",
                         "detail": str(exc)},
            )

    _state.active = True
    if "filter_mode" in data:
        fm = data["filter_mode"]
        if fm in ("design", "verify"):
            _state.filter_mode = fm

    return {
        "active": True,
        "filter_mode": _state.filter_mode,
        "previous_gm_mode": _state.previous_gm_mode,
    }


@router.post("/stop")
async def stop_tf_measurement():
    """Stop transfer function measurement and restore previous GM mode."""
    if not _state.active:
        return {"active": False, "message": "Not in TF measurement mode"}

    target = _state.previous_gm_mode or "standby"

    try:
        current = await asyncio.to_thread(_gm_get_mode)
        if current == "measurement":
            await asyncio.to_thread(_gm_set_mode, target)
            log.info("TF stopped: GM measurement -> %s", target)
    except Exception as exc:
        log.warning("Failed to restore GM to %s: %s", target, exc)

    _state.active = False
    _state.previous_gm_mode = None

    return {"active": False, "restored_mode": target}
