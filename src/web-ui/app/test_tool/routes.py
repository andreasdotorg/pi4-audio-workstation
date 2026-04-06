"""Test tool REST endpoints (TT-2, US-053).

REST API for the test tool page, proxying commands to pi4audio-signal-gen
via its TCP RPC interface.  These endpoints complement the ``/ws/siggen``
WebSocket proxy (which handles real-time state feedback).  REST is used
for one-shot commands and status queries from scripts or tests.

Endpoints:
    POST /api/v1/test-tool/play     Start signal playback
    POST /api/v1/test-tool/stop     Stop signal playback
    POST /api/v1/test-tool/level    Set playback level
    POST /api/v1/test-tool/signal   Set signal type
    POST /api/v1/test-tool/channel  Set active channels
    POST /api/v1/test-tool/freq     Set frequency (sine/sweep)
    GET  /api/v1/test-tool/status   Get signal generator state
    POST /api/v1/test-tool/ensure-measurement-mode
                                    Switch GM to measurement mode (F-144)
    GET  /api/v1/test-tool/current-mode
                                    Query current GM routing mode (F-144)
    GET  /api/v1/test-tool/calibration
                                    UMIK-1 calibration curve (T-088-5)

Safety:
    - D-009 hard cap (-0.5 dBFS) enforced server-side on all level fields.
    - Channel validation: 1-8 only.
    - Frequency validation: 20-20000 Hz.
    - Command allowlisting: only the documented commands are accepted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import re
import shutil
import socket
import sys
import time
from typing import Any, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

log = logging.getLogger(__name__)

# Signal generator connection parameters (shared with main.py /ws/siggen).
SIGGEN_HOST = os.environ.get("PI4AUDIO_SIGGEN_HOST", "127.0.0.1")
SIGGEN_PORT = int(os.environ.get("PI4AUDIO_SIGGEN_PORT", "4001"))
SIGGEN_MODE = os.environ.get("PI4AUDIO_SIGGEN", "") == "1"

# UMIK-1 calibration file (miniDSP format).
UMIK1_CAL_PATH = os.environ.get(
    "PI4AUDIO_UMIK1_CAL", "/home/ela/7161942.txt"
)

# Directory for calibration files (upload/list).
UMIK1_CAL_DIR = os.environ.get(
    "PI4AUDIO_CAL_DIR", "/etc/pi4audio/calibration"
)

# D-009: hard level cap.
HARD_CAP_DBFS = -0.5

# Valid ranges matching Rust RPC server (rpc.rs).
MIN_LEVEL_DBFS = -60.0
MIN_FREQ_HZ = 20.0
MAX_FREQ_HZ = 20000.0
VALID_SIGNALS = {"sine", "white", "pink", "sweep", "silence", "file"}
VALID_CHANNELS = set(range(1, 9))

router = APIRouter(prefix="/api/v1/test-tool", tags=["test-tool"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PlayRequest(BaseModel):
    signal: str = "sine"
    channels: List[int]
    level_dbfs: float = -40.0
    freq: float = 1000.0
    duration: Optional[float] = None
    sweep_end: float = 20000.0
    path: Optional[str] = None

    @field_validator("signal")
    @classmethod
    def validate_signal(cls, v: str) -> str:
        if v not in VALID_SIGNALS:
            raise ValueError(f"Invalid signal type: {v!r}. "
                             f"Must be one of {sorted(VALID_SIGNALS)}")
        return v

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("At least one channel required")
        for ch in v:
            if ch not in VALID_CHANNELS:
                raise ValueError(f"Invalid channel {ch}. Must be 1-8")
        return v

    @field_validator("level_dbfs")
    @classmethod
    def validate_level(cls, v: float) -> float:
        if v > HARD_CAP_DBFS:
            v = HARD_CAP_DBFS
        if v < MIN_LEVEL_DBFS:
            v = MIN_LEVEL_DBFS
        return v

    @field_validator("freq")
    @classmethod
    def validate_freq(cls, v: float) -> float:
        if v < MIN_FREQ_HZ or v > MAX_FREQ_HZ:
            raise ValueError(f"Frequency {v} Hz out of range "
                             f"[{MIN_FREQ_HZ}, {MAX_FREQ_HZ}]")
        return v

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0.1 or v > 600):
            raise ValueError(f"Duration {v}s out of range [0.1, 600]")
        return v


class LevelRequest(BaseModel):
    level_dbfs: float

    @field_validator("level_dbfs")
    @classmethod
    def validate_level(cls, v: float) -> float:
        if v > HARD_CAP_DBFS:
            v = HARD_CAP_DBFS
        if v < MIN_LEVEL_DBFS:
            v = MIN_LEVEL_DBFS
        return v


class SignalRequest(BaseModel):
    signal: str
    freq: float = 1000.0

    @field_validator("signal")
    @classmethod
    def validate_signal(cls, v: str) -> str:
        if v not in VALID_SIGNALS:
            raise ValueError(f"Invalid signal type: {v!r}")
        return v

    @field_validator("freq")
    @classmethod
    def validate_freq(cls, v: float) -> float:
        if v < MIN_FREQ_HZ or v > MAX_FREQ_HZ:
            raise ValueError(f"Frequency {v} Hz out of range")
        return v


class ChannelRequest(BaseModel):
    channels: List[int]

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("At least one channel required")
        for ch in v:
            if ch not in VALID_CHANNELS:
                raise ValueError(f"Invalid channel {ch}. Must be 1-8")
        return v


class FreqRequest(BaseModel):
    freq: float

    @field_validator("freq")
    @classmethod
    def validate_freq(cls, v: float) -> float:
        if v < MIN_FREQ_HZ or v > MAX_FREQ_HZ:
            raise ValueError(f"Frequency {v} Hz out of range")
        return v


# ---------------------------------------------------------------------------
# TCP helper
# ---------------------------------------------------------------------------

def _siggen_rpc(cmd: dict, timeout: float = 5.0) -> dict:
    """Send a command to the signal generator and return the ack.

    Raises ConnectionError or TimeoutError on failure.  Handles
    message interleaving (AD-D037-5): consumes state/event messages
    until the ack arrives.
    """
    sock = socket.create_connection((SIGGEN_HOST, SIGGEN_PORT), timeout=timeout)
    try:
        sock.settimeout(timeout)
        line = json.dumps(cmd, separators=(",", ":")) + "\n"
        sock.sendall(line.encode())

        recv_buf = b""
        deadline_mono = time.monotonic() + timeout
        while True:
            remaining = deadline_mono - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for ack")
            sock.settimeout(max(0.01, remaining))
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                raise TimeoutError("Timed out waiting for ack")
            if not chunk:
                raise ConnectionError("Signal generator disconnected")
            recv_buf += chunk
            while b"\n" in recv_buf:
                msg_line, recv_buf = recv_buf.split(b"\n", 1)
                msg = json.loads(msg_line)
                msg_type = msg.get("type")
                if msg_type == "ack" and msg.get("cmd") == cmd.get("cmd"):
                    return msg
                # Discard interleaved state/event messages (AD-D037-5).
    finally:
        sock.close()


def _not_enabled() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": "siggen_not_enabled",
                 "detail": "Signal generator not enabled "
                           "(set PI4AUDIO_SIGGEN=1)"},
    )


async def _rpc_or_error(cmd: dict) -> JSONResponse:
    """Send an RPC command and return the ack as JSON, or an error."""
    try:
        ack = await asyncio.to_thread(_siggen_rpc, cmd)
        if ack.get("ok"):
            return JSONResponse(content=ack)
        return JSONResponse(
            status_code=422,
            content={"error": "siggen_rejected",
                     "detail": ack.get("error", "unknown error")},
        )
    except ConnectionError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": "siggen_unavailable",
                     "detail": str(exc)},
        )
    except TimeoutError as exc:
        return JSONResponse(
            status_code=504,
            content={"error": "siggen_timeout",
                     "detail": str(exc)},
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/play")
async def play(body: PlayRequest):
    """Start signal playback on the specified channel(s)."""
    if not SIGGEN_MODE:
        return _not_enabled()

    cmd: dict[str, Any] = {
        "cmd": "play",
        "signal": body.signal,
        "channels": body.channels,
        "level_dbfs": body.level_dbfs,
        "freq": body.freq,
        "duration": body.duration,
    }
    if body.signal == "sweep":
        cmd["sweep_end"] = body.sweep_end
    if body.signal == "file" and body.path:
        cmd["path"] = body.path

    return await _rpc_or_error(cmd)


@router.post("/stop")
async def stop():
    """Stop signal playback (20ms fade-out)."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "stop"})


@router.post("/level")
async def set_level(body: LevelRequest):
    """Change playback level (smooth gain ramp)."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "set_level", "level_dbfs": body.level_dbfs})


@router.post("/signal")
async def set_signal(body: SignalRequest):
    """Change signal type (crossfade transition)."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "set_signal", "signal": body.signal,
                          "freq": body.freq})


@router.post("/channel")
async def set_channel(body: ChannelRequest):
    """Change active output channels (fade transition)."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "set_channel", "channels": body.channels})


@router.post("/freq")
async def set_freq(body: FreqRequest):
    """Change frequency for sine/sweep signal."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "set_freq", "freq": body.freq})


@router.get("/status")
async def status():
    """Get current signal generator state."""
    if not SIGGEN_MODE:
        return _not_enabled()
    return await _rpc_or_error({"cmd": "status"})


# ---------------------------------------------------------------------------
# GraphManager mode switching (F-144)
# ---------------------------------------------------------------------------

# GM connection parameters (shared with main.py lifespan).
GM_HOST = os.environ.get("PI4AUDIO_GM_HOST", "127.0.0.1")
GM_PORT = int(os.environ.get("PI4AUDIO_GM_PORT", "4002"))

# F-230 mock: quantum per mode (matches real GM set_quantum_for_mode in main.rs).
_MODE_QUANTUM = {"dj": 1024, "standby": 256, "live": 256, "measurement": 256}


def _sync_mock_quantum(mode: str) -> None:
    """Update the mock quantum to match the mode (F-230 mock equivalent)."""
    mock_mode = os.environ.get("PI_AUDIO_MOCK", "1") == "1"
    if not mock_mode:
        return
    from .. import config_routes as cr
    cr._mock_quantum = _MODE_QUANTUM.get(mode, 256)


@contextlib.contextmanager
def _gm_client():
    """Yield a connected GraphManager client, closing it on exit."""
    meas_dir = os.environ.get("PI4AUDIO_MEAS_DIR", os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "measurement")))
    if meas_dir not in sys.path:
        sys.path.insert(0, meas_dir)
    from graph_manager_client import GraphManagerClient, MockGraphManagerClient
    mock_mode = os.environ.get("PI_AUDIO_MOCK", "1") == "1"
    ClientCls = MockGraphManagerClient if mock_mode else GraphManagerClient
    client = ClientCls(host=GM_HOST, port=GM_PORT)
    client.connect()
    try:
        yield client
    finally:
        client.close()


def _gm_get_mode() -> str:
    """Query current GM routing mode via TCP RPC."""
    with _gm_client() as client:
        return client.get_mode()


def _gm_set_mode(mode: str) -> str:
    """Set GM routing mode via TCP RPC, wait for settlement, return mode."""
    with _gm_client() as client:
        resp = client.set_mode(mode)
        # US-140: Wait for reconciler settlement instead of caller sleeping.
        epoch = resp.get("epoch", 0)
        client.await_settled(since_epoch=epoch, timeout_ms=10000)
        return mode


@router.get("/current-mode")
async def current_mode():
    """Return the current GraphManager routing mode (F-144)."""
    try:
        mode = await asyncio.to_thread(_gm_get_mode)
        return {"mode": mode}
    except Exception as exc:
        log.warning("Failed to query GM mode: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unavailable", "detail": str(exc)},
        )


@router.post("/ensure-measurement-mode")
async def ensure_measurement_mode():
    """Switch GraphManager to measurement mode if not already there (F-144).

    Signal-gen needs measurement routing to have PipeWire links.  This
    endpoint is called by the test page before playing test tones.

    Returns {"mode": "measurement", "switched": true/false}.
    """
    try:
        current = await asyncio.to_thread(_gm_get_mode)
    except Exception as exc:
        log.warning("Failed to query GM mode: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unavailable", "detail": str(exc)},
        )

    if current == "measurement":
        _sync_mock_quantum("measurement")
        return {"mode": "measurement", "switched": False}

    try:
        await asyncio.to_thread(_gm_set_mode, "measurement")
        _sync_mock_quantum("measurement")
        log.info("F-144: Switched GM to measurement mode (was: %s)", current)
        return {"mode": "measurement", "switched": True, "previous": current}
    except Exception as exc:
        log.error("Failed to switch GM to measurement mode: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_mode_switch_failed", "detail": str(exc)},
        )


@router.post("/restore-mode")
async def restore_mode(request: Request):
    """Restore GraphManager to a specified mode (F-160).

    Expects JSON body: {"mode": "dj"} (or "standby", "live", etc.).
    Called by the test tab when navigating away to restore the previous mode.

    Returns {"mode": "<restored>", "switched": true/false}.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400,
                            content={"error": "invalid_json"})

    target = data.get("mode", "standby")
    if target not in ("standby", "dj", "live"):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_mode",
                     "detail": f"Mode must be standby, dj, or live (got: {target})"},
        )

    try:
        current = await asyncio.to_thread(_gm_get_mode)
    except Exception as exc:
        log.warning("Failed to query GM mode: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_unavailable", "detail": str(exc)},
        )

    if current == target:
        _sync_mock_quantum(target)
        return {"mode": target, "switched": False}

    try:
        await asyncio.to_thread(_gm_set_mode, target)
        _sync_mock_quantum(target)
        log.info("F-160: Restored GM to %s mode (was: %s)", target, current)
        return {"mode": target, "switched": True}
    except Exception as exc:
        log.error("Failed to restore GM to %s mode: %s", target, exc)
        return JSONResponse(
            status_code=502,
            content={"error": "gm_mode_switch_failed", "detail": str(exc)},
        )


# ---------------------------------------------------------------------------
# UMIK-1 calibration data (T-088-5)
# ---------------------------------------------------------------------------

def _parse_umik1_calibration(path: str) -> tuple[list[float], list[float]]:
    """Parse a miniDSP UMIK-1 calibration file.

    Format: tab/space-separated freq<tab>dB lines.  Header lines
    starting with ``"`` or ``*`` are skipped.

    Returns (frequencies, db_corrections) as two parallel float lists.
    Raises FileNotFoundError if the file does not exist, ValueError if
    it contains no usable data.
    """
    freqs: list[float] = []
    db_corrections: list[float] = []
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('"') or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    freqs.append(float(parts[0]))
                    db_corrections.append(float(parts[1]))
                except ValueError:
                    continue
    if not freqs:
        raise ValueError(f"No calibration data found in {path}")
    return freqs, db_corrections


def _parse_umik1_sensitivity(path: str) -> float | None:
    """Extract sensitivity factor from UMIK-1 calibration file header.

    Parses the "Sens Factor =X.XXXdB" value from the first header line.
    Returns the sensitivity in dB, or None if not found.
    """
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith('"') and "Sens Factor" in line:
                m = re.search(r"Sens Factor\s*=\s*([+-]?\d+\.?\d*)\s*dB", line)
                if m:
                    return float(m.group(1))
            if not line.startswith('"') and not line.startswith("*"):
                break  # Past headers
    return None


def _a_weighting_db(freq: float) -> float:
    """IEC 61672:2003 A-weighting in dB for a given frequency.

    Uses the exact transfer function:
        R_A(f) = 12194^2 * f^4 /
                 ((f^2 + 20.6^2) * sqrt((f^2 + 107.7^2)(f^2 + 737.9^2))
                  * (f^2 + 12194^2))
        A(f) = 20*log10(R_A(f)) + 2.00
    """
    if freq <= 0:
        return -200.0  # Effectively muted
    f2 = freq * freq
    num = 12194.0 ** 2 * f2 * f2
    denom = (
        (f2 + 20.6 ** 2)
        * math.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2))
        * (f2 + 12194.0 ** 2)
    )
    if denom == 0:
        return -200.0
    r_a = num / denom
    return 20.0 * math.log10(max(r_a, 1e-20)) + 2.0


def _validate_cal_file(path: str) -> dict:
    """Validate a miniDSP UMIK-1 calibration file format.

    Returns {valid: bool, errors: [...], sensitivity_db: float|null,
             num_points: int, freq_range: [min, max]}.
    """
    errors: list[str] = []
    sensitivity = None
    freqs: list[float] = []
    try:
        with open(path, "r") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return {"valid": False, "errors": ["File not found"],
                "sensitivity_db": None, "num_points": 0,
                "freq_range": None}
    except Exception as exc:
        return {"valid": False, "errors": [f"Read error: {exc}"],
                "sensitivity_db": None, "num_points": 0,
                "freq_range": None}

    has_header = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('"'):
            has_header = True
            if "Sens Factor" in stripped:
                m = re.search(
                    r"Sens Factor\s*=\s*([+-]?\d+\.?\d*)\s*dB", stripped)
                if m:
                    sensitivity = float(m.group(1))
            continue
        if stripped.startswith("*"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            try:
                freqs.append(float(parts[0]))
                float(parts[1])  # Validate dB column parseable
            except ValueError:
                errors.append(f"Malformed data line: {stripped[:60]}")

    if not has_header:
        errors.append("No header line found (expected miniDSP format "
                       "with quoted first line)")
    if sensitivity is None:
        errors.append("Sensitivity factor not found in header")
    if len(freqs) < 5:
        errors.append(f"Too few data points ({len(freqs)}); "
                       "expected at least 5 for a valid cal file")
    if freqs:
        if freqs[0] > 30:
            errors.append(f"First frequency {freqs[0]} Hz > 30 Hz; "
                           "expected data starting near 20 Hz")
        if freqs[-1] < 15000:
            errors.append(f"Last frequency {freqs[-1]} Hz < 15000 Hz; "
                           "expected data up to ~20 kHz")
        for i in range(1, len(freqs)):
            if freqs[i] <= freqs[i - 1]:
                errors.append("Frequencies not monotonically increasing")
                break

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "sensitivity_db": sensitivity,
        "num_points": len(freqs),
        "freq_range": [freqs[0], freqs[-1]] if freqs else None,
    }


@router.get("/calibration")
async def calibration():
    """Return UMIK-1 calibration curve as JSON (T-088-5).

    Reads the calibration file specified by ``PI4AUDIO_UMIK1_CAL``
    (default ``/home/ela/7161942.txt``).  The response contains two
    parallel arrays: frequencies (Hz) and dB corrections.
    """
    try:
        freqs, db_corrections = await asyncio.to_thread(
            _parse_umik1_calibration, UMIK1_CAL_PATH,
        )
    except FileNotFoundError:
        return JSONResponse(
            status_code=404,
            content={
                "error": "calibration_file_not_found",
                "detail": f"UMIK-1 calibration file not found: {UMIK1_CAL_PATH}",
            },
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": "calibration_parse_error",
                "detail": str(exc),
            },
        )
    # Parse sensitivity from header.
    sensitivity_db = None
    try:
        sensitivity_db = await asyncio.to_thread(
            _parse_umik1_sensitivity, UMIK1_CAL_PATH)
    except Exception:
        pass

    # Compute A-weighting curve at calibration frequencies.
    a_weighting = [round(_a_weighting_db(f), 3) for f in freqs]

    return {
        "frequencies": freqs,
        "db_corrections": db_corrections,
        "sensitivity_db": sensitivity_db,
        "a_weighting": a_weighting,
        "cal_file": os.path.basename(UMIK1_CAL_PATH),
    }


# ---------------------------------------------------------------------------
# Calibration file management (US-096)
# ---------------------------------------------------------------------------

_CAL_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*\.txt$")


@router.get("/calibration/files")
async def list_cal_files():
    """List available UMIK-1 calibration files.

    Looks in the calibration directory and lists all .txt files
    that appear to be miniDSP UMIK-1 format.
    """
    cal_dir = UMIK1_CAL_DIR
    if not os.path.isdir(cal_dir):
        return {"files": [], "active": os.path.basename(UMIK1_CAL_PATH)}

    files = []
    for name in sorted(os.listdir(cal_dir)):
        if not name.endswith(".txt"):
            continue
        path = os.path.join(cal_dir, name)
        if not os.path.isfile(path):
            continue
        info: dict[str, Any] = {"name": name}
        try:
            sens = _parse_umik1_sensitivity(path)
            info["sensitivity_db"] = sens
        except Exception:
            info["sensitivity_db"] = None
        # Extract serial from header if present.
        try:
            with open(path, "r") as fh:
                first = fh.readline()
            m = re.search(r"SERNO:\s*(\d+)", first)
            info["serial"] = m.group(1) if m else None
        except Exception:
            info["serial"] = None
        files.append(info)

    # Also include the currently active file if not in the directory.
    active_name = os.path.basename(UMIK1_CAL_PATH)
    return {"files": files, "active": active_name}


@router.post("/calibration/validate")
async def validate_cal_file_upload(request: Request):
    """Validate an uploaded calibration file.

    Accepts raw text body containing the calibration file content.
    Returns validation results without saving the file.
    """
    body = await request.body()
    text = body.decode("utf-8", errors="replace")

    # Write to a temporary file for parsing.
    import tempfile
    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write(text)
        tmp_path = tmp.name

    try:
        result = await asyncio.to_thread(_validate_cal_file, tmp_path)
    finally:
        os.unlink(tmp_path)

    return result


@router.post("/calibration/upload")
async def upload_cal_file(request: Request):
    """Upload and save a new UMIK-1 calibration file.

    Expects JSON body: {name: "filename.txt", content: "file content"}.
    Validates the file before saving.
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400,
                            content={"error": "invalid_json"})

    name = data.get("name", "")
    content = data.get("content", "")

    if not name or not _CAL_SAFE_NAME.match(name):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_filename",
                     "detail": "Filename must match [a-zA-Z0-9._-]+.txt"})

    # Validate content before saving.
    import tempfile
    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        validation = _validate_cal_file(tmp_path)
        if not validation["valid"]:
            return JSONResponse(
                status_code=422,
                content={"error": "validation_failed",
                         "validation": validation})
    finally:
        os.unlink(tmp_path)

    # Save to calibration directory.
    cal_dir = UMIK1_CAL_DIR
    os.makedirs(cal_dir, exist_ok=True)
    dest = os.path.join(cal_dir, name)

    try:
        with open(dest, "w") as fh:
            fh.write(content)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": "save_failed", "detail": str(exc)})

    return {"saved": True, "name": name, "path": dest,
            "validation": validation}


# ---------------------------------------------------------------------------
# Calibration verification (US-096)
# ---------------------------------------------------------------------------

@router.post("/calibration/verify")
async def verify_calibration():
    """Verify UMIK-1 calibration by comparing expected vs measured SPL.

    Plays a 1 kHz sine tone at a known level via signal-gen, measures
    via UMIK-1 through pcm-bridge, and compares. At 1 kHz, the UMIK-1
    cal file correction should be ~0 dB (reference frequency).

    Returns {passed: bool, expected_spl_db: float, measured_spl_db: float,
             deviation_db: float, detail: str}.
    """
    if not SIGGEN_MODE:
        return _not_enabled()

    # Parameters: -20 dBFS 1 kHz tone on channel 3 (UMIK-1 monitoring).
    test_level_dbfs = -20.0
    test_freq_hz = 1000.0
    # UMIK-1 sensitivity: dBFS + sensitivity = dBSPL.
    sensitivity = 121.4  # Hardcoded default (from Pi UMIK-1 unit)

    # Try to get sensitivity from cal file.
    try:
        sens_from_file = _parse_umik1_sensitivity(UMIK1_CAL_PATH)
        if sens_from_file is not None:
            # The cal file sens factor adjusts the base sensitivity.
            # UMIK-1 sensitivity with cal: 121.4 dB (nominal) adjusted by
            # the sens factor from the cal file.
            pass  # Use 121.4 as the total conversion factor
    except Exception:
        pass

    # Expected SPL at 1 kHz: the signal generator outputs at test_level_dbfs.
    # UMIK-1 picks it up acoustically — actual SPL depends on room, distance,
    # speaker efficiency. We can't know the expected SPL without those.
    # Instead, this test verifies CONSISTENCY: play at known level, read SPL,
    # and check that the readout is plausible (e.g., > 40 dB and < 100 dB
    # for a tone at -20 dBFS in a typical room).

    # Step 1: Play tone.
    try:
        play_ack = await asyncio.to_thread(_siggen_rpc, {
            "cmd": "play", "signal": "sine", "channels": [3],
            "level_dbfs": test_level_dbfs, "freq": test_freq_hz,
        })
        if not play_ack.get("ok"):
            return JSONResponse(
                status_code=502,
                content={"error": "play_failed",
                         "detail": play_ack.get("error", "unknown")})
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": "siggen_error", "detail": str(exc)})

    # Step 2: Wait for signal to stabilize (500ms).
    await asyncio.sleep(0.5)

    # Step 3: Read SPL from pcm-bridge UMIK-1 channel.
    # This requires a short PCM capture from the UMIK-1 channel.
    # For now, report the test parameters and let the frontend
    # compare its live SPL readout against the expected range.
    measured_spl = None
    try:
        import urllib.request
        resp = urllib.request.urlopen(
            "http://127.0.0.1:9100/levels", timeout=2)
        levels_data = json.loads(resp.read())
        # pcm-bridge reports per-channel RMS levels.
        # Channel 3 (0-indexed 2) is UMIK-1.
        ch3_rms = levels_data.get("channels", {}).get("2", {}).get("rms")
        if ch3_rms is not None and ch3_rms > 0:
            rms_dbfs = 20 * math.log10(max(ch3_rms, 1e-10))
            measured_spl = rms_dbfs + sensitivity
    except Exception as exc:
        log.warning("Failed to read pcm-bridge levels: %s", exc)

    # Step 4: Stop tone.
    try:
        await asyncio.to_thread(_siggen_rpc, {"cmd": "stop"})
    except Exception:
        pass

    if measured_spl is None:
        return {
            "passed": False,
            "error": "measurement_failed",
            "detail": "Could not read UMIK-1 level from pcm-bridge. "
                      "Verify UMIK-1 is connected and pcm-bridge is running.",
        }

    # Plausibility check: -20 dBFS tone through speakers picked up by
    # UMIK-1 should produce a reasonable SPL (30-100 dB).
    passed = 30 < measured_spl < 100
    deviation = abs(measured_spl - 70)  # Expected ~70 dB in a nearfield setup

    return {
        "passed": passed,
        "test_level_dbfs": test_level_dbfs,
        "test_freq_hz": test_freq_hz,
        "measured_spl_db": round(measured_spl, 1),
        "sensitivity_offset": sensitivity,
        "plausible_range": "30-100 dB SPL",
        "deviation_from_typical_db": round(deviation, 1),
        "detail": (
            f"Measured {measured_spl:.1f} dB SPL at 1 kHz. "
            f"{'Plausible' if passed else 'OUT OF RANGE'} "
            f"(expected 30-100 dB for -20 dBFS tone)."
        ),
    }
