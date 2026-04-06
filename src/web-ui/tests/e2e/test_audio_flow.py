"""E2E audio flow tests — ported from scripts/test-integration.sh.

These tests verify the live local-demo audio pipeline:
- GraphManager RPC responds correctly
- Level-bridge reports non-zero levels when audio is flowing
- Timestamps are monotonically increasing (US-077)
- pcm-bridge v2 binary header is correct (US-077)

They require the full stack to be running (PipeWire + GM + signal-gen +
level-bridge + pcm-bridge + web UI). The test-e2e.sh wrapper starts the
stack before pytest is invoked.
"""

import json

import pytest


pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Check 2: GM get_graph_info returns valid data
# ---------------------------------------------------------------------------

class TestGMGraphInfo:
    """GM get_graph_info RPC returns valid graph metadata."""

    def test_gm_get_graph_info_ok(self, rpc_call, gm_port):
        """get_graph_info returns ok=true."""
        resp = rpc_call("127.0.0.1", gm_port, {"cmd": "get_graph_info"})
        assert resp.get("ok") is True, (
            f"get_graph_info should return ok=true, got: {resp}"
        )

    def test_gm_get_graph_info_has_sample_rate(self, rpc_call, gm_port):
        """get_graph_info includes sample_rate."""
        resp = rpc_call("127.0.0.1", gm_port, {"cmd": "get_graph_info"})
        assert resp.get("ok") is True
        rate = resp.get("sample_rate")
        assert rate is not None, f"Missing sample_rate in: {resp}"
        assert isinstance(rate, int) and rate > 0, (
            f"sample_rate should be positive int, got {rate}"
        )


# ---------------------------------------------------------------------------
# Check 3: GM get_links reports link topology
# ---------------------------------------------------------------------------

class TestGMLinks:
    """GM get_links RPC returns link topology."""

    def test_gm_get_links_ok(self, rpc_call, gm_port):
        """get_links returns ok=true."""
        resp = rpc_call("127.0.0.1", gm_port, {"cmd": "get_links"})
        assert resp.get("ok") is True, (
            f"get_links should return ok=true, got: {resp}"
        )

    def test_gm_get_links_has_desired(self, rpc_call, gm_port):
        """get_links reports desired link count > 0."""
        resp = rpc_call("127.0.0.1", gm_port, {"cmd": "get_links"})
        assert resp.get("ok") is True
        desired = resp.get("desired", 0)
        assert isinstance(desired, int) and desired > 0, (
            f"desired link count should be > 0, got {desired}"
        )

    def test_gm_get_links_has_actual(self, rpc_call, gm_port):
        """get_links reports actual link count > 0."""
        resp = rpc_call("127.0.0.1", gm_port, {"cmd": "get_links"})
        assert resp.get("ok") is True
        actual = resp.get("actual", 0)
        assert isinstance(actual, int) and actual > 0, (
            f"actual link count should be > 0, got {actual}"
        )

    def test_gm_get_links_has_mode(self, rpc_call, gm_port):
        """get_links reports current mode."""
        resp = rpc_call("127.0.0.1", gm_port, {"cmd": "get_links"})
        assert resp.get("ok") is True
        mode = resp.get("mode")
        assert mode is not None, f"Missing mode in get_links response: {resp}"


# ---------------------------------------------------------------------------
# Check 4+5: Level-bridge reports non-zero levels
# ---------------------------------------------------------------------------

class TestLevelBridge:
    """Level-bridge instances report non-zero audio levels.

    Requires DJ mode so that signal-gen/Mixxx are linked through the
    convolver to the level bridges.
    """

    @pytest.mark.xfail(
        reason="F-272: reconciler race — no deterministic settlement signal "
               "(also F-262: UMIK sim signal loss after mode transition)",
        strict=False,
    )
    def test_level_bridge_sw_has_signal(self, ensure_dj_mode, read_levels):
        """level-bridge-sw (port 9100) reports non-zero peak levels."""
        lines = read_levels(9100, count=1)
        assert len(lines) >= 1, "No data from level-bridge-sw on port 9100"
        data = lines[0]
        peak = data.get("peak", [])
        assert len(peak) > 0, f"No peak data in level-bridge response: {data}"
        has_signal = any(p > -100.0 for p in peak)
        assert has_signal, (
            f"level-bridge-sw: all channels at silence (peak: {peak})"
        )

    def test_level_bridge_hw_out_responds(self, ensure_dj_mode, read_levels):
        """level-bridge-hw-out (port 9101) responds with peak data.

        In local-demo, the hw-out bridge monitors the virtual USBStreamer
        sink. Signal may or may not be present depending on whether the
        null sink passes audio through. We only verify the bridge responds
        with valid peak data (connectivity test).
        """
        lines = read_levels(9101, count=1)
        assert len(lines) >= 1, "No data from level-bridge-hw-out on port 9101"
        data = lines[0]
        peak = data.get("peak", [])
        assert len(peak) > 0, f"No peak data in level-bridge response: {data}"


# ---------------------------------------------------------------------------
# Check 8: Timestamp monotonicity (US-077 DoD #3)
# ---------------------------------------------------------------------------

class TestTimestampMonotonicity:
    """Level-bridge pos/nsec timestamps increase monotonically."""

    def test_timestamps_monotonic(self, read_levels):
        """Read 8 snapshots, verify pos and nsec strictly increase."""
        lines = read_levels(9100, count=8)
        # Filter to snapshots with non-zero timestamps
        valid = [d for d in lines if d.get("pos", 0) > 0 and d.get("nsec", 0) > 0]
        assert len(valid) >= 3, (
            f"Need at least 3 non-zero timestamp snapshots, got {len(valid)}"
        )

        for i in range(1, len(valid)):
            prev = valid[i - 1]
            curr = valid[i]
            assert curr["pos"] > prev["pos"], (
                f"pos not monotonic: snapshot {i} pos={curr['pos']} "
                f"<= prev={prev['pos']}"
            )
            assert curr["nsec"] > prev["nsec"], (
                f"nsec not monotonic: snapshot {i} nsec={curr['nsec']} "
                f"<= prev={prev['nsec']}"
            )


# ---------------------------------------------------------------------------
# Check 9: pcm-bridge v2 binary header (US-077 DoD #3)
# ---------------------------------------------------------------------------

class TestPcmBridgeV2:
    """pcm-bridge binary protocol v2 header verification."""

    def test_pcm_bridge_v2_header(self, read_pcm_header):
        """pcm-bridge sends v2 header with non-zero graph_pos/graph_nsec."""
        header = read_pcm_header(9090)
        assert header is not None, (
            "No data frames received from pcm-bridge on port 9090"
        )
        assert header["version"] == 2, (
            f"Expected version 2, got {header['version']}"
        )
        assert header["frame_count"] > 0, (
            f"frame_count should be > 0, got {header['frame_count']}"
        )
        assert header["graph_pos"] > 0, (
            f"graph_pos should be > 0, got {header['graph_pos']}"
        )
        assert header["graph_nsec"] > 0, (
            f"graph_nsec should be > 0, got {header['graph_nsec']}"
        )
