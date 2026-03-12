"""D-020 Monitoring Web UI — FastAPI application.

Unified SPA serving four views: Monitor, Measure, System, MIDI.
Stage 1 implements Monitor and System; Measure and MIDI are frontend stubs.

WebSocket endpoints:
    /ws/monitoring  — Level meters + CamillaDSP status at ~10 Hz
    /ws/system      — Full system health at ~1 Hz
    /ws/pcm         — Binary PCM stream (3-channel interleaved float32)

Mock mode (PI_AUDIO_MOCK=1):
    Real collectors are not started; MockDataGenerator is used instead.
    This is the default on macOS development machines.

Run from the scripts/web-ui directory:
    pip install fastapi uvicorn
    uvicorn app.main:app --host 0.0.0.0 --port 8080

URL parameters (passed through to WebSocket):
    ?scenario=A   Select mock data scenario (A-E, default A)
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ws_monitoring import ws_monitoring
from .ws_system import ws_system

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"

app = FastAPI(title="Pi Audio Workstation", version="0.1.0")


# -- Lifecycle events --

@app.on_event("startup")
async def startup():
    if MOCK_MODE:
        log.info("Mock mode enabled (PI_AUDIO_MOCK=1) — real collectors not started")
        return

    log.info("Starting real data collectors...")
    from .collectors import (
        CamillaDSPCollector,
        PcmStreamCollector,
        PipeWireCollector,
        SystemCollector,
    )

    app.state.cdsp = CamillaDSPCollector()
    await app.state.cdsp.start()

    app.state.pcm = PcmStreamCollector()
    await app.state.pcm.start()

    app.state.system_collector = SystemCollector()
    await app.state.system_collector.start()

    app.state.pw = PipeWireCollector()
    await app.state.pw.start()

    log.info("All collectors started")


@app.on_event("shutdown")
async def shutdown():
    if MOCK_MODE:
        return

    log.info("Stopping collectors...")
    for name in ("cdsp", "pcm", "system_collector", "pw"):
        collector = getattr(app.state, name, None)
        if collector is not None:
            await collector.stop()
    log.info("All collectors stopped")


# -- Routes --

@app.get("/")
async def index():
    """Serve the SPA shell."""
    return FileResponse(STATIC_DIR / "index.html")


# -- WebSocket endpoints --

app.websocket("/ws/monitoring")(ws_monitoring)
app.websocket("/ws/system")(ws_system)


@app.websocket("/ws/pcm")
async def ws_pcm(ws: WebSocket, scenario: str = "A"):
    """Binary PCM stream: 4-byte LE uint32 header + interleaved float32."""
    await ws.accept()

    if MOCK_MODE:
        from .mock.mock_pcm import mock_pcm_stream
        log.info("PCM client connected (mock, scenario=%s)", scenario)
        await mock_pcm_stream(ws, scenario)
        return

    pcm_collector = getattr(app.state, "pcm", None)
    if pcm_collector is None or not pcm_collector.active:
        await ws.close(code=1008, reason="PCM collector not active")
        return

    log.info("PCM client connected")
    try:
        await pcm_collector.stream_to_client(ws)
    except WebSocketDisconnect:
        log.info("PCM client disconnected")
    except Exception:
        log.exception("PCM websocket error")


# -- Static files (mounted last so explicit routes take priority) --

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
