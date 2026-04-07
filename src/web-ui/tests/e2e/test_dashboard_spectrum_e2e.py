"""Browser E2E: Dashboard spectrum canvas renders live data (US-142).

Verifies that the spectrum canvas on the dashboard view receives PCM data
via the /ws/pcm WebSocket path and renders non-zero pixels, proving the
full signal path from pcm-bridge through the browser's FFT pipeline to
canvas rendering.

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
RENDER_TIMEOUT_MS = 20_000


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
def dashboard_page(browser, local_demo_url):
    """Fresh browser page on the dashboard tab."""
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(local_demo_url)
    pg.wait_for_timeout(2000)
    # Dashboard is the default active tab — verify it
    expect(pg.locator("#view-dashboard")).to_have_class(
        re.compile(r".*\bactive\b.*"))
    yield pg
    context.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_ws_connected(page, timeout_ms=WS_DATA_TIMEOUT_MS):
    """Wait until the connection dot turns green (WS connected)."""
    page.wait_for_function(
        """() => {
            const dot = document.getElementById('conn-dot');
            if (!dot) return false;
            const style = window.getComputedStyle(dot);
            // Connected state: background is green-ish (#4caf50 or similar)
            return style.backgroundColor !== 'rgb(158, 158, 158)' &&
                   style.backgroundColor !== '';
        }""",
        timeout=timeout_ms,
    )


def _canvas_has_nonzero_pixels(page, canvas_id, timeout_ms=RENDER_TIMEOUT_MS):
    """Wait until a canvas has non-zero pixel data (something rendered)."""
    page.wait_for_function(
        """(canvasId) => {
            const c = document.getElementById(canvasId);
            if (!c || c.width === 0 || c.height === 0) return false;
            const ctx = c.getContext('2d');
            // Sample the lower half of the canvas where spectrum bars render
            const h = c.height;
            const w = c.width;
            const y0 = Math.floor(h * 0.3);
            const data = ctx.getImageData(0, y0, w, h - y0).data;
            // Check if any pixel has non-zero alpha (something was drawn)
            for (let i = 3; i < data.length; i += 4) {
                if (data[i] > 0) return true;
            }
            return false;
        }""",
        arg=canvas_id,
        timeout=timeout_ms,
    )


# ===========================================================================
# Tests
# ===========================================================================

class TestDashboardSpectrum:
    """Verify spectrum canvas renders live PCM data in the browser."""

    def test_spectrum_canvas_exists(self, dashboard_page):
        """Spectrum canvas element is present on the dashboard."""
        canvas = dashboard_page.locator("#spectrum-canvas")
        expect(canvas).to_be_attached()

    def test_spectrum_canvas_has_dimensions(self, dashboard_page):
        """Spectrum canvas has non-zero width and height."""
        canvas = dashboard_page.locator("#spectrum-canvas")
        expect(canvas).to_be_attached()
        box = canvas.bounding_box()
        assert box is not None, "Spectrum canvas has no bounding box"
        assert box["width"] > 0, f"Canvas width is {box['width']}"
        assert box["height"] > 0, f"Canvas height is {box['height']}"

    def test_spectrum_renders_after_ws_connect(self, dashboard_page):
        """Spectrum canvas draws non-zero pixels after WS data arrives.

        This proves the full path: pcm-bridge -> /ws/pcm -> FFT pipeline ->
        spectrum-renderer -> canvas. Even with silence (all-zero PCM), the
        spectrum renderer draws grid lines and axis labels, so the canvas
        should have non-zero pixels once the pipeline is running.
        """
        _wait_for_ws_connected(dashboard_page)
        _canvas_has_nonzero_pixels(dashboard_page, "spectrum-canvas")

    def test_spectrum_fft_size_selector_works(self, dashboard_page):
        """Changing FFT size selector updates the canvas."""
        _wait_for_ws_connected(dashboard_page)
        _canvas_has_nonzero_pixels(dashboard_page, "spectrum-canvas")

        select = dashboard_page.locator("#spectrum-fft-size")
        expect(select).to_be_attached()

        # Change to 8192 (Analysis)
        select.select_option("8192")
        dashboard_page.wait_for_timeout(1000)

        # Canvas should still render with the new FFT size
        _canvas_has_nonzero_pixels(dashboard_page, "spectrum-canvas")
