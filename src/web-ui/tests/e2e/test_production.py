"""E2E tests for production-replica validation (US-075 Bug #7).

Validates the local-demo stack against production expectations using real
PipeWire and GraphManager. All tests require ``nix run .#local-demo`` and
are auto-skipped when LOCAL_DEMO_URL is not reachable.

Covers the top 4 gaps identified in the E2E audit:

    1. Mode switching: standby -> dj -> live -> measurement -> standby
       with UI verification at each step (mode badge, graph, link counts)
    2. Link count verification per mode (Standby, DJ, Live, Measurement)
    3. Quantum change on mode switch (F-230): DJ=1024, others=256
    4. Mode badge default = "standby" on initial load (F-228)

Usage:
    # Start local-demo in another terminal:
    nix run .#local-demo

    # Run the tests:
    cd src/web-ui
    python -m pytest tests/integration/test_production_replica.py -v --headed

    # Or with custom URL:
    LOCAL_DEMO_URL=http://localhost:9090 python -m pytest ...

Marked @pytest.mark.slow -- mode switches take 2-5 seconds each.
"""

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.browser, pytest.mark.slow]

# Timeout for GM reconciliation after a mode switch.
MODE_SWITCH_SETTLE_S = 5
# Timeout for UI updates via WebSocket after mode switch.
UI_UPDATE_TIMEOUT_MS = 15_000
# Timeout for initial WebSocket data delivery.
WS_DATA_TIMEOUT_MS = 10_000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _probe_server(url: str) -> bool:
    """Check if server is reachable (TCP connect)."""
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
    """Resolve the local-demo server URL, skip if unreachable."""
    url = os.environ.get("LOCAL_DEMO_URL", "http://localhost:8080")
    if not _probe_server(url):
        pytest.skip(
            f"Local-demo server not reachable at {url}. "
            f"Start it with: nix run .#local-demo")
    return url


@pytest.fixture()
def demo_page(browser, local_demo_url):
    """Fresh browser page navigated to the local-demo server.

    Does NOT reset measurement state (no /reset endpoint in non-mock mode).
    """
    context = browser.new_context()
    pg = context.new_page()
    console_errors = []
    pg.on(
        "console",
        lambda msg: console_errors.append(msg.text)
        if msg.type == "error" else None,
    )
    pg.goto(local_demo_url)
    pg.wait_for_timeout(2000)
    yield pg
    context.close()
    real_errors = [
        e for e in console_errors
        if "/ws/siggen" not in e and "WebSocket" not in e
    ]
    if real_errors:
        print(f"[local-demo E2E] JS console errors (non-fatal): {real_errors}")


@pytest.fixture(autouse=True)
def _ensure_standby(local_demo_url):
    """Ensure GM is in standby mode before and after each test.

    This prevents test ordering dependencies and leaves the local-demo
    in a clean state.
    """
    _set_mode(local_demo_url, "standby")
    yield
    _set_mode(local_demo_url, "standby")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _switch_tab(page, view_name: str):
    page.locator(f'.nav-tab[data-view="{view_name}"]').click()
    expect(page.locator(f"#view-{view_name}")).to_have_class(
        re.compile(r".*\bactive\b.*"))


def _wait_for_ws_data(page, timeout_ms=WS_DATA_TIMEOUT_MS):
    """Wait until WebSocket delivers data (DSP state is no longer '--')."""
    page.locator("#sb-dsp-state").wait_for(state="attached")
    page.wait_for_function(
        "document.getElementById('sb-dsp-state').textContent !== '--'",
        timeout=timeout_ms,
    )


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
    """Query current GM mode via test-tool API."""
    try:
        data = _api_get(base_url, "/api/v1/test-tool/current-mode")
        return data.get("mode", "unknown")
    except Exception:
        return "unknown"


def _set_mode(base_url, mode: str) -> bool:
    """Switch GM to the given mode via test-tool API. Returns True on success."""
    try:
        if mode == "measurement":
            result = _api_post(base_url,
                               "/api/v1/test-tool/ensure-measurement-mode")
        else:
            result = _api_post(base_url, "/api/v1/test-tool/restore-mode",
                               {"mode": mode})
        time.sleep(MODE_SWITCH_SETTLE_S)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 502:
            pytest.skip("GM not connected -- cannot switch mode")
        raise
    except Exception:
        return False


def _get_topology(base_url) -> dict:
    """Get graph topology from the API."""
    return _api_get(base_url, "/api/v1/graph/topology")


def _wait_for_mode_badge(page, expected_mode: str,
                         timeout_ms=UI_UPDATE_TIMEOUT_MS):
    """Wait for the mode badge in the browser to show the expected mode."""
    expected_upper = expected_mode.upper()
    page.wait_for_function(
        f"""() => {{
            const el = document.getElementById('sb-mode');
            return el && el.textContent.trim().toUpperCase() === '{expected_upper}';
        }}""",
        timeout=timeout_ms,
    )


def _wait_for_quantum(page, expected_quantum: str,
                      timeout_ms=UI_UPDATE_TIMEOUT_MS):
    """Wait for the quantum display in the browser to show the expected value."""
    page.wait_for_function(
        f"""() => {{
            const el = document.getElementById('sb-quantum');
            return el && el.textContent.trim() === '{expected_quantum}';
        }}""",
        timeout=timeout_ms,
    )


# ===========================================================================
# 1. Mode Badge Default (F-228)
# ===========================================================================


class TestModeBadgeDefault:
    """Initial mode badge shows STANDBY, not DJ (F-228 regression guard)."""

    def test_initial_mode_is_standby_api(self, local_demo_url):
        """GM reports standby mode on initial startup."""
        mode = _get_mode(local_demo_url)
        assert mode == "standby", (
            f"Expected initial mode 'standby', got '{mode}'")

    def test_mode_badge_shows_standby_in_browser(self, demo_page):
        """Mode badge in browser shows STANDBY on initial load."""
        _wait_for_ws_data(demo_page)
        _wait_for_mode_badge(demo_page, "standby")
        text = demo_page.locator("#sb-mode").text_content().strip().upper()
        assert text == "STANDBY", (
            f"Expected 'STANDBY' mode badge, got '{text}'")

    def test_system_view_mode_shows_standby(self, demo_page):
        """System view mode element shows standby."""
        _switch_tab(demo_page, "system")
        demo_page.locator("#sys-mode").wait_for(state="attached", timeout=5000)
        demo_page.wait_for_function(
            "document.getElementById('sys-mode').textContent !== '--'",
            timeout=WS_DATA_TIMEOUT_MS,
        )
        text = demo_page.locator("#sys-mode").text_content().strip().upper()
        assert "STANDBY" in text, (
            f"Expected 'STANDBY' in system mode, got '{text}'")


# ===========================================================================
# 2. Mode Switching E2E
# ===========================================================================


class TestModeSwitching:
    """Full mode switching cycle: standby -> dj -> live -> standby.

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

    def test_mode_badge_updates_in_browser_after_dj_switch(
            self, demo_page, local_demo_url):
        """Browser mode badge updates to DJ after API mode switch."""
        _wait_for_ws_data(demo_page)
        _wait_for_mode_badge(demo_page, "standby")

        _set_mode(local_demo_url, "dj")
        _wait_for_mode_badge(demo_page, "dj")
        text = demo_page.locator("#sb-mode").text_content().strip().upper()
        assert text == "DJ", f"Expected 'DJ', got '{text}'"

    def test_mode_badge_updates_in_browser_after_live_switch(
            self, demo_page, local_demo_url):
        """Browser mode badge updates to LIVE after API mode switch."""
        _wait_for_ws_data(demo_page)

        _set_mode(local_demo_url, "live")
        _wait_for_mode_badge(demo_page, "live")
        text = demo_page.locator("#sb-mode").text_content().strip().upper()
        assert text == "LIVE", f"Expected 'LIVE', got '{text}'"

    def test_mode_badge_updates_in_browser_after_measurement_switch(
            self, demo_page, local_demo_url):
        """Browser mode badge updates to MEASUREMENT after API mode switch."""
        _wait_for_ws_data(demo_page)

        _set_mode(local_demo_url, "measurement")
        _wait_for_mode_badge(demo_page, "measurement")
        text = demo_page.locator("#sb-mode").text_content().strip().upper()
        assert text == "MEASUREMENT", f"Expected 'MEASUREMENT', got '{text}'"

    def test_graph_mode_label_updates_after_switch(
            self, demo_page, local_demo_url):
        """Graph tab mode label updates after mode switch."""
        _wait_for_ws_data(demo_page)
        _switch_tab(demo_page, "graph")
        # Wait for initial graph render
        demo_page.wait_for_function(
            "document.querySelectorAll('#gv-svg .gv-node').length > 0",
            timeout=10000,
        )

        _set_mode(local_demo_url, "dj")
        # Wait for graph to re-render with new mode
        demo_page.wait_for_function(
            """() => {
                const el = document.getElementById('gv-mode-label');
                return el && el.textContent.toUpperCase().includes('DJ');
            }""",
            timeout=UI_UPDATE_TIMEOUT_MS,
        )
        label_text = demo_page.locator("#gv-mode-label").text_content()
        assert "DJ" in label_text.upper(), (
            f"Expected 'DJ' in graph mode label, got '{label_text}'")


# ===========================================================================
# 3. Link Count Verification Per Mode
# ===========================================================================


class TestLinkCountsPerMode:
    """Verify link counts from graph topology match routing table expectations.

    Expected counts (from routing.rs tests):
        2-way: Standby 21, DJ 39, Live 49, Measurement 27
        3-way: Standby 23, DJ 43, Live 53, Measurement 31

    Link counts may be lower if optional links fail (e.g., level-bridge
    when no convolver-out node exists yet). We use ranges.
    """

    # (min, max) link count ranges per mode.
    # Lower bound accounts for optional links failing.
    # Upper bound accounts for 3-way layout + system links.
    # Ranges are wide because local-demo topology differs from production
    # (no real USBStreamer, virtual ALSA sink, optional links may not connect).
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
        reason="GM reconciler timing: rapid DJ->live switch may not stabilize "
               "before PipeWire link destruction completes (PW 1.6.x)",
        strict=False,
    )
    def test_live_has_at_least_as_many_links_as_dj(self, local_demo_url):
        """Live mode has at least as many links as DJ.

        During mode transitions, the link count temporarily drops as old
        links are removed before new ones are created.  We poll until the
        topology reports 'live' mode AND the link count stabilizes.
        """
        _set_mode(local_demo_url, "dj")
        topo_dj = _get_topology(local_demo_url)
        dj_links = len(topo_dj.get("links", []))

        _set_mode(local_demo_url, "live")
        # Poll until mode=live and link count stabilizes
        live_links = 0
        prev_links = -1
        for _ in range(6):
            topo_live = _get_topology(local_demo_url)
            if topo_live.get("mode") == "live":
                live_links = len(topo_live.get("links", []))
                if live_links == prev_links and live_links > 0:
                    break  # Stabilized
                prev_links = live_links
            time.sleep(2)

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
# 4. Quantum Change on Mode Switch (F-230)
# ===========================================================================


class TestQuantumOnModeSwitch:
    """Quantum changes correctly when switching modes (F-230).

    DJ mode: clock.force-quantum=1024
    All other modes: clock.force-quantum=0 (reverts to config default 256)
    """

    def test_standby_quantum_256(self, demo_page, local_demo_url):
        """Standby mode shows quantum 256 (config default)."""
        _wait_for_ws_data(demo_page)
        _wait_for_quantum(demo_page, "256")
        text = demo_page.locator("#sb-quantum").text_content().strip()
        assert text == "256", f"Expected quantum '256' in standby, got '{text}'"

    def test_dj_quantum_1024(self, demo_page, local_demo_url):
        """DJ mode shows quantum 1024 (F-230: force-quantum)."""
        _wait_for_ws_data(demo_page)
        _set_mode(local_demo_url, "dj")
        _wait_for_quantum(demo_page, "1024")
        text = demo_page.locator("#sb-quantum").text_content().strip()
        assert text == "1024", f"Expected quantum '1024' in DJ, got '{text}'"

    def test_live_quantum_256(self, demo_page, local_demo_url):
        """Live mode shows quantum 256 (F-230: clears force-quantum)."""
        _wait_for_ws_data(demo_page)
        _set_mode(local_demo_url, "live")
        _wait_for_quantum(demo_page, "256")
        text = demo_page.locator("#sb-quantum").text_content().strip()
        assert text == "256", f"Expected quantum '256' in live, got '{text}'"

    def test_dj_then_live_quantum_changes(self, demo_page, local_demo_url):
        """Switching DJ -> live changes quantum from 1024 back to 256."""
        _wait_for_ws_data(demo_page)

        _set_mode(local_demo_url, "dj")
        _wait_for_quantum(demo_page, "1024")

        _set_mode(local_demo_url, "live")
        _wait_for_quantum(demo_page, "256")

        text = demo_page.locator("#sb-quantum").text_content().strip()
        assert text == "256", (
            f"After DJ->Live, expected quantum '256', got '{text}'")

    def test_dj_then_standby_quantum_changes(self, demo_page, local_demo_url):
        """Switching DJ -> standby changes quantum from 1024 back to 256."""
        _wait_for_ws_data(demo_page)

        _set_mode(local_demo_url, "dj")
        _wait_for_quantum(demo_page, "1024")

        _set_mode(local_demo_url, "standby")
        _wait_for_quantum(demo_page, "256")

        text = demo_page.locator("#sb-quantum").text_content().strip()
        assert text == "256", (
            f"After DJ->Standby, expected quantum '256', got '{text}'")

    def test_system_view_quantum_updates(self, demo_page, local_demo_url):
        """System view quantum element updates after mode switch."""
        _wait_for_ws_data(demo_page)
        _switch_tab(demo_page, "system")
        demo_page.locator("#sys-quantum").wait_for(
            state="attached", timeout=5000)
        demo_page.wait_for_function(
            "document.getElementById('sys-quantum').textContent !== '--'",
            timeout=WS_DATA_TIMEOUT_MS,
        )

        _set_mode(local_demo_url, "dj")
        demo_page.wait_for_function(
            "document.getElementById('sys-quantum').textContent.includes('1024')",
            timeout=UI_UPDATE_TIMEOUT_MS,
        )
        text = demo_page.locator("#sys-quantum").text_content().strip()
        assert "1024" in text, (
            f"Expected '1024' in system quantum after DJ switch, got '{text}'")


# ===========================================================================
# 5. Production Node Presence
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
        # Local-demo uses pw-play or a substitute for Mixxx.
        # Check for any node with "mixxx" or "pw-play" in its name.
        has_source = any(
            "mixxx" in n.lower() or "pw-play" in n.lower() or "substitute" in n.lower()
            for n in names
        )
        if not has_source:
            # May also be a generic stream; check for any Stream/Output/Audio
            stream_nodes = [
                n for n in topo["nodes"]
                if n.get("media_class") == "Stream/Output/Audio"
            ]
            has_source = len(stream_nodes) > 0
        assert has_source, (
            f"Expected a Mixxx substitute or audio stream node in DJ mode. "
            f"Found: {sorted(names)}")
