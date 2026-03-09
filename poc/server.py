"""
Web UI PoC – FastAPI server for Pi4 audio workstation.

Bridges JACK audio (3 monitor channels) and CamillaDSP levels
to browser clients over WebSocket.

Run: uvicorn server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import logging
import struct
from contextlib import asynccontextmanager
from pathlib import Path

import jack
import numpy as np
from camilladsp import CamillaClient
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("webui-poc")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAMPLE_RATE = 48000
QUANTUM = 256
NUM_CHANNELS = 3
RING_FRAMES = 8192  # must be power-of-2 for simple wraparound
CDSP_HOST = "127.0.0.1"
CDSP_PORT = 1234
PCM_SEND_INTERVAL = QUANTUM / SAMPLE_RATE  # ~5.33 ms
LEVELS_POLL_INTERVAL = 0.1  # 100 ms

# ---------------------------------------------------------------------------
# Ring buffer – single-producer (JACK callback) / single-consumer (WS task)
# Pre-allocated numpy arrays; the callback only does C-level memcpy via
# numpy slice assignment.  write_pos is bumped atomically (Python GIL).
# ---------------------------------------------------------------------------
ring_buf = np.zeros((RING_FRAMES, NUM_CHANNELS), dtype=np.float32)
write_pos: int = 0  # updated only in JACK callback
read_pos: int = 0   # updated only in consumer task

# ---------------------------------------------------------------------------
# JACK client setup
# ---------------------------------------------------------------------------
jack_client: jack.Client | None = None


def _jack_process(frames: int) -> None:
    """JACK process callback – RT-safe, no Python allocation."""
    global write_pos
    if jack_client is None:
        return
    # frames == QUANTUM (256) in normal operation
    for ch in range(NUM_CHANNELS):
        buf = jack_client.inports[ch].get_array()  # float32 numpy view
        start = write_pos % RING_FRAMES
        end = start + frames
        if end <= RING_FRAMES:
            ring_buf[start:end, ch] = buf[:frames]
        else:
            first = RING_FRAMES - start
            ring_buf[start:RING_FRAMES, ch] = buf[:first]
            ring_buf[0:frames - first, ch] = buf[first:frames]
    write_pos += frames


def _start_jack() -> jack.Client:
    """Create JACK client, register ports, connect to Loopback monitors."""
    global jack_client, write_pos, read_pos
    write_pos = 0
    read_pos = 0

    client = jack.Client("webui-poc")
    client.set_process_callback(_jack_process)

    for i in range(NUM_CHANNELS):
        client.inports.register(f"input_{i}")

    jack_client = client  # assign BEFORE activate so callback can access it
    client.activate()

    # Discover CamillaDSP monitor ports by pattern
    monitor_ports = client.get_ports("CamillaDSP.*:monitor.*", is_output=True)
    if len(monitor_ports) < NUM_CHANNELS:
        logger.warning(
            "Found only %d CamillaDSP monitor ports (need %d). "
            "Connect manually with jack_connect.",
            len(monitor_ports),
            NUM_CHANNELS,
        )
    for i, port in enumerate(monitor_ports[:NUM_CHANNELS]):
        client.connect(port, client.inports[i])
        logger.info("Connected %s -> %s", port.name, client.inports[i].name)
    logger.info("JACK client started: %s (%d ports)", client.name, NUM_CHANNELS)
    return client


def _stop_jack() -> None:
    global jack_client
    if jack_client is not None:
        jack_client.deactivate()
        jack_client.close()
        jack_client = None
        logger.info("JACK client stopped")


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    _start_jack()
    yield
    _stop_jack()


app = FastAPI(lifespan=lifespan)

# ---------------------------------------------------------------------------
# WebSocket: PCM binary stream
# ---------------------------------------------------------------------------
HEADER_STRUCT = struct.Struct("<I")  # 4-byte LE uint32 frame count


@app.websocket("/ws/pcm")
async def ws_pcm(ws: WebSocket) -> None:
    global read_pos
    await ws.accept()
    logger.info("PCM client connected")
    try:
        while True:
            # Wait until at least QUANTUM frames are available
            available = write_pos - read_pos
            if available < QUANTUM:
                await asyncio.sleep(PCM_SEND_INTERVAL / 2)
                continue

            # Read QUANTUM frames from ring buffer
            start = read_pos % RING_FRAMES
            end = start + QUANTUM
            if end <= RING_FRAMES:
                chunk = ring_buf[start:end, :].copy()
            else:
                first = RING_FRAMES - start
                chunk = np.empty((QUANTUM, NUM_CHANNELS), dtype=np.float32)
                chunk[:first, :] = ring_buf[start:RING_FRAMES, :]
                chunk[first:, :] = ring_buf[0:QUANTUM - first, :]
            read_pos += QUANTUM

            # Build binary message: header (frame count) + interleaved float32
            header = HEADER_STRUCT.pack(QUANTUM)
            await ws.send_bytes(header + chunk.tobytes())
            await asyncio.sleep(PCM_SEND_INTERVAL)
    except WebSocketDisconnect:
        logger.info("PCM client disconnected")
    except Exception:
        logger.exception("PCM websocket error")


# ---------------------------------------------------------------------------
# WebSocket: CamillaDSP levels
# ---------------------------------------------------------------------------
@app.websocket("/ws/levels")
async def ws_levels(ws: WebSocket) -> None:
    await ws.accept()
    logger.info("Levels client connected")

    cdsp: CamillaClient | None = None

    try:
        while True:
            # (Re)connect to CamillaDSP if needed
            if cdsp is None:
                try:
                    cdsp = CamillaClient(CDSP_HOST, CDSP_PORT)
                    cdsp.connect()
                    logger.info("Connected to CamillaDSP at %s:%d", CDSP_HOST, CDSP_PORT)
                except Exception:
                    logger.warning(
                        "CamillaDSP not reachable at %s:%d – retrying in 2s",
                        CDSP_HOST,
                        CDSP_PORT,
                    )
                    cdsp = None
                    await asyncio.sleep(2)
                    continue

            try:
                levels = cdsp.levels.levels_since_last()
                payload = {
                    "capture_rms": levels["capture_rms"],
                    "capture_peak": levels["capture_peak"],
                    "playback_rms": levels["playback_rms"],
                    "playback_peak": levels["playback_peak"],
                }
                await ws.send_json(payload)
            except Exception as e:
                logger.warning("CamillaDSP read failed (%s: %s) – reconnecting", type(e).__name__, e)
                try:
                    cdsp.disconnect()
                except Exception:
                    pass
                cdsp = None
                await asyncio.sleep(2)
                continue

            await asyncio.sleep(LEVELS_POLL_INTERVAL)
    except WebSocketDisconnect:
        logger.info("Levels client disconnected")
    except Exception:
        logger.exception("Levels websocket error")
    finally:
        if cdsp is not None:
            try:
                cdsp.disconnect()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Static files (must be mounted last so it doesn't shadow WS routes)
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
