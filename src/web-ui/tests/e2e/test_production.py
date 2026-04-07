"""Browser E2E tests for production-replica validation.

Playwright browser tests that verify mode badge, quantum display, and
graph updates are reflected in the real browser UI after mode switches.

API-only tests (mode switching, link counts, node presence) have been
moved to tests/service-integration/test_production.py (F-283).

Usage:
    nix run .#test-e2e    # runs both service-integration and e2e tiers
"""

import json
import os
import re
import socket
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.browser, pytest.mark.slow]

# Timeout for UI updates via WebSocket after mode switch.
UI_UPDATE_TIMEOUT_MS = 15_000
# Timeout for initial WebSocket data delivery.
WS_DATA_TIMEOUT_MS = 10_000


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


@pytest.fixture()
def demo_page(browser, local_demo_url):
    """Fresh browser page navigated to the local-demo server."""
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


def _wait_for_mode_badge(page, expected_mode: str,
                         timeout_ms=UI_UPDATE_TIMEOUT_MS):
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
    page.wait_for_function(
        f"""() => {{
            const el = document.getElementById('sb-quantum');
            return el && el.textContent.trim() === '{expected_quantum}';
        }}""",
        timeout=timeout_ms,
    )


# ===========================================================================
# 1. Mode Badge Default — Browser verification (F-228)
# ===========================================================================


class TestModeBadgeDefault:
    """Initial mode badge shows STANDBY in the browser (F-228 regression guard)."""

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
# 2. Mode Switching — Browser verification
# ===========================================================================


class TestModeSwitchingBrowser:
    """Browser UI updates after mode switches via API."""

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
        demo_page.wait_for_function(
            "document.querySelectorAll('#gv-svg .gv-node').length > 0",
            timeout=10000,
        )

        _set_mode(local_demo_url, "dj")
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
# 3. Quantum Change on Mode Switch (F-230)
# ===========================================================================


class TestQuantumOnModeSwitch:
    """Quantum changes correctly when switching modes (F-230, F-249).

    DJ mode: clock.force-quantum=1024
    All other modes: clock.force-quantum=256
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
