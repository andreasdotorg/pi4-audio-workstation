"""Browser E2E: Config tab gain and quantum display (US-145).

Verifies that the Config tab renders gain controls, quantum buttons,
and filter chain info from the running local-demo stack.

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
def config_page(browser, local_demo_url):
    """Fresh browser page on the Config tab."""
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(local_demo_url)
    pg.wait_for_timeout(2000)
    # Switch to config tab
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
    """Wait until WebSocket delivers data."""
    page.locator("#sb-dsp-state").wait_for(state="attached")
    page.wait_for_function(
        "document.getElementById('sb-dsp-state').textContent !== '--'",
        timeout=timeout_ms,
    )


# ===========================================================================
# 1. Gain controls
# ===========================================================================

class TestConfigGainControls:
    """Verify gain control elements on the Config tab."""

    def test_gain_list_exists(self, config_page):
        """Gain list container is present."""
        expect(config_page.locator("#cfg-gain-list")).to_be_attached()

    def test_gain_list_populated(self, config_page):
        """Gain list has channel entries after WS data arrives."""
        _wait_for_ws_data(config_page)
        config_page.wait_for_timeout(2000)
        gain_list = config_page.locator("#cfg-gain-list")
        # Gain items are dynamically populated by config.js
        children = gain_list.locator("> *")
        assert children.count() >= 1, (
            "Expected at least 1 gain channel entry")

    def test_gain_apply_button_exists(self, config_page):
        """APPLY button for gain changes is present."""
        btn = config_page.locator("#cfg-gain-apply")
        expect(btn).to_be_attached()

    def test_gain_reset_button_exists(self, config_page):
        """RESET button for gain changes is present."""
        btn = config_page.locator("#cfg-gain-reset")
        expect(btn).to_be_attached()


# ===========================================================================
# 2. Quantum controls
# ===========================================================================

class TestConfigQuantumControls:
    """Verify quantum selector buttons on the Config tab."""

    def test_quantum_buttons_exist(self, config_page):
        """Quantum button container has 256/512/1024 options."""
        btns = config_page.locator("#cfg-quantum-btns .cfg-quantum-btn")
        assert btns.count() >= 3, (
            f"Expected >= 3 quantum buttons, got {btns.count()}")

    def test_quantum_256_button(self, config_page):
        """256 quantum button exists with correct data attribute."""
        btn = config_page.locator('.cfg-quantum-btn[data-q="256"]')
        expect(btn).to_be_attached()

    def test_quantum_1024_button(self, config_page):
        """1024 quantum button exists with correct data attribute."""
        btn = config_page.locator('.cfg-quantum-btn[data-q="1024"]')
        expect(btn).to_be_attached()

    def test_quantum_latency_display(self, config_page):
        """Latency display element exists."""
        latency = config_page.locator("#cfg-quantum-latency")
        expect(latency).to_be_attached()


# ===========================================================================
# 3. Filter chain info
# ===========================================================================

class TestConfigFilterChainInfo:
    """Verify filter chain information display."""

    def test_filter_chain_node_element(self, config_page):
        """Filter chain node ID element exists."""
        expect(config_page.locator("#cfg-fc-node")).to_be_attached()

    def test_filter_chain_id_element(self, config_page):
        """Filter chain PW ID element exists."""
        expect(config_page.locator("#cfg-fc-id")).to_be_attached()

    def test_filter_chain_info_updates(self, config_page):
        """Filter chain info updates from '--' after WS data."""
        _wait_for_ws_data(config_page)
        config_page.wait_for_function(
            "document.getElementById('cfg-fc-node').textContent.trim() !== '--'",
            timeout=WS_DATA_TIMEOUT_MS,
        )


# ===========================================================================
# 4. Venue section
# ===========================================================================

class TestConfigVenueSection:
    """Verify venue selection elements on the Config tab."""

    def test_venue_select_exists(self, config_page):
        """Venue selection dropdown is present."""
        expect(config_page.locator("#venue-select")).to_be_attached()

    def test_gate_indicator_exists(self, config_page):
        """Gate indicator element is present."""
        expect(config_page.locator("#gate-indicator")).to_be_attached()

    def test_gate_open_button_exists(self, config_page):
        """OPEN GATE button is present."""
        expect(config_page.locator("#gate-open-btn")).to_be_attached()

    def test_gate_close_button_exists(self, config_page):
        """CLOSE GATE button is present."""
        expect(config_page.locator("#gate-close-btn")).to_be_attached()
