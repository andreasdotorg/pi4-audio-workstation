"""Service-integration tests for production-replica validation.

API-only tests extracted from tests/e2e/test_production.py (F-283).
These verify mode switching, link topology, and node presence against
the real local-demo stack via HTTP API — no browser needed.

Browser-driven tests remain in tests/e2e/test_production.py.

Usage:
    nix run .#test-e2e    # runs both service-integration and e2e tiers
"""

import json
import os
import socket
import urllib.error
import urllib.request

import pytest


pytestmark = [pytest.mark.service_integration, pytest.mark.slow]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _probe_server(url: str) -> bool:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def local_demo_url():
    url = os.environ.get("LOCAL_DEMO_URL", "http://localhost:8080")
    if not _probe_server(url):
        pytest.skip(
            f"Local-demo server not reachable at {url}. "
            f"Start it with: nix run .#local-demo")
    return url


@pytest.fixture(autouse=True)
def _ensure_standby(local_demo_url):
    _set_mode(local_demo_url, "standby")
    yield
    _set_mode(local_demo_url, "standby")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_get(base_url, path, timeout=10):
    resp = urllib.request.urlopen(f"{base_url}{path}", timeout=timeout)
    return json.loads(resp.read())


def _api_post(base_url, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body else b""
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def _get_mode(base_url) -> str:
    try:
        data = _api_get(base_url, "/api/v1/test-tool/current-mode")
        return data.get("mode", "unknown")
    except Exception:
        return "unknown"


def _set_mode(base_url, mode: str) -> bool:
    try:
        if mode == "measurement":
            _api_post(base_url,
                      "/api/v1/test-tool/ensure-measurement-mode")
        else:
            _api_post(base_url, "/api/v1/test-tool/restore-mode",
                      {"mode": mode})
        return True
    except urllib.error.HTTPError as e:
        if e.code == 502:
            pytest.skip("GM not connected -- cannot switch mode")
        raise
    except Exception:
        return False


def _get_topology(base_url) -> dict:
    return _api_get(base_url, "/api/v1/graph/topology")


# ===========================================================================
# 1. Mode Badge Default — API check only (F-228)
# ===========================================================================


class TestModeBadgeDefaultAPI:
    """Initial mode is standby (API verification)."""

    def test_initial_mode_is_standby_api(self, local_demo_url):
        """GM reports standby mode on initial startup."""
        mode = _get_mode(local_demo_url)
        assert mode == "standby", (
            f"Expected initial mode 'standby', got '{mode}'")


# ===========================================================================
# 2. Mode Switching — API only
# ===========================================================================


class TestModeSwitching:
    """Full mode switching cycle via API.

    Each switch verifies the API reports the new mode and the topology
    mode field matches.
    """

    def test_switch_standby_to_dj(self, local_demo_url):
        """Switch from standby to DJ mode via API."""
        assert _set_mode(local_demo_url, "dj")
        mode = _get_mode(local_demo_url)
        assert mode == "dj", f"Expected 'dj', got '{mode}'"

        topo = _get_topology(local_demo_url)
        assert topo["mode"] == "dj", (
            f"Topology mode should be 'dj', got '{topo['mode']}'")

    def test_switch_dj_to_live(self, local_demo_url):
        """Switch from standby to DJ, then to live mode."""
        _set_mode(local_demo_url, "dj")
        assert _set_mode(local_demo_url, "live")
        mode = _get_mode(local_demo_url)
        assert mode == "live", f"Expected 'live', got '{mode}'"

        topo = _get_topology(local_demo_url)
        assert topo["mode"] == "live", (
            f"Topology mode should be 'live', got '{topo['mode']}'")

    def test_switch_to_measurement(self, local_demo_url):
        """Switch to measurement mode."""
        assert _set_mode(local_demo_url, "measurement")
        mode = _get_mode(local_demo_url)
        assert mode == "measurement", f"Expected 'measurement', got '{mode}'"

        topo = _get_topology(local_demo_url)
        assert topo["mode"] == "measurement", (
            f"Topology mode should be 'measurement', got '{topo['mode']}'")

    def test_switch_measurement_back_to_standby(self, local_demo_url):
        """Switch to measurement, then back to standby."""
        _set_mode(local_demo_url, "measurement")
        assert _set_mode(local_demo_url, "standby")
        mode = _get_mode(local_demo_url)
        assert mode == "standby", f"Expected 'standby', got '{mode}'"

    def test_full_cycle_standby_dj_live_standby(self, local_demo_url):
        """Full cycle: standby -> dj -> live -> standby."""
        for target in ("dj", "live", "standby"):
            assert _set_mode(local_demo_url, target)
            mode = _get_mode(local_demo_url)
            assert mode == target, (
                f"After switching to '{target}', got '{mode}'")


# ===========================================================================
# 3. Link Count Verification Per Mode
# ===========================================================================


class TestLinkCountsPerMode:
    """Verify link counts from graph topology match routing table expectations."""

    LINK_RANGES = {
        "standby":     (15, 35),
        "dj":          (15, 55),
        "live":        (15, 65),
        "measurement": (15, 45),
    }

    @pytest.mark.parametrize("mode,link_range", list(LINK_RANGES.items()),
                             ids=list(LINK_RANGES.keys()))
    def test_link_count_in_range(self, local_demo_url, mode, link_range):
        """Link count for {mode} mode is within expected range."""
        _set_mode(local_demo_url, mode)
        topo = _get_topology(local_demo_url)
        link_count = len(topo.get("links", []))
        lo, hi = link_range
        assert lo <= link_count <= hi, (
            f"Expected {lo}-{hi} links in {mode} mode, got {link_count}")

    def test_dj_has_more_links_than_standby(self, local_demo_url):
        """DJ mode has at least as many links as standby."""
        _set_mode(local_demo_url, "standby")
        standby_links = len(_get_topology(local_demo_url).get("links", []))

        _set_mode(local_demo_url, "dj")
        dj_links = len(_get_topology(local_demo_url).get("links", []))

        assert dj_links >= standby_links, (
            f"DJ ({dj_links}) should have >= links than standby ({standby_links})")

    @pytest.mark.xfail(
        reason="F-290: assertion incorrect — DJ has more links than live "
               "due to Mixxx 8ch routing",
        strict=False,
    )
    def test_live_has_at_least_as_many_links_as_dj(self, local_demo_url):
        """Live mode has at least as many links as DJ."""
        _set_mode(local_demo_url, "dj")
        topo_dj = _get_topology(local_demo_url)
        dj_links = len(topo_dj.get("links", []))

        _set_mode(local_demo_url, "live")
        topo_live = _get_topology(local_demo_url)
        live_links = len(topo_live.get("links", []))

        assert live_links >= dj_links, (
            f"Live ({live_links}) should have >= links than DJ ({dj_links})")

    def test_topology_mode_matches_after_each_switch(self, local_demo_url):
        """Topology mode field matches the requested mode after each switch."""
        for mode in ("standby", "dj", "live", "measurement", "standby"):
            _set_mode(local_demo_url, mode)
            topo = _get_topology(local_demo_url)
            assert topo["mode"] == mode, (
                f"Expected topology mode '{mode}', got '{topo['mode']}'")


# ===========================================================================
# 4. Production Node Presence
# ===========================================================================


class TestProductionNodePresence:
    """Verify production-expected nodes exist in the local-demo topology."""

    def test_convolver_node_present(self, local_demo_url):
        """Convolver node exists in topology."""
        topo = _get_topology(local_demo_url)
        names = {n["name"] for n in topo["nodes"]}
        assert "pi4audio-convolver" in names, (
            f"Missing pi4audio-convolver. Found: {sorted(names)}")

    def test_convolver_out_node_present(self, local_demo_url):
        """Convolver-out node exists in topology."""
        topo = _get_topology(local_demo_url)
        names = {n["name"] for n in topo["nodes"]}
        assert "pi4audio-convolver-out" in names, (
            f"Missing pi4audio-convolver-out. Found: {sorted(names)}")

    def test_level_bridge_nodes_present(self, local_demo_url):
        """Level-bridge nodes (sw, hw-out, hw-in) exist in topology."""
        topo = _get_topology(local_demo_url)
        names = {n["name"] for n in topo["nodes"]}
        for bridge in ("pi4audio-level-bridge-sw",
                       "pi4audio-level-bridge-hw-out",
                       "pi4audio-level-bridge-hw-in"):
            assert bridge in names, (
                f"Missing {bridge}. Found: {sorted(names)}")

    def test_signal_gen_node_present(self, local_demo_url):
        """Signal-gen node exists in topology."""
        topo = _get_topology(local_demo_url)
        names = {n["name"] for n in topo["nodes"]}
        assert "pi4audio-signal-gen" in names, (
            f"Missing pi4audio-signal-gen. Found: {sorted(names)}")

    def test_pcm_bridge_node_present(self, local_demo_url):
        """PCM-bridge node exists in topology."""
        topo = _get_topology(local_demo_url)
        names = {n["name"] for n in topo["nodes"]}
        assert "pi4audio-pcm-bridge" in names, (
            f"Missing pi4audio-pcm-bridge. Found: {sorted(names)}")

    def test_mixxx_substitute_present_in_dj(self, local_demo_url):
        """In DJ mode, a Mixxx substitute node exists."""
        _set_mode(local_demo_url, "dj")
        topo = _get_topology(local_demo_url)
        names = {n["name"] for n in topo["nodes"]}
        has_source = any(
            "mixxx" in n.lower() or "pw-play" in n.lower() or "substitute" in n.lower()
            for n in names
        )
        if not has_source:
            stream_nodes = [
                n for n in topo["nodes"]
                if n.get("media_class") == "Stream/Output/Audio"
            ]
            has_source = len(stream_nodes) > 0
        assert has_source, (
            f"Expected a Mixxx substitute or audio stream node in DJ mode. "
            f"Found: {sorted(names)}")
