"""Browser E2E tests for measurement flow against a running local-demo stack.

Playwright browser tests that verify the measurement UI loads, shows correct
state, and can drive a full measurement session through browser interaction.

API-only tests (server health, API-driven session, post-hoc artifact
validation) have been moved to tests/service-integration/test_measurement.py
(F-284).

Usage:
    nix run .#test-e2e    # runs both service-integration and e2e tiers
"""

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.browser, pytest.mark.slow]

SCREENSHOTS_DIR = Path("/tmp/pi4audio-e2e-screenshots/local-demo")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

GAIN_CAL_TIMEOUT = 90_000
SESSION_TIMEOUT = 600_000
STATE_TIMEOUT = 10_000

PROFILE_NAME = "2way-80hz-sealed"
VENUE_NAME = "local-demo"


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
    _wait_for_idle_or_abort(local_demo_url, timeout_s=30)

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

    _switch_tab(pg, "measure")
    pg.wait_for_timeout(500)
    for terminal_id in ("#mw-complete", "#mw-error", "#mw-aborted"):
        screen = pg.locator(terminal_id)
        if screen.count() > 0:
            ret_btn = screen.locator(".mw-return-btn")
            if ret_btn.count() > 0 and ret_btn.is_visible():
                ret_btn.click()
                pg.wait_for_timeout(500)
                break

    yield pg
    context.close()
    real_errors = [
        e for e in console_errors
        if "/ws/siggen" not in e and "WebSocket" not in e
    ]
    if real_errors:
        print(f"[local-demo E2E] JS console errors (non-fatal): {real_errors}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _screenshot(page, name: str) -> None:
    page.screenshot(path=str(SCREENSHOTS_DIR / name))


def _switch_tab(page, view_name: str):
    page.locator(f'.nav-tab[data-view="{view_name}"]').click()
    expect(page.locator(f"#view-{view_name}")).to_have_class(
        re.compile(r".*\bactive\b.*"))


def _wait_for_state(page, state, *, timeout=SESSION_TIMEOUT):
    expected_text = state.upper().replace("_", " ")
    try:
        page.wait_for_function(
            """(expected) => {
                const el = document.querySelector('[data-testid="measurement-state"]');
                return el && el.textContent === expected;
            }""",
            arg=expected_text,
            timeout=timeout,
        )
    except Exception:
        actual = page.locator('[data-testid="measurement-state"]').text_content()
        raise TimeoutError(
            f"Timed out waiting for state '{expected_text}' "
            f"(current: '{actual}', timeout: {timeout}ms)"
        )


def _wait_for_non_idle(page, *, timeout=STATE_TIMEOUT):
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[data-testid="measurement-state"]');
            return el && el.textContent !== 'IDLE' && el.textContent !== '--';
        }""",
        timeout=timeout,
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


def _wait_for_idle_or_abort(base_url, timeout_s=30):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            data = _api_get(base_url, "/api/v1/measurement/status")
            state = data.get("state", "")
            if state in ("idle", "complete", "error", "aborted"):
                return
            if state in ("setup", "gain_cal", "measuring", "filter_gen",
                         "deploy", "verify"):
                try:
                    _api_post(base_url, "/api/v1/measurement/abort")
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(1)


def _ensure_gate_open(base_url, venue=VENUE_NAME):
    data = json.dumps({"venue": venue}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/v1/venue/select",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=10)
    result = json.loads(resp.read())
    assert result.get("ok"), f"Venue select failed: {result}"

    req = urllib.request.Request(
        f"{base_url}/api/v1/venue/gate/open",
        data=b"",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=10)
    result = json.loads(resp.read())
    assert result.get("gate_open"), f"Gate open failed: {result}"


# ===========================================================================
# Phase 2: Browser UI loads and shows correct state
# ===========================================================================

class TestLocalDemoBrowserUI:
    """Verify the browser UI loads against local-demo."""

    def test_dashboard_loads(self, demo_page):
        """Dashboard tab loads with live data from local-demo."""
        _screenshot(demo_page, "ld-01-dashboard.png")
        dsp_state = demo_page.locator("#sb-dsp-state")
        expect(dsp_state).to_be_attached()

    def test_measure_tab_idle(self, demo_page):
        """Measure tab shows IDLE state."""
        _switch_tab(demo_page, "measure")
        badge = demo_page.locator('[data-testid="measurement-state"]')
        expect(badge).to_be_attached()
        expect(badge).to_have_text("IDLE")
        _screenshot(demo_page, "ld-02-measure-idle.png")

    def test_profile_dropdown_has_options(self, demo_page):
        """Measure tab profile dropdown is populated from seeded data."""
        _switch_tab(demo_page, "measure")
        demo_page.wait_for_timeout(1500)
        select = demo_page.locator("#mw-setup-profile")
        expect(select).to_be_attached()
        options_count = select.locator("option").count()
        assert options_count > 1, (
            f"Expected > 1 profile options, got {options_count}")


# ===========================================================================
# Phase 4: Full measurement session via browser
# ===========================================================================

class TestLocalDemoMeasurementBrowser:
    """Drive a full measurement session through the browser UI."""

    @pytest.mark.xfail(
        reason="F-262: session starts (F-285 signal-gen fix works) but ends "
               "in ERROR — room-sim IRs fail filter verification (min-phase "
               "check). Same root cause as API test.",
        strict=False,
    )
    def test_full_session_browser(self, demo_page, local_demo_url):
        """Click START, wait for COMPLETE — full E2E through browser."""
        _ensure_gate_open(local_demo_url)

        _switch_tab(demo_page, "measure")

        idle_screen = demo_page.locator("#mw-idle")
        expect(idle_screen).to_be_visible(timeout=5000)

        demo_page.evaluate("""() => {
            var sel = document.getElementById('mw-setup-profile');
            if (sel) {
                for (var i = 0; i < sel.options.length; i++) {
                    if (sel.options[i].value === '%s') {
                        sel.selectedIndex = i;
                        sel.dispatchEvent(new Event('change'));
                        break;
                    }
                }
            }
            var pos = document.getElementById('mw-setup-positions');
            if (pos) pos.value = '1';
        }""" % PROFILE_NAME)
        demo_page.wait_for_timeout(1000)

        start_btn = demo_page.locator('[data-testid="start-measurement"]')
        expect(start_btn).to_be_visible(timeout=3000)
        start_btn.click()

        _screenshot(demo_page, "ld-03-session-started.png")

        _wait_for_non_idle(demo_page, timeout=STATE_TIMEOUT)

        abort_btn = demo_page.locator('[data-testid="abort-measurement"]')
        expect(abort_btn).not_to_have_class(re.compile(r".*\bhidden\b.*"))

        _screenshot(demo_page, "ld-04-gain-cal.png")

        _wait_for_state(demo_page, "complete", timeout=SESSION_TIMEOUT)

        badge = demo_page.locator('[data-testid="measurement-state"]')
        expect(badge).to_have_text("COMPLETE")

        complete_screen = demo_page.locator("#mw-complete")
        expect(complete_screen).not_to_have_class(
            re.compile(r".*\bhidden\b.*"))

        _screenshot(demo_page, "ld-05-session-complete.png")
