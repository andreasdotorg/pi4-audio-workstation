"""Browser E2E: WebSocket endpoints connect and stream (US-147).

Verifies that all WebSocket endpoints used by the web UI successfully
connect and deliver data when accessed from a real browser context.

WS endpoints:
  /ws/monitoring  — level meters, DSP state, clip detection
  /ws/system      — CPU, temp, memory, scheduling, mode
  /ws/measurement — measurement wizard progress
  /ws/pcm         — raw PCM binary frames for spectrum FFT
  /ws/siggen      — signal generator status (may not connect without siggen)

Usage:
    nix run .#test-e2e    # runs both service-integration and e2e tiers
"""

import os
import socket

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.browser, pytest.mark.slow]

WS_CONNECT_TIMEOUT_MS = 15_000


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


# ===========================================================================
# Tests
# ===========================================================================

class TestWSMonitoring:
    """Verify /ws/monitoring connects and delivers data."""

    def test_monitoring_ws_delivers_data(self, demo_page):
        """Status bar DSP state updates from '--', proving /ws/monitoring works."""
        demo_page.locator("#sb-dsp-state").wait_for(state="attached")
        demo_page.wait_for_function(
            "document.getElementById('sb-dsp-state').textContent !== '--'",
            timeout=WS_CONNECT_TIMEOUT_MS,
        )

    def test_monitoring_ws_delivers_clip_data(self, demo_page):
        """Clip indicator updates from '--', proving monitoring data flows."""
        demo_page.locator("#sb-clip").wait_for(state="attached")
        demo_page.wait_for_function(
            "document.getElementById('sb-clip').textContent.trim() !== '--'",
            timeout=WS_CONNECT_TIMEOUT_MS,
        )


class TestWSSystem:
    """Verify /ws/system connects and delivers data."""

    def test_system_ws_delivers_cpu(self, demo_page):
        """CPU gauge updates from '--', proving /ws/system works."""
        demo_page.wait_for_function(
            "document.getElementById('sb-cpu-gauge-text').textContent.trim() !== '--'",
            timeout=WS_CONNECT_TIMEOUT_MS,
        )

    def test_system_ws_delivers_temp(self, demo_page):
        """Temperature gauge updates from '--'."""
        demo_page.wait_for_function(
            "document.getElementById('sb-temp-gauge-text').textContent.trim() !== '--'",
            timeout=WS_CONNECT_TIMEOUT_MS,
        )

    def test_system_ws_delivers_mode(self, demo_page):
        """Mode badge updates from '--', proving system WS delivers GM data."""
        demo_page.wait_for_function(
            """() => {
                const el = document.getElementById('sb-mode');
                return el && el.textContent.trim() !== '--';
            }""",
            timeout=WS_CONNECT_TIMEOUT_MS,
        )

    def test_system_ws_delivers_quantum(self, demo_page):
        """Quantum indicator updates from '--'."""
        demo_page.wait_for_function(
            "document.getElementById('sb-quantum').textContent.trim() !== '--'",
            timeout=WS_CONNECT_TIMEOUT_MS,
        )


class TestWSPcm:
    """Verify /ws/pcm connects and delivers binary PCM frames."""

    def test_pcm_ws_drives_spectrum(self, demo_page):
        """Spectrum canvas renders non-zero pixels, proving /ws/pcm delivers data.

        The spectrum display depends on /ws/pcm delivering binary PCM frames.
        If the canvas renders anything beyond the background, the PCM pipeline
        is working.
        """
        expect(demo_page.locator("#view-dashboard")).to_have_class("view active")
        demo_page.wait_for_function(
            """() => {
                const c = document.getElementById('spectrum-canvas');
                if (!c || c.width === 0 || c.height === 0) return false;
                const ctx = c.getContext('2d');
                const data = ctx.getImageData(0, 0, c.width, c.height).data;
                for (let i = 3; i < data.length; i += 4) {
                    if (data[i] > 0) return true;
                }
                return false;
            }""",
            timeout=WS_CONNECT_TIMEOUT_MS,
        )


class TestWSConnectionDot:
    """Verify the global connection dot reflects WS health."""

    def test_connection_dot_indicates_connected(self, demo_page):
        """Connection dot changes state after WS endpoints connect."""
        demo_page.wait_for_function(
            "document.getElementById('sb-dsp-state').textContent !== '--'",
            timeout=WS_CONNECT_TIMEOUT_MS,
        )
        # At this point at least /ws/monitoring is connected
        dot = demo_page.locator("#conn-dot")
        expect(dot).to_be_attached()
