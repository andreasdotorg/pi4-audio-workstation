"""E2E tests for /api/v1/config against real PipeWire.

These tests exercise the exact code path that was broken in US-113:
pw-dump -> JSON parse -> config endpoint.  They run against the real
local-demo stack with PI_AUDIO_MOCK=0.

This is the regression gate that mock-backend integration tests cannot
provide (L-QE-002).
"""

import pytest

pytestmark = pytest.mark.e2e


class TestConfigEndpointReal:
    """Config endpoint returns real PipeWire data (not mock)."""

    def test_config_returns_200(self, api_get):
        """GET /api/v1/config returns 200, not 502."""
        status, data = api_get("/api/v1/config")
        assert status == 200, (
            f"Config endpoint returned {status} — pw-dump parse likely failed. "
            f"This is the exact US-113 blocker (L-QE-002)."
        )

    def test_config_has_quantum(self, api_get):
        """Config response includes a positive quantum value."""
        status, data = api_get("/api/v1/config")
        assert status == 200
        camilladsp = data.get("camilladsp", {})
        quantum = camilladsp.get("quantum")
        assert quantum is not None, "Config missing quantum"
        assert isinstance(quantum, int) and quantum > 0, (
            f"quantum should be positive int, got {quantum}"
        )

    def test_config_has_sample_rate(self, api_get):
        """Config response includes sample rate (expect 48000)."""
        status, data = api_get("/api/v1/config")
        assert status == 200
        camilladsp = data.get("camilladsp", {})
        rate = camilladsp.get("sample_rate")
        assert rate is not None, "Config missing sample_rate"
        assert rate == 48000, f"Expected 48000, got {rate}"

    def test_config_has_gain_values(self, api_get):
        """Config response includes per-channel gain Mult values."""
        status, data = api_get("/api/v1/config")
        assert status == 200
        camilladsp = data.get("camilladsp", {})
        gains = camilladsp.get("channel_gains", {})
        assert len(gains) > 0, (
            "Config should have channel_gains from real convolver params"
        )
        for name, mult in gains.items():
            assert isinstance(mult, (int, float)), (
                f"Gain {name} should be numeric, got {type(mult)}"
            )
            assert mult <= 1.0, (
                f"D-009 safety: gain {name} Mult={mult} exceeds 1.0"
            )

    def test_config_has_filter_chain_info(self, api_get):
        """Config response includes filter-chain convolver metadata."""
        status, data = api_get("/api/v1/config")
        assert status == 200
        camilladsp = data.get("camilladsp", {})
        fc = camilladsp.get("filter_chain", {})
        assert fc.get("node_id") is not None, (
            "filter_chain should have node_id from real convolver"
        )
        assert fc.get("node_name") is not None, (
            "filter_chain should have node_name"
        )


class TestGraphEndpointReal:
    """Graph topology endpoint returns real PW + GM data."""

    def test_graph_topology_returns_200(self, api_get):
        """GET /api/v1/graph/topology returns 200."""
        status, data = api_get("/api/v1/graph/topology")
        assert status == 200, f"Graph topology returned {status}: {data}"

    def test_graph_topology_has_nodes(self, api_get):
        """Graph topology includes PipeWire nodes."""
        status, data = api_get("/api/v1/graph/topology")
        assert status == 200
        assert "nodes" in data, f"Graph topology missing 'nodes': {list(data.keys())}"

    def test_graph_topology_has_links(self, api_get):
        """Graph topology includes link data."""
        status, data = api_get("/api/v1/graph/topology")
        assert status == 200
        assert "links" in data, (
            f"Graph topology should have 'links': {list(data.keys())}"
        )


class TestStatusEndpointReal:
    """Health-check endpoint returns ok."""

    def test_status_returns_200(self, api_get):
        """GET /api/v1/status returns 200."""
        status, data = api_get("/api/v1/status")
        assert status == 200, f"Status endpoint returned {status}: {data}"
        assert data.get("status") == "ok", f"Expected status=ok, got {data}"
