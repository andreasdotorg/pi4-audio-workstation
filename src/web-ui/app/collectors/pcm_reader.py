"""Raw PCM stream reader for pcm-bridge TCP servers (US-120).

Connects to a pcm-bridge TCP server, parses v2 wire format frames,
extracts a single channel as float64 numpy arrays, and delivers them
via an asyncio.Queue.

Wire format v2 (from pcm-bridge server.rs):
    [version:1][pad:3][frame_count:4_LE][graph_pos:8_LE][graph_nsec:8_LE][PCM...]
where PCM is frame_count * num_channels * 4 bytes of interleaved float32.

Connection lifecycle mirrors LevelsCollector: connect on startup, exponential
backoff on disconnect, graceful degradation when pcm-bridge is unreachable.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# Wire format v2 header size (bytes).
V2_HEADER_SIZE = 24

_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0
_BACKOFF_CAP = 8.0


class PcmStreamReader:
    """Async TCP client that reads PCM frames from pcm-bridge and extracts
    a single channel as float64 numpy arrays.

    Parameters
    ----------
    host : str
        pcm-bridge TCP host.
    port : int
        pcm-bridge TCP port.
    num_channels : int
        Number of interleaved channels in the PCM stream.
    channel : int
        Zero-based channel index to extract.
    queue : asyncio.Queue
        Output queue for extracted channel data (numpy float64 arrays).
    name : str
        Human-readable name for logging.
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
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        self._task = asyncio.create_task(
            self._read_loop(), name=f"pcm-reader-{self._name}")
        log.info("PcmStreamReader[%s] started (target %s:%d ch%d/%d)",
                 self._name, self._host, self._port,
                 self._channel, self._num_channels)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._connected = False
        log.info("PcmStreamReader[%s] stopped", self._name)

    async def _read_loop(self) -> None:
        """Connect to pcm-bridge and read v2 frames in a loop."""
        backoff = _BACKOFF_BASE
        while True:
            writer = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=2.0,
                )
                backoff = _BACKOFF_BASE
                self._connected = True
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
                    self._extract_frames(buf)

            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                log.warning("PcmStreamReader[%s] timeout -- reconnecting",
                            self._name)
            except (ConnectionRefusedError, OSError) as exc:
                log.warning("PcmStreamReader[%s] connection error: %s -- "
                            "retry in %.1fs", self._name, exc, backoff)
            except Exception:
                log.exception("PcmStreamReader[%s] unexpected error",
                              self._name)
            finally:
                self._connected = False
                if writer is not None:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

            await asyncio.sleep(backoff)
            backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_CAP)

    def _extract_frames(self, buf: bytearray) -> None:
        """Extract complete v2 frames from the buffer and enqueue channel data."""
        while len(buf) >= V2_HEADER_SIZE:
            version = buf[0]
            if version != 2:
                log.warning(
                    "PcmStreamReader[%s] unexpected version %d, re-syncing",
                    self._name, version)
                del buf[:1]
                continue

            frame_count = struct.unpack_from("<I", buf, 4)[0]
            if frame_count > 8192:
                log.warning(
                    "PcmStreamReader[%s] implausible frame_count %d, "
                    "re-syncing", self._name, frame_count)
                del buf[:1]
                continue

            msg_size = V2_HEADER_SIZE + frame_count * self._num_channels * 4
            if len(buf) < msg_size:
                break  # Incomplete frame.

            # Parse interleaved float32 PCM and extract channel.
            pcm_bytes = bytes(buf[V2_HEADER_SIZE:msg_size])
            del buf[:msg_size]

            pcm = np.frombuffer(pcm_bytes, dtype=np.float32)
            pcm = pcm.reshape(-1, self._num_channels)
            channel_data = pcm[:, self._channel].astype(np.float64)

            # Non-blocking put -- drop oldest if queue is full.
            try:
                self._queue.put_nowait(channel_data)
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self._queue.put_nowait(channel_data)
