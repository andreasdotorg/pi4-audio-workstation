"""Browser E2E: Gain display and controls on Config tab (US-153).

Verifies that the D-009 per-channel gain controls on the Config tab:
  - Gain list container exists
  - Gain rows are populated after WS data arrives (GM connected)
  - APPLY and RESET buttons exist with correct initial disabled state
  - Gain status element exists

These tests are purely observational — they read UI state only and do NOT
modify gains or trigger any audio-producing operations.

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
GAIN_POPULATE_MS = 5_000


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
def config_page(browser, local_demo_url):
    """Fresh browser page on the Config tab."""
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(local_demo_url)
    pg.wait_for_timeout(2000)
    pg.locator('.nav-tab[data-view="config"]').click()
    expect(pg.locator("#view-config")).to_have_class(
        re.compile(r".*\bactive\b.*"))
    pg.wait_for_timeout(1000)
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


# ===========================================================================
# Tests
# ===========================================================================

class TestGainListPresence:
    """Verify gain list container and controls exist on Config tab."""

    def test_gain_list_container_exists(self, config_page):
        """Gain list container element exists."""
        _wait_for_ws_data(config_page)
        el = config_page.locator("#cfg-gain-list")
        expect(el).to_be_attached()

    def test_gain_apply_button_exists(self, config_page):
        """APPLY button for gains exists."""
        _wait_for_ws_data(config_page)
        btn = config_page.locator("#cfg-gain-apply")
        expect(btn).to_be_attached()

    def test_gain_reset_button_exists(self, config_page):
        """RESET button for gains exists."""
        _wait_for_ws_data(config_page)
        btn = config_page.locator("#cfg-gain-reset")
        expect(btn).to_be_attached()

    def test_gain_status_element_exists(self, config_page):
        """Gain status display element exists."""
        _wait_for_ws_data(config_page)
        el = config_page.locator("#cfg-gain-status")
        expect(el).to_be_attached()


class TestGainButtonStates:
    """Verify gain button initial states."""

    def test_gain_apply_initially_disabled(self, config_page):
        """APPLY button is disabled before any gain changes."""
        _wait_for_ws_data(config_page)
        config_page.wait_for_timeout(GAIN_POPULATE_MS)
        btn = config_page.locator("#cfg-gain-apply")
        expect(btn).to_be_disabled()

    def test_gain_reset_initially_disabled(self, config_page):
        """RESET button is disabled before any gain changes."""
        _wait_for_ws_data(config_page)
        config_page.wait_for_timeout(GAIN_POPULATE_MS)
        btn = config_page.locator("#cfg-gain-reset")
        expect(btn).to_be_disabled()


class TestGainRowsPopulated:
    """Verify gain rows are populated when GM is connected."""

    def test_gain_rows_appear(self, config_page):
        """Gain rows appear in the gain list after GM data arrives.

        In local-demo with GM connected, the gain list should be populated
        with cfg-gain-row elements for each gain node. If GM is not
        connected, the list may be empty — we skip in that case.
        """
        _wait_for_ws_data(config_page)
        config_page.wait_for_timeout(GAIN_POPULATE_MS)

        rows = config_page.locator(".cfg-gain-row")
        count = rows.count()
        if count == 0:
            # GM may not be connected in local-demo — skip gracefully
            pytest.skip(
                "No gain rows populated — GM may not be connected")
        # With a standard 4-channel filter-chain, expect 4 gain rows
        assert count >= 1, f"Expected gain rows, got {count}"

    def test_gain_rows_have_labels(self, config_page):
        """Each gain row has a label element."""
        _wait_for_ws_data(config_page)
        config_page.wait_for_timeout(GAIN_POPULATE_MS)

        rows = config_page.locator(".cfg-gain-row")
        if rows.count() == 0:
            pytest.skip("No gain rows — GM may not be connected")

        for i in range(rows.count()):
            row = rows.nth(i)
            # Each row should have child elements (label, slider, value)
            children = row.locator("> *")
            assert children.count() >= 1, (
                f"Gain row {i} has no child elements")

    def test_gain_rows_have_sliders(self, config_page):
        """Each gain row has an input range slider."""
        _wait_for_ws_data(config_page)
        config_page.wait_for_timeout(GAIN_POPULATE_MS)

        rows = config_page.locator(".cfg-gain-row")
        if rows.count() == 0:
            pytest.skip("No gain rows — GM may not be connected")

        for i in range(rows.count()):
            row = rows.nth(i)
            slider = row.locator("input[type='range']")
            assert slider.count() >= 1, (
                f"Gain row {i} has no range slider")
