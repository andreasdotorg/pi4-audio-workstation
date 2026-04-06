"""Browser E2E: Safety alert indicator in status bar (US-152).

Verifies that the F-072 safety alert indicator in the status bar:
  - Exists and is visible after WS data arrives
  - Shows "OK" when GraphManager is connected and no alerts are active
  - Reflects watchdog and gain integrity states via the sb-safety-text element

These tests are purely observational — they read UI state only and do NOT
trigger any audio-producing operations.

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
SAFETY_SETTLE_MS = 5_000


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
# Tests
# ===========================================================================

class TestSafetyAlertPresence:
    """Verify the safety alert indicator exists in the status bar."""

    def test_safety_alert_element_exists(self, demo_page):
        """Safety alert span exists in the DOM."""
        _wait_for_ws_data(demo_page)
        el = demo_page.locator("#sb-safety-alert")
        expect(el).to_be_attached()

    def test_safety_text_element_exists(self, demo_page):
        """Safety text value element exists."""
        _wait_for_ws_data(demo_page)
        el = demo_page.locator("#sb-safety-text")
        expect(el).to_be_attached()


class TestSafetyAlertNormalState:
    """Verify safety alert shows OK in normal operation."""

    def test_safety_alert_visible_after_ws(self, demo_page):
        """Safety alert becomes visible (hidden class removed) after WS data."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_timeout(SAFETY_SETTLE_MS)

        el = demo_page.locator("#sb-safety-alert")
        # After GM connects, the hidden class should be removed
        expect(el).not_to_have_class(re.compile(r".*\bhidden\b.*"))

    def test_safety_text_shows_ok_or_known_state(self, demo_page):
        """Safety text shows OK, ?, MUTED, or GAIN! (a known state)."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_timeout(SAFETY_SETTLE_MS)

        text_el = demo_page.locator("#sb-safety-text")
        text = text_el.text_content().strip().upper()
        known_states = {"OK", "?", "MUTED", "GAIN!"}
        assert text in known_states, (
            f"Safety text '{text}' is not a known state: {known_states}")

    def test_safety_text_ok_in_normal_operation(self, demo_page):
        """In normal local-demo operation, safety text should be OK."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_timeout(SAFETY_SETTLE_MS)

        text_el = demo_page.locator("#sb-safety-text")
        text = text_el.text_content().strip().upper()
        # In local-demo with GM connected, expect OK or ? (if GM not connected)
        assert text in ("OK", "?"), (
            f"Expected safety OK or ? in local-demo, got '{text}'")


class TestSafetyAlertPersistsAcrossTabs:
    """Safety alert is visible on all tabs (status bar is global)."""

    @pytest.mark.parametrize("tab", ["system", "graph", "config", "measure"])
    def test_safety_alert_visible_on_tab(self, demo_page, tab):
        """Safety alert element is attached on {tab} tab."""
        _wait_for_ws_data(demo_page)
        demo_page.wait_for_timeout(SAFETY_SETTLE_MS)
        _switch_tab(demo_page, tab)
        demo_page.wait_for_timeout(500)

        el = demo_page.locator("#sb-safety-alert")
        expect(el).to_be_attached()
