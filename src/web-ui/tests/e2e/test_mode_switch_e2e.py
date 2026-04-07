"""Browser E2E: Mode switching via browser dropdown (US-149).

Verifies that clicking the mode badge opens a dropdown and switching
modes through the browser UI updates the mode badge and quantum display.

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

WS_DATA_TIMEOUT_MS = 15_000
MODE_CHANGE_TIMEOUT_MS = 15_000


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


def _set_mode_api(base_url, mode):
    """Set mode via test-tool API."""
    try:
        data = json.dumps({"mode": mode}).encode()
        if mode == "measurement":
            req = urllib.request.Request(
                f"{base_url}/api/v1/test-tool/ensure-measurement-mode",
                data=b"",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        else:
            req = urllib.request.Request(
                f"{base_url}/api/v1/test-tool/restore-mode",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code == 502:
            pytest.skip("GM not connected -- cannot switch mode")
        raise


@pytest.fixture(autouse=True)
def _ensure_standby(local_demo_url):
    """Ensure standby mode before and after each test."""
    _set_mode_api(local_demo_url, "standby")
    yield
    _set_mode_api(local_demo_url, "standby")


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


def _wait_for_mode_badge(page, expected_mode, timeout_ms=MODE_CHANGE_TIMEOUT_MS):
    expected_upper = expected_mode.upper()
    page.wait_for_function(
        f"""() => {{
            const el = document.getElementById('sb-mode');
            return el && el.textContent.trim().toUpperCase() === '{expected_upper}';
        }}""",
        timeout=timeout_ms,
    )


# ===========================================================================
# Tests
# ===========================================================================

class TestModeDropdown:
    """Verify mode dropdown opens and contains mode options."""

    def test_mode_badge_clickable(self, demo_page):
        """Clicking the mode badge opens the dropdown."""
        _wait_for_ws_data(demo_page)
        _wait_for_mode_badge(demo_page, "standby")

        badge = demo_page.locator("#sb-mode")
        badge.click()
        demo_page.wait_for_timeout(500)

        dropdown = demo_page.locator("#sb-mode-dropdown")
        # Dropdown should become visible (remove 'hidden' class)
        expect(dropdown).not_to_have_class(re.compile(r".*\bhidden\b.*"))

    def test_dropdown_has_dj_live_standby(self, demo_page):
        """Dropdown contains DJ, Live, and Standby options."""
        _wait_for_ws_data(demo_page)

        badge = demo_page.locator("#sb-mode")
        badge.click()
        demo_page.wait_for_timeout(500)

        for mode in ("dj", "live", "standby"):
            option = demo_page.locator(f'.sb-mode-option[data-mode="{mode}"]')
            expect(option).to_be_attached()


class TestModeSwitchViaBrowser:
    """Verify mode switches through the browser dropdown update the badge."""

    def test_switch_to_dj_via_dropdown(self, demo_page):
        """Clicking DJ in dropdown updates mode badge to DJ."""
        _wait_for_ws_data(demo_page)
        _wait_for_mode_badge(demo_page, "standby")

        # Open dropdown
        demo_page.locator("#sb-mode").click()
        demo_page.wait_for_timeout(500)

        # Click DJ option
        demo_page.locator('.sb-mode-option[data-mode="dj"]').click()

        _wait_for_mode_badge(demo_page, "dj")
        text = demo_page.locator("#sb-mode").text_content().strip().upper()
        assert text == "DJ", f"Expected 'DJ', got '{text}'"

    def test_switch_to_live_via_dropdown(self, demo_page):
        """Clicking Live in dropdown updates mode badge to LIVE."""
        _wait_for_ws_data(demo_page)
        _wait_for_mode_badge(demo_page, "standby")

        demo_page.locator("#sb-mode").click()
        demo_page.wait_for_timeout(500)
        demo_page.locator('.sb-mode-option[data-mode="live"]').click()

        _wait_for_mode_badge(demo_page, "live")
        text = demo_page.locator("#sb-mode").text_content().strip().upper()
        assert text == "LIVE", f"Expected 'LIVE', got '{text}'"

    def test_switch_dj_then_standby_via_dropdown(self, demo_page):
        """Full cycle: standby -> DJ -> standby via dropdown."""
        _wait_for_ws_data(demo_page)
        _wait_for_mode_badge(demo_page, "standby")

        # Switch to DJ
        demo_page.locator("#sb-mode").click()
        demo_page.wait_for_timeout(500)
        demo_page.locator('.sb-mode-option[data-mode="dj"]').click()
        _wait_for_mode_badge(demo_page, "dj")

        # Switch back to standby
        demo_page.locator("#sb-mode").click()
        demo_page.wait_for_timeout(500)
        demo_page.locator('.sb-mode-option[data-mode="standby"]').click()
        _wait_for_mode_badge(demo_page, "standby")

        text = demo_page.locator("#sb-mode").text_content().strip().upper()
        assert text == "STANDBY", f"Expected 'STANDBY', got '{text}'"
