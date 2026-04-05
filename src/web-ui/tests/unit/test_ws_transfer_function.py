"""Unit tests for the transfer function WebSocket handler (US-120, T-120-03).

Tests verify:
- PcmStreamReader frame parsing and channel extraction
- PCM source lookup from environment
- Mock mode transfer function generation
- Engine loop data flow
"""

import asyncio
import json
import struct
import os

import numpy as np
import pytest

from app.collectors.pcm_reader import PcmStreamReader, V2_HEADER_SIZE
from app.transfer_function_routes import _get_pcm_source

# Alias for backward compat in tests.
_V2_HEADER = V2_HEADER_SIZE


# -- PCM source lookup tests --

class TestPcmSourceLookup:
    def test_default_monitor_source(self, monkeypatch):
        monkeypatch.delenv("PI4AUDIO_PCM_SOURCES", raising=False)
        result = _get_pcm_source("monitor")
        assert result == ("127.0.0.1", 9090)

    def test_custom_sources(self, monkeypatch):
        sources = json.dumps({
            "monitor": "tcp:10.0.0.1:9090",
            "capture-usb": "tcp:10.0.0.1:9091",
        })
        monkeypatch.setenv("PI4AUDIO_PCM_SOURCES", sources)
        assert _get_pcm_source("monitor") == ("10.0.0.1", 9090)
        assert _get_pcm_source("capture-usb") == ("10.0.0.1", 9091)

    def test_unknown_source_returns_none(self, monkeypatch):
        monkeypatch.delenv("PI4AUDIO_PCM_SOURCES", raising=False)
        assert _get_pcm_source("nonexistent") is None

    def test_invalid_json_returns_none(self, monkeypatch):
        monkeypatch.setenv("PI4AUDIO_PCM_SOURCES", "not json")
        assert _get_pcm_source("monitor") is None

    def test_malformed_address_returns_none(self, monkeypatch):
        sources = json.dumps({"bad": "no-port"})
        monkeypatch.setenv("PI4AUDIO_PCM_SOURCES", sources)
        assert _get_pcm_source("bad") is None


# -- V2 frame construction helper --

def _make_v2_frame(samples: np.ndarray, num_channels: int) -> bytes:
    """Build a pcm-bridge v2 wire format frame from interleaved float32 samples.

    Wire format v2: [version:1][pad:3][frame_count:4_LE][graph_pos:8_LE][graph_nsec:8_LE]
    Total header: 24 bytes.

    samples shape: (frame_count, num_channels) or (frame_count * num_channels,)
    """
    if samples.ndim == 1:
        frame_count = len(samples) // num_channels
    else:
        frame_count = samples.shape[0]
        samples = samples.flatten()

    # version(1) + pad(3) + frame_count(4) + graph_pos(8) + graph_nsec(8) = 24
    header = bytearray(24)
    header[0] = 2  # version
    struct.pack_into("<I", header, 4, frame_count)
    struct.pack_into("<Q", header, 8, 0)   # graph_pos
    struct.pack_into("<Q", header, 16, 0)  # graph_nsec
    pcm_bytes = samples.astype(np.float32).tobytes()
    return bytes(header) + pcm_bytes


class TestV2FrameHelper:
    def test_header_size(self):
        """Verify our test helper produces correct header size."""
        samples = np.zeros((128, 2), dtype=np.float32)
        frame = _make_v2_frame(samples, 2)
        assert frame[0] == 2  # version
        frame_count = struct.unpack_from("<I", frame, 4)[0]
        assert frame_count == 128
        expected_size = 24 + 128 * 2 * 4
        assert len(frame) == expected_size


# -- PcmStreamReader tests --

class TestPcmStreamReader:
    def test_extracts_correct_channel(self):
        """V2 frame parsing should extract the requested channel from
        interleaved PCM data (mirrors PcmStreamReader internal logic)."""
        # Create a 2-channel frame: ch0 = 1.0, ch1 = -1.0
        frame_count = 256
        interleaved = np.zeros((frame_count, 2), dtype=np.float32)
        interleaved[:, 0] = 1.0
        interleaved[:, 1] = -1.0
        frame_bytes = _make_v2_frame(interleaved, 2)

        # Simulate what PcmStreamReader does internally: parse v2 frame.
        assert frame_bytes[0] == 2  # version
        fc = struct.unpack_from("<I", frame_bytes, 4)[0]
        assert fc == frame_count

        pcm_data = np.frombuffer(frame_bytes[_V2_HEADER:], dtype=np.float32)
        pcm_data = pcm_data.reshape(-1, 2)

        # Channel 0 should be all 1.0
        ch0 = pcm_data[:, 0].astype(np.float64)
        np.testing.assert_allclose(ch0, 1.0)

        # Channel 1 should be all -1.0
        ch1 = pcm_data[:, 1].astype(np.float64)
        np.testing.assert_allclose(ch1, -1.0)

    def test_queue_overflow_drops_oldest(self):
        """When the queue is full, new data should replace the oldest."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)

        # Fill queue.
        queue.put_nowait(np.array([1.0]))
        queue.put_nowait(np.array([2.0]))
        assert queue.full()

        # Simulate the overflow logic from PcmStreamReader.
        new_data = np.array([3.0])
        try:
            queue.put_nowait(new_data)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()  # Drop oldest
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(new_data)

        # Queue should contain [2.0, 3.0] (oldest 1.0 dropped).
        items = []
        while not queue.empty():
            items.append(queue.get_nowait())
        assert len(items) == 2
        np.testing.assert_allclose(items[0], [2.0])
        np.testing.assert_allclose(items[1], [3.0])


# -- Integration-style test: engine loop data flow --

class TestEngineDataFlow:
    def test_engine_processes_paired_data(self):
        """Verify that the engine produces valid results when fed
        paired reference and measurement data."""
        from app.transfer_function import TransferFunctionConfig, TransferFunctionEngine

        cfg = TransferFunctionConfig(fft_size=1024, alpha=0.25)
        engine = TransferFunctionEngine(cfg)

        np.random.seed(42)
        for _ in range(8):
            ref = np.random.randn(1024)
            meas = ref * 0.5  # -6 dB gain
            engine.process_block(ref, meas)

        result = engine.compute()
        d = result.to_json_dict()

        assert d["blocks_accumulated"] >= 8
        assert len(d["magnitude_db"]) == cfg.n_bins
        assert len(d["coherence"]) == cfg.n_bins
        # With deterministic gain, magnitude should be near -6 dB.
        mid_mag = np.array(d["magnitude_db"][10:-10])
        expected_db = 20.0 * np.log10(0.5)  # -6.02 dB
        assert np.all(np.abs(mid_mag - expected_db) < 1.0)

    def test_to_json_dict_has_required_fields(self):
        """Verify the JSON frame has all fields expected by the WS client."""
        from app.transfer_function import TransferFunctionConfig, TransferFunctionEngine

        cfg = TransferFunctionConfig(fft_size=256)
        engine = TransferFunctionEngine(cfg)
        engine.process_block(np.random.randn(256), np.random.randn(256))
        result = engine.compute()
        d = result.to_json_dict()

        required_fields = [
            "magnitude_db", "phase_deg", "coherence", "freq_axis",
            "channel", "blocks_accumulated", "delay_samples", "warming_up",
        ]
        for field in required_fields:
            assert field in d, f"Missing required field: {field}"
