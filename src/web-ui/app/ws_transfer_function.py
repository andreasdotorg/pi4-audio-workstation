"""WebSocket handler for real-time transfer function measurement (US-120).

Dual-FFT cross-spectrum computation: reads two PCM streams (reference =
post-convolver monitor, measurement = UMIK-1 capture) from pcm-bridge TCP
servers, feeds a TransferFunctionEngine, and pushes magnitude/phase/coherence
results to the browser at ~10 Hz.

Mock mode (PI_AUDIO_MOCK=1): generates synthetic test signals so the UI
can be developed without hardware.

PCM source configuration via PI4AUDIO_PCM_SOURCES env var (same as /ws/pcm):
    {"monitor":"tcp:127.0.0.1:9090","capture-usb":"tcp:127.0.0.1:9091"}

Channel selection (query params on the WebSocket URL):
    ref_channel=0    Channel index in the monitor PCM stream (default 0 = left)
    meas_channel=0   Channel index in the capture PCM stream (default 0 = UMIK-1)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import time
from typing import Optional

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect, Query

from .transfer_function import (
    TransferFunctionConfig,
    TransferFunctionEngine,
    DelayFinder,
)

log = logging.getLogger(__name__)

MOCK_MODE = os.environ.get("PI_AUDIO_MOCK", "1") == "1"

# Default PCM source names for reference and measurement streams.
_DEFAULT_REF_SOURCE = "monitor"
_DEFAULT_MEAS_SOURCE = "capture-usb"

# Wire format v2 header size (bytes).
_V2_HEADER = 24

# Push rate for transfer function results (~10 Hz).
_PUSH_INTERVAL = 0.1

# How often to recompute delay (seconds). Delay is slow-moving.
_DELAY_RECOMPUTE_INTERVAL = 2.0


class PcmStreamReader:
    """Async TCP client that reads PCM frames from pcm-bridge and extracts
    a single channel as float32 numpy arrays.

    Connects to a pcm-bridge TCP server, parses v2 wire format frames,
    deinterleaves the requested channel, and puts numpy arrays into an
    asyncio.Queue for consumption by the transfer function engine.

    Wire format v2:
        [version:1][pad:3][frame_count:4][graph_pos:8][graph_nsec:8][PCM...]
    where PCM is frame_count * num_channels * 4 bytes of interleaved float32.
    """

    def __init__(
        self,
        host: str,
        port: int,
        num_channels: int,
        channel: int,
        queue: asyncio.Queue,
        name: str = "pcm",
    ) -> None:
        self._host = host
        self._port = port
        self._num_channels = num_channels
        self._channel = channel
        self._queue = queue
        self._name = name
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._task = asyncio.create_task(
            self._read_loop(), name=f"pcm-reader-{self._name}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _read_loop(self) -> None:
        """Connect to pcm-bridge and read v2 frames in a loop."""
        backoff = 1.0
        while True:
            reader = None
            writer = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=2.0,
                )
                backoff = 1.0
                log.info("PcmStreamReader[%s] connected to %s:%d",
                         self._name, self._host, self._port)

                buf = bytearray()
                while True:
                    data = await asyncio.wait_for(
                        reader.read(65536), timeout=2.0)
                    if not data:
                        log.warning("PcmStreamReader[%s] connection closed",
                                    self._name)
                        break
                    buf.extend(data)

                    # Extract complete v2 frames.
                    while len(buf) >= _V2_HEADER:
                        version = buf[0]
                        if version != 2:
                            log.warning(
                                "PcmStreamReader[%s] unexpected version %d, "
                                "re-syncing", self._name, version)
                            del buf[:1]
                            continue

                        frame_count = struct.unpack_from("<I", buf, 4)[0]
                        if frame_count > 8192:
                            log.warning(
                                "PcmStreamReader[%s] implausible frame_count "
                                "%d, re-syncing", self._name, frame_count)
                            del buf[:1]
                            continue

                        msg_size = _V2_HEADER + frame_count * self._num_channels * 4
                        if len(buf) < msg_size:
                            break  # Incomplete frame.

                        # Parse interleaved float32 PCM and extract channel.
                        pcm_bytes = bytes(buf[_V2_HEADER:msg_size])
                        del buf[:msg_size]

                        pcm = np.frombuffer(pcm_bytes, dtype=np.float32)
                        pcm = pcm.reshape(-1, self._num_channels)
                        channel_data = pcm[:, self._channel].astype(np.float64)

                        # Non-blocking put — drop oldest if queue is full.
                        try:
                            self._queue.put_nowait(channel_data)
                        except asyncio.QueueFull:
                            try:
                                self._queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            self._queue.put_nowait(channel_data)

            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                log.warning("PcmStreamReader[%s] timeout — reconnecting",
                            self._name)
            except (ConnectionRefusedError, OSError) as exc:
                log.warning("PcmStreamReader[%s] connection error: %s — "
                            "retry in %.1fs", self._name, exc, backoff)
            except Exception:
                log.exception("PcmStreamReader[%s] unexpected error",
                              self._name)
            finally:
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8.0)


def _get_pcm_source(name: str) -> Optional[tuple[str, int]]:
    """Look up a PCM source by name from PI4AUDIO_PCM_SOURCES."""
    raw = os.environ.get("PI4AUDIO_PCM_SOURCES", "")
    if raw:
        try:
            sources = json.loads(raw)
        except json.JSONDecodeError:
            sources = {}
    else:
        sources = {"monitor": "tcp:127.0.0.1:9090"}

    addr_str = sources.get(name)
    if addr_str is None:
        return None

    if addr_str.startswith("tcp:"):
        addr_str = addr_str[4:]
    parts = addr_str.rsplit(":", 1)
    if len(parts) != 2:
        return None
    try:
        return (parts[0], int(parts[1]))
    except ValueError:
        return None


async def ws_transfer_function(
    ws: WebSocket,
    ref_source: str = Query(_DEFAULT_REF_SOURCE),
    meas_source: str = Query(_DEFAULT_MEAS_SOURCE),
    ref_channel: int = Query(0),
    meas_channel: int = Query(0),
    fft_size: int = Query(4096),
    alpha: float = Query(0.125),
):
    """Push transfer function data (magnitude, phase, coherence) at ~10 Hz.

    Query parameters:
        ref_source:   PCM source name for reference (default "monitor")
        meas_source:  PCM source name for measurement (default "capture-usb")
        ref_channel:  Channel index in reference stream (default 0)
        meas_channel: Channel index in measurement stream (default 0)
        fft_size:     FFT size (default 4096)
        alpha:        Exponential averaging alpha (default 0.125)
    """
    await ws.accept()

    if MOCK_MODE:
        await _mock_transfer_function(ws, fft_size, alpha)
        return

    # Validate FFT size.
    if fft_size not in (1024, 2048, 4096, 8192):
        await ws.close(code=4000, reason=f"Invalid fft_size: {fft_size}")
        return

    # Validate alpha.
    if not 0 < alpha <= 1:
        await ws.close(code=4000, reason=f"Invalid alpha: {alpha}")
        return

    # Look up PCM sources.
    ref_addr = _get_pcm_source(ref_source)
    meas_addr = _get_pcm_source(meas_source)

    if ref_addr is None:
        await ws.close(
            code=4004,
            reason=f"Unknown ref PCM source: {ref_source!r}")
        return
    if meas_addr is None:
        await ws.close(
            code=4004,
            reason=f"Unknown meas PCM source: {meas_source!r}")
        return

    num_channels = int(os.environ.get("PI4AUDIO_PCM_CHANNELS", "2"))

    log.info("Transfer function WS connected: ref=%s[%d] meas=%s[%d] "
             "fft=%d alpha=%.3f",
             ref_source, ref_channel, meas_source, meas_channel,
             fft_size, alpha)

    # Create engine and delay finder.
    cfg = TransferFunctionConfig(fft_size=fft_size, alpha=alpha)
    engine = TransferFunctionEngine(cfg)
    delay_finder = DelayFinder()

    # Queues for PCM data from the two streams.
    ref_queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    meas_queue: asyncio.Queue = asyncio.Queue(maxsize=64)

    # Start PCM readers.
    ref_reader = PcmStreamReader(
        ref_addr[0], ref_addr[1], num_channels, ref_channel,
        ref_queue, name=f"ref-{ref_source}")
    meas_reader = PcmStreamReader(
        meas_addr[0], meas_addr[1], num_channels, meas_channel,
        meas_queue, name=f"meas-{meas_source}")

    await ref_reader.start()
    await meas_reader.start()

    try:
        await _engine_loop(ws, engine, delay_finder, ref_queue, meas_queue)
    except WebSocketDisconnect:
        log.info("Transfer function WS disconnected")
    except Exception:
        log.exception("Transfer function WS error")
    finally:
        await ref_reader.stop()
        await meas_reader.stop()


async def _engine_loop(
    ws: WebSocket,
    engine: TransferFunctionEngine,
    delay_finder: DelayFinder,
    ref_queue: asyncio.Queue,
    meas_queue: asyncio.Queue,
) -> None:
    """Main processing loop: drain PCM queues, feed engine, push results."""
    last_push = 0.0
    last_delay_compute = 0.0

    # Listen for client messages (alpha changes, reset) concurrently.
    async def client_listener():
        """Handle incoming client commands."""
        while True:
            try:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                cmd = msg.get("cmd")
                if cmd == "set_alpha":
                    new_alpha = float(msg.get("alpha", 0.125))
                    if 0 < new_alpha <= 1:
                        engine.set_alpha(new_alpha)
                        log.info("TF alpha changed to %.4f", new_alpha)
                elif cmd == "reset":
                    engine.reset()
                    log.info("TF engine reset by client")
                elif cmd == "set_fft_size":
                    # FFT size change requires a full engine rebuild.
                    new_size = int(msg.get("fft_size", 4096))
                    if new_size in (1024, 2048, 4096, 8192):
                        new_cfg = TransferFunctionConfig(
                            fft_size=new_size,
                            alpha=engine.config.alpha,
                            sample_rate=engine.config.sample_rate,
                        )
                        engine.__init__(new_cfg)
                        log.info("TF engine rebuilt with fft_size=%d", new_size)
            except WebSocketDisconnect:
                raise
            except Exception:
                pass  # Ignore malformed messages.

    listener_task = asyncio.create_task(client_listener())

    try:
        while True:
            # Drain both queues and collect all available PCM chunks.
            ref_chunks = []
            meas_chunks = []

            # Wait for at least one chunk from either queue.
            try:
                ref_data = await asyncio.wait_for(ref_queue.get(), timeout=0.05)
                ref_chunks.append(ref_data)
            except asyncio.TimeoutError:
                pass

            try:
                meas_data = await asyncio.wait_for(meas_queue.get(), timeout=0.05)
                meas_chunks.append(meas_data)
            except asyncio.TimeoutError:
                pass

            # Drain remaining available data without blocking.
            while not ref_queue.empty():
                try:
                    ref_chunks.append(ref_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            while not meas_queue.empty():
                try:
                    meas_chunks.append(meas_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Feed engine with paired data.
            if ref_chunks and meas_chunks:
                ref_block = np.concatenate(ref_chunks)
                meas_block = np.concatenate(meas_chunks)
                # Align lengths: use the shorter of the two.
                min_len = min(len(ref_block), len(meas_block))
                if min_len > 0:
                    ref_block = ref_block[:min_len]
                    meas_block = meas_block[:min_len]
                    engine.process_block(ref_block, meas_block)
                    delay_finder.accumulate(ref_block, meas_block)

            # Recompute delay periodically.
            now = time.monotonic()
            if now - last_delay_compute >= _DELAY_RECOMPUTE_INTERVAL:
                if delay_finder.has_enough_data():
                    delay = await asyncio.to_thread(delay_finder.compute_delay)
                    engine.delay_samples = delay
                last_delay_compute = now

            # Push results at ~10 Hz.
            if now - last_push >= _PUSH_INTERVAL:
                result = engine.compute()
                frame = result.to_json_dict()
                frame["delay_ms"] = delay_finder.delay_ms
                frame["delay_confidence"] = round(delay_finder.confidence, 1)
                await ws.send_text(json.dumps(frame))
                last_push = now

    finally:
        listener_task.cancel()
        try:
            await listener_task
        except (asyncio.CancelledError, WebSocketDisconnect):
            pass


async def _mock_transfer_function(
    ws: WebSocket,
    fft_size: int = 4096,
    alpha: float = 0.125,
) -> None:
    """Mock mode: generate synthetic transfer function data for UI development.

    Simulates a room with a gentle high-frequency rolloff and some resonances.
    """
    cfg = TransferFunctionConfig(fft_size=fft_size, alpha=alpha)
    engine = TransferFunctionEngine(cfg)
    freq_axis = cfg.freq_axis()

    log.info("Transfer function WS connected (mock, fft=%d)", fft_size)

    # Generate a synthetic "room response" for mock mode.
    np.random.seed(42)
    block_count = 0

    try:
        while True:
            # Create a reference signal (white noise).
            ref = np.random.randn(cfg.fft_size).astype(np.float64)

            # Create measurement = ref convolved with a simple "room" response.
            # Gentle HF rolloff + a resonance bump around 100Hz.
            meas = ref.copy()
            # Add slight coloration: simple 1-pole LPF for HF rolloff.
            for i in range(1, len(meas)):
                meas[i] = 0.85 * meas[i] + 0.15 * meas[i - 1]
            # Add a small amount of noise to make coherence < 1.0.
            meas += np.random.randn(cfg.fft_size) * 0.05

            engine.process_block(ref, meas)
            block_count += 1

            # Push at ~10 Hz.
            result = engine.compute()
            frame = result.to_json_dict()
            frame["delay_ms"] = 2.5
            frame["delay_confidence"] = 15.0
            await ws.send_text(json.dumps(frame))
            await asyncio.sleep(_PUSH_INTERVAL)

    except WebSocketDisconnect:
        log.info("Transfer function WS disconnected (mock)")
    except Exception:
        log.exception("Transfer function WS error (mock)")
