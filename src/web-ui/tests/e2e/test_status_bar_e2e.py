"""Browser E2E: Status bar elements visible and updated (US-148).

Verifies that the persistent status bar renders correctly across tabs:
connection dot, mini meters, panic button, mode badge/dropdown, DSP state,
quantum, and system gauges.

Usage:
    nix run .#test-e2e    # runs both service-integration and e2e tiers
"""

import os
import re
import socket

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.browser, pytest.mark.slow]

WS_DATA_TIMEOUT_MS = 15_000


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
    pg.goto(local_demo_url)
    pg.wait_for_timeout(2000)
    yield pg
    context.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_ws_data(page, timeout_ms=WS_DATA_TIMEOUT_MS):
    """Wait until WebSocket delivers data (DSP state not '--')."""
    page.locator("#sb-dsp-state").wait_for(state="attached")
    page.wait_for_function(
        "document.getElementById('sb-dsp-state').textContent !== '--'",
        timeout=timeout_ms,
    )


def _switch_tab(page, view_name: str):
    page.locator(f'.nav-tab[data-view="{view_name}"]').click()
    expect(page.locator(f"#view-{view_name}")).to_have_class(
        re.compile(r".*\bactive\b.*"))


# ===========================================================================
# 1. Connection dot
# ===========================================================================

class TestConnectionDot:
    """Verify the WebSocket connection indicator dot."""

    def test_connection_dot_exists(self, demo_page):
        """Connection dot element is present in the nav bar."""
        dot = demo_page.locator("#conn-dot")
        expect(dot).to_be_attached()

    def test_connection_dot_turns_green(self, demo_page):
        """Connection dot gets 'connected' class after WebSocket connects."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_function(
            """() => {
                const dot = document.getElementById('conn-dot');
                return dot && dot.classList.contains('connected');
            }""",
            timeout=WS_DATA_TIMEOUT_MS,
        )


# ===========================================================================
# 2. Mini meters in status bar
# ===========================================================================

class TestStatusBarMiniMeters:
    """Verify mini meter canvases in the status bar."""

    @pytest.mark.parametrize("canvas_id", [
        "sb-mini-main",
        "sb-mini-app",
        "sb-mini-dspout",
        "sb-mini-physin",
    ])
    def test_mini_meter_canvas_exists(self, demo_page, canvas_id):
        """Mini meter canvas element is present."""
        canvas = demo_page.locator(f"#{canvas_id}")
        expect(canvas).to_be_attached()

    def test_mini_meters_render_after_ws_data(self, demo_page):
        """At least one mini meter canvas renders non-zero pixels."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_function(
            """() => {
                const ids = ['sb-mini-main', 'sb-mini-app',
                             'sb-mini-dspout', 'sb-mini-physin'];
                for (const id of ids) {
                    const c = document.getElementById(id);
                    if (!c || c.width === 0 || c.height === 0) continue;
                    const ctx = c.getContext('2d');
                    const data = ctx.getImageData(0, 0, c.width, c.height).data;
                    for (let i = 3; i < data.length; i += 4) {
                        if (data[i] > 0) return true;
                    }
                }
                return false;
            }""",
            timeout=WS_DATA_TIMEOUT_MS,
        )


# ===========================================================================
# 3. Panic button
# ===========================================================================

class TestPanicButton:
    """Verify the panic (MUTE) button is visible and clickable."""

    def test_panic_button_exists(self, demo_page):
        """Panic button element with data-testid is present."""
        btn = demo_page.locator('[data-testid="panic-button"]')
        expect(btn).to_be_attached()

    def test_panic_button_visible(self, demo_page):
        """Panic button is visible on the page."""
        btn = demo_page.locator('[data-testid="panic-button"]')
        expect(btn).to_be_visible()

    def test_panic_button_has_text(self, demo_page):
        """Panic button shows 'MUTE' text."""
        btn = demo_page.locator('[data-testid="panic-button"]')
        expect(btn).to_have_text("MUTE")


# ===========================================================================
# 4. Mode badge and dropdown
# ===========================================================================

class TestModeBadge:
    """Verify the mode badge and mode switcher dropdown."""

    def test_mode_badge_exists(self, demo_page):
        """Mode badge element is present."""
        badge = demo_page.locator("#sb-mode")
        expect(badge).to_be_attached()

    def test_mode_badge_updates_from_ws(self, demo_page):
        """Mode badge updates from '--' after WS data arrives."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_function(
            """() => {
                const el = document.getElementById('sb-mode');
                return el && el.textContent.trim() !== '--';
            }""",
            timeout=WS_DATA_TIMEOUT_MS,
        )

    def test_mode_dropdown_exists(self, demo_page):
        """Mode dropdown with mode options is present (hidden by default)."""
        dropdown = demo_page.locator("#sb-mode-dropdown")
        expect(dropdown).to_be_attached()

        # Should have DJ, Live, Standby options
        options = dropdown.locator(".sb-mode-option")
        assert options.count() >= 3, (
            f"Expected >= 3 mode options, got {options.count()}")


# ===========================================================================
# 5. DSP and pipeline indicators
# ===========================================================================

class TestDSPIndicators:
    """Verify DSP state, quantum, and xrun indicators update."""

    def test_dsp_state_updates(self, demo_page):
        """DSP state indicator updates from '--'."""
        _wait_for_ws_data(demo_page)
        text = demo_page.locator("#sb-dsp-state").text_content().strip()
        assert text != "--", f"DSP state still '--' after WS data"

    def test_quantum_updates(self, demo_page):
        """Quantum indicator updates from '--'."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_function(
            "document.getElementById('sb-quantum').textContent.trim() !== '--'",
            timeout=WS_DATA_TIMEOUT_MS,
        )
        text = demo_page.locator("#sb-quantum").text_content().strip()
        assert text != "--", f"Quantum still '--' after WS data"

    def test_xruns_updates(self, demo_page):
        """Xruns indicator updates from '--'."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_function(
            "document.getElementById('sb-xruns').textContent.trim() !== '--'",
            timeout=WS_DATA_TIMEOUT_MS,
        )

    def test_cpu_gauge_updates(self, demo_page):
        """CPU gauge updates from '--'."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_function(
            "document.getElementById('sb-cpu-gauge-text').textContent.trim() !== '--'",
            timeout=WS_DATA_TIMEOUT_MS,
        )

    def test_temp_gauge_updates(self, demo_page):
        """Temperature gauge updates from '--'."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_function(
            "document.getElementById('sb-temp-gauge-text').textContent.trim() !== '--'",
            timeout=WS_DATA_TIMEOUT_MS,
        )


# ===========================================================================
# 6. Status bar persists across tab switches
# ===========================================================================

class TestStatusBarPersistence:
    """Verify the status bar remains visible and updated across tab changes."""

    def test_status_bar_visible_on_dashboard(self, demo_page):
        """Status bar is visible on the dashboard tab."""
        expect(demo_page.locator("#status-bar")).to_be_visible()

    def test_status_bar_visible_on_system_tab(self, demo_page):
        """Status bar remains visible after switching to system tab."""
        _switch_tab(demo_page, "system")
        expect(demo_page.locator("#status-bar")).to_be_visible()
        expect(demo_page.locator('[data-testid="panic-button"]')).to_be_visible()

    def test_status_bar_visible_on_graph_tab(self, demo_page):
        """Status bar remains visible after switching to graph tab."""
        _switch_tab(demo_page, "graph")
        expect(demo_page.locator("#status-bar")).to_be_visible()

    def test_status_bar_visible_on_config_tab(self, demo_page):
        """Status bar remains visible after switching to config tab."""
        _switch_tab(demo_page, "config")
        expect(demo_page.locator("#status-bar")).to_be_visible()

    def test_dsp_state_preserved_across_tabs(self, demo_page):
        """DSP state value preserved when switching tabs."""
        _wait_for_ws_data(demo_page)
        dsp_before = demo_page.locator("#sb-dsp-state").text_content().strip()

        _switch_tab(demo_page, "system")
        demo_page.wait_for_timeout(500)

        dsp_after = demo_page.locator("#sb-dsp-state").text_content().strip()
        assert dsp_after != "--", "DSP state reset to '--' after tab switch"
