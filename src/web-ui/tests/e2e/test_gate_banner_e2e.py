"""Browser E2E: Gate banner visible across all tabs when closed (US-150).

Verifies that the persistent audio gate banner (US-126) is visible on
every tab when the gate is closed, and hidden when the gate is open.

Usage:
    nix run .#test-e2e    # runs both service-integration and e2e tiers
"""

import json
import os
import re
import socket
import urllib.request

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.browser, pytest.mark.slow]

VENUE_NAME = "local-demo"
WS_DATA_TIMEOUT_MS = 15_000
GATE_SETTLE_MS = 3_000


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


def _api_post(base_url, path, body=None, timeout=10):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


@pytest.fixture()
def demo_page_gate_closed(browser, local_demo_url):
    """Browser page with gate explicitly closed."""
    # Ensure gate is closed via API
    try:
        _api_post(local_demo_url, "/api/v1/venue/gate/close")
    except Exception:
        pass

    context = browser.new_context()
    pg = context.new_page()
    pg.goto(local_demo_url)
    pg.wait_for_timeout(2000)
    yield pg

    # Close gate on teardown
    try:
        _api_post(local_demo_url, "/api/v1/venue/gate/close")
    except Exception:
        pass
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

class TestGateBannerWhenClosed:
    """Verify gate banner visibility when gate is closed."""

    def test_gate_banner_visible_on_dashboard(self, demo_page_gate_closed):
        """Gate banner is visible on dashboard tab when gate is closed."""
        _wait_for_ws_data(demo_page_gate_closed)
        demo_page_gate_closed.wait_for_timeout(GATE_SETTLE_MS)
        banner = demo_page_gate_closed.locator("#gate-banner")
        expect(banner).to_be_attached()
        # Banner display style should not be 'none' when gate is closed
        # The banner might be shown/hidden via display or class
        is_visible = demo_page_gate_closed.evaluate(
            "document.getElementById('gate-banner').style.display !== 'none'")
        assert is_visible, "Gate banner should be visible when gate is closed"

    def test_gate_banner_text_content(self, demo_page_gate_closed):
        """Gate banner shows appropriate closed message."""
        _wait_for_ws_data(demo_page_gate_closed)
        demo_page_gate_closed.wait_for_timeout(GATE_SETTLE_MS)
        banner_text = demo_page_gate_closed.locator(".gate-banner-text")
        if banner_text.count() > 0:
            text = banner_text.text_content().upper()
            assert "GATE" in text or "CLOSED" in text, (
                f"Expected gate/closed in banner text, got '{text}'")

    @pytest.mark.parametrize("tab", ["system", "graph", "config", "measure"])
    def test_gate_banner_visible_on_all_tabs(
            self, demo_page_gate_closed, tab):
        """Gate banner is visible on {tab} tab when gate is closed."""
        _wait_for_ws_data(demo_page_gate_closed)
        demo_page_gate_closed.wait_for_timeout(GATE_SETTLE_MS)
        _switch_tab(demo_page_gate_closed, tab)
        demo_page_gate_closed.wait_for_timeout(500)

        banner = demo_page_gate_closed.locator("#gate-banner")
        expect(banner).to_be_attached()
        is_visible = demo_page_gate_closed.evaluate(
            "document.getElementById('gate-banner').style.display !== 'none'")
        assert is_visible, (
            f"Gate banner should be visible on {tab} tab when closed")


class TestGateBannerWhenOpen:
    """Verify gate banner hidden when gate is open."""

    def test_gate_banner_hidden_when_open(
            self, demo_page_gate_closed, local_demo_url):
        """Gate banner hides when gate is opened via API."""
        _wait_for_ws_data(demo_page_gate_closed)

        # Select venue and open gate
        try:
            _api_post(local_demo_url, "/api/v1/venue/select",
                      {"venue": VENUE_NAME})
            _api_post(local_demo_url, "/api/v1/venue/gate/open")
        except Exception:
            pytest.skip("Could not open gate via API")

        demo_page_gate_closed.wait_for_timeout(GATE_SETTLE_MS)

        banner = demo_page_gate_closed.locator("#gate-banner")
        # Banner should be hidden (display: none) when gate is open
        is_hidden = demo_page_gate_closed.evaluate(
            "document.getElementById('gate-banner').style.display === 'none'")
        assert is_hidden, "Gate banner should be hidden when gate is open"

        # Close gate again for clean teardown
        try:
            _api_post(local_demo_url, "/api/v1/venue/gate/close")
        except Exception:
            pass
