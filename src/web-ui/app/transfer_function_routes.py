"""WebSocket endpoint and coordinator for real-time transfer function (US-120).

Architecture (per Architect consultation):
- PcmStreamReader (collectors/pcm_reader.py) reads raw PCM from pcm-bridge TCP
- TransferFunctionCoordinator pulls aligned blocks from both readers, feeds the
  engine, and publishes results to a shared slot
- WebSocket handler awaits new results and pushes JSON frames to clients
- Coordinator starts on first client connect, stops on last disconnect

The computation engine (transfer_function.py) is pure numpy -- no I/O, no async.
This module wires the I/O to the engine.

PCM source configuration via PI4AUDIO_PCM_SOURCES env var (same as /ws/pcm):
    {"monitor":"tcp:127.0.0.1:9090","capture-usb":"tcp:127.0.0.1:9091"}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect, Query

from .collectors.pcm_reader import PcmStreamReader
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

# Display push rate (~8 Hz, decoupled from computation rate per Architect).
_PUSH_INTERVAL = 0.125

# How often to recompute delay (seconds). Delay is slow-moving.
_DELAY_RECOMPUTE_INTERVAL = 2.0


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


class TransferFunctionCoordinator:
    """Coordinates PCM readers, engine, and delay finder.

    Lifecycle tied to client count: starts on first client, stops when
    the last client disconnects. Multiple WebSocket clients share the
    same coordinator and see the same data.
    """

    def __init__(
        self,
        ref_addr: tuple[str, int],
        meas_addr: tuple[str, int],
        num_channels: int,
        ref_channel: int,
        meas_channel: int,
        fft_size: int = 4096,
        alpha: float = 0.125,
    ) -> None:
        self._ref_addr = ref_addr
        self._meas_addr = meas_addr
        self._num_channels = num_channels

        cfg = TransferFunctionConfig(fft_size=fft_size, alpha=alpha)
        self.engine = TransferFunctionEngine(cfg)
        self.delay_finder = DelayFinder()

        self._ref_queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._meas_queue: asyncio.Queue = asyncio.Queue(maxsize=64)

        self._ref_reader = PcmStreamReader(
            ref_addr[0], ref_addr[1], num_channels, ref_channel,
            self._ref_queue, name="tf-ref")
        self._meas_reader = PcmStreamReader(
            meas_addr[0], meas_addr[1], num_channels, meas_channel,
            self._meas_queue, name="tf-meas")

        # Latest result, updated by the computation task.
        self._latest_result: Optional[dict] = None
        self._new_data = asyncio.Event()

        self._compute_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def latest_result(self) -> Optional[dict]:
        return self._latest_result

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self._ref_reader.start()
        await self._meas_reader.start()
        self._compute_task = asyncio.create_task(
            self._compute_loop(), name="tf-coordinator")
        log.info("TransferFunctionCoordinator started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._compute_task is not None:
            self._compute_task.cancel()
            try:
                await self._compute_task
            except asyncio.CancelledError:
                pass
            self._compute_task = None
        await self._ref_reader.stop()
        await self._meas_reader.stop()
        log.info("TransferFunctionCoordinator stopped")

    async def wait_new_data(self, timeout: float = 0.2) -> bool:
        """Wait for new result data from the computation task."""
        try:
            await asyncio.wait_for(self._new_data.wait(), timeout=timeout)
            self._new_data.clear()
            return True
        except asyncio.TimeoutError:
            return False

    async def _compute_loop(self) -> None:
        """Drain PCM queues, feed engine, publish results."""
        last_delay_compute = 0.0

        while True:
            # Drain both queues.
            ref_chunks = []
            meas_chunks = []

            try:
                ref_data = await asyncio.wait_for(
                    self._ref_queue.get(), timeout=0.05)
                ref_chunks.append(ref_data)
            except asyncio.TimeoutError:
                pass

            try:
                meas_data = await asyncio.wait_for(
                    self._meas_queue.get(), timeout=0.05)
                meas_chunks.append(meas_data)
            except asyncio.TimeoutError:
                pass

            # Drain remaining without blocking.
            while not self._ref_queue.empty():
                try:
                    ref_chunks.append(self._ref_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            while not self._meas_queue.empty():
                try:
                    meas_chunks.append(self._meas_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Feed engine with paired data.
            if ref_chunks and meas_chunks:
                ref_block = np.concatenate(ref_chunks)
                meas_block = np.concatenate(meas_chunks)
                min_len = min(len(ref_block), len(meas_block))
                if min_len > 0:
                    ref_block = ref_block[:min_len]
                    meas_block = meas_block[:min_len]
                    self.engine.process_block(ref_block, meas_block)
                    self.delay_finder.accumulate(ref_block, meas_block)

            # Recompute delay periodically.
            now = time.monotonic()
            if now - last_delay_compute >= _DELAY_RECOMPUTE_INTERVAL:
                if self.delay_finder.has_enough_data():
                    delay = await asyncio.to_thread(
                        self.delay_finder.compute_delay)
                    self.engine.delay_samples = delay
                last_delay_compute = now

            # Publish latest result.
            result = self.engine.compute()
            frame = result.to_json_dict()
            frame["delay_ms"] = self.delay_finder.delay_ms
            frame["delay_confidence"] = round(self.delay_finder.confidence, 1)
            frame["ref_connected"] = self._ref_reader.connected
            frame["meas_connected"] = self._meas_reader.connected
            self._latest_result = frame
            self._new_data.set()


# -- Singleton coordinator management --
# One coordinator per app, started/stopped based on client count.

_coordinator: Optional[TransferFunctionCoordinator] = None
_client_count = 0
_coordinator_lock = asyncio.Lock()


async def _acquire_coordinator(
    ref_source: str,
    meas_source: str,
    ref_channel: int,
    meas_channel: int,
    fft_size: int,
    alpha: float,
) -> Optional[TransferFunctionCoordinator]:
    """Get or create the shared coordinator, incrementing client count."""
    global _coordinator, _client_count

    ref_addr = _get_pcm_source(ref_source)
    meas_addr = _get_pcm_source(meas_source)
    if ref_addr is None or meas_addr is None:
        return None

    num_channels = int(os.environ.get("PI4AUDIO_PCM_CHANNELS", "2"))

    async with _coordinator_lock:
        if _coordinator is None or not _coordinator.running:
            _coordinator = TransferFunctionCoordinator(
                ref_addr=ref_addr,
                meas_addr=meas_addr,
                num_channels=num_channels,
                ref_channel=ref_channel,
                meas_channel=meas_channel,
                fft_size=fft_size,
                alpha=alpha,
            )
            await _coordinator.start()
        _client_count += 1
        log.info("TF coordinator: client count -> %d", _client_count)
        return _coordinator


async def _release_coordinator() -> None:
    """Decrement client count; stop coordinator if no clients remain."""
    global _coordinator, _client_count

    async with _coordinator_lock:
        _client_count = max(0, _client_count - 1)
        log.info("TF coordinator: client count -> %d", _client_count)
        if _client_count == 0 and _coordinator is not None:
            await _coordinator.stop()
            _coordinator = None


async def ws_transfer_function(
    ws: WebSocket,
    ref_source: str = Query(_DEFAULT_REF_SOURCE),
    meas_source: str = Query(_DEFAULT_MEAS_SOURCE),
    ref_channel: int = Query(0),
    meas_channel: int = Query(0),
    fft_size: int = Query(4096),
    alpha: float = Query(0.125),
):
    """Push transfer function data (magnitude, phase, coherence) at ~8 Hz.

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

    # Validate parameters.
    if fft_size not in (1024, 2048, 4096, 8192):
        await ws.close(code=4000, reason=f"Invalid fft_size: {fft_size}")
        return
    if not 0 < alpha <= 1:
        await ws.close(code=4000, reason=f"Invalid alpha: {alpha}")
        return

    ref_addr = _get_pcm_source(ref_source)
    meas_addr = _get_pcm_source(meas_source)
    if ref_addr is None or meas_addr is None:
        missing = []
        if ref_addr is None:
            missing.append(f"ref={ref_source!r}")
        if meas_addr is None:
            missing.append(f"meas={meas_source!r}")
        log.warning(
            "TF PCM source(s) not configured (%s) — falling back to "
            "mock mode (synthetic data)", ", ".join(missing))
        await _mock_transfer_function(ws, fft_size, alpha,
                                      mock_fallback=True)
        return

    log.info("Transfer function WS connected: ref=%s[%d] meas=%s[%d] "
             "fft=%d alpha=%.3f",
             ref_source, ref_channel, meas_source, meas_channel,
             fft_size, alpha)

    coordinator = await _acquire_coordinator(
        ref_source, meas_source, ref_channel, meas_channel, fft_size, alpha)
    if coordinator is None:
        await ws.close(code=4004, reason="PCM source not found")
        return

    try:
        await _client_loop(ws, coordinator)
    except WebSocketDisconnect:
        log.info("Transfer function WS disconnected")
    except Exception:
        log.exception("Transfer function WS error")
    finally:
        await _release_coordinator()


async def _client_loop(
    ws: WebSocket,
    coordinator: TransferFunctionCoordinator,
) -> None:
    """Per-client loop: await results from coordinator, push to WS."""

    async def push_loop():
        """Push results at ~8 Hz."""
        while True:
            await coordinator.wait_new_data(timeout=_PUSH_INTERVAL)
            result = coordinator.latest_result
            if result is not None:
                await ws.send_text(json.dumps(result))

    async def client_listener():
        """Handle incoming client commands."""
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            cmd = msg.get("cmd")
            if cmd == "set_alpha":
                new_alpha = msg.get("alpha")
                try:
                    new_alpha = float(new_alpha)
                    if 0 < new_alpha <= 1:
                        coordinator.engine.set_alpha(new_alpha)
                        log.info("TF alpha changed to %.4f", new_alpha)
                except (TypeError, ValueError):
                    pass
            elif cmd == "reset":
                coordinator.engine.reset()
                log.info("TF engine reset by client")
            elif cmd == "stop":
                log.info("TF stop requested by client")
                return  # Exit listener, which tears down the connection.

    push_task = asyncio.create_task(push_loop())
    listener_task = asyncio.create_task(client_listener())

    try:
        done, pending = await asyncio.wait(
            {push_task, listener_task},
            return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        # Re-raise any exception from the completed task.
        for t in done:
            t.result()
    except WebSocketDisconnect:
        raise
    finally:
        for t in (push_task, listener_task):
            if not t.done():
                t.cancel()


async def _mock_transfer_function(
    ws: WebSocket,
    fft_size: int = 4096,
    alpha: float = 0.125,
    mock_fallback: bool = False,
) -> None:
    """Mock mode: generate synthetic transfer function data for UI development.

    Simulates a room with a gentle high-frequency rolloff and some resonances.

    When *mock_fallback* is True, the server was in real mode but fell back
    because required PCM sources are not configured.  Each frame includes
    ``"mock_fallback": true`` so the UI can show a degraded-mode indicator.
    """
    cfg = TransferFunctionConfig(fft_size=fft_size, alpha=alpha)
    engine = TransferFunctionEngine(cfg)

    log.info("Transfer function WS connected (mock, fft=%d)", fft_size)

    np.random.seed(42)

    try:
        while True:
            ref = np.random.randn(cfg.fft_size).astype(np.float64)
            # Measurement = ref with gentle HF rolloff + small noise.
            meas = ref.copy()
            for i in range(1, len(meas)):
                meas[i] = 0.85 * meas[i] + 0.15 * meas[i - 1]
            meas += np.random.randn(cfg.fft_size) * 0.05

            engine.process_block(ref, meas)

            result = engine.compute()
            frame = result.to_json_dict()
            frame["delay_ms"] = 2.5
            frame["delay_confidence"] = 15.0
            frame["ref_connected"] = True
            frame["meas_connected"] = True
            frame["mock_fallback"] = mock_fallback
            await ws.send_text(json.dumps(frame))
            await asyncio.sleep(_PUSH_INTERVAL)

    except WebSocketDisconnect:
        log.info("Transfer function WS disconnected (mock)")
    except Exception:
        log.exception("Transfer function WS error (mock)")
