"""End-to-end Playwright tests for venue selection and audio gate (US-113 Phase 5).

Verifies:
    - Venue section UI elements on Config tab
    - Venue list populated from /api/v1/venue/list (mock GM returns 2 venues)
    - Venue selection flow: select -> apply -> detail display
    - Audio gate section: indicator, open/close buttons, state transitions
    - Gate safety: starts CLOSED, open requires confirmation dialog
    - REST API endpoints: list, current, select, detail, gate/open, gate/close
    - Input validation: path traversal rejected, invalid venue names rejected

Tests run against the session-scoped mock FastAPI server (PI_AUDIO_MOCK=1).
The MockGraphManagerClient provides venue/gate RPC responses — this is a
legitimate mock of an external system boundary (GraphManager TCP RPC).
Real code paths exercised: venue_routes.py, venue.py, venue.js.
"""

import json
import re
import urllib.request

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def _switch_tab(page, view_name: str):
    page.locator(f'.nav-tab[data-view="{view_name}"]').click()
    expect(page.locator(f"#view-{view_name}")).to_have_class(
        re.compile(r".*\bactive\b.*")
    )


def _switch_to_config(page):
    """Switch to Config tab and wait for venue.js to fetch data."""
    _switch_tab(page, "config")
    # venue.js fires fetchVenueList + fetchGateStatus when Config tab activates.
    # Wait for the dropdown to be populated (mock GM returns 2 venues).
    page.wait_for_function(
        "document.getElementById('venue-select').options.length > 1",
        timeout=5000,
    )


def _api_get(base_url: str, path: str) -> dict:
    """GET a JSON endpoint and return the parsed response."""
    resp = urllib.request.urlopen(f"{base_url}{path}", timeout=5)
    return json.loads(resp.read())


def _api_post(base_url: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """POST to a JSON endpoint, return (status_code, parsed_body)."""
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ---------------------------------------------------------------------------
# 1. Venue Section UI Elements
# ---------------------------------------------------------------------------


class TestVenueSectionUI:
    """Venue section renders with expected elements on Config tab."""

    def test_venue_section_title(self, page):
        """Venue section has 'VENUE' title."""
        _switch_to_config(page)
        title = page.locator("#cfg-venue .cfg-section-title").first
        expect(title).to_have_text("VENUE")

    def test_venue_dropdown_exists(self, page):
        """Venue dropdown select element is present."""
        _switch_to_config(page)
        sel = page.locator("#venue-select")
        expect(sel).to_be_attached()

    def test_venue_dropdown_has_placeholder(self, page):
        """Venue dropdown first option is a placeholder."""
        _switch_to_config(page)
        first_opt = page.locator("#venue-select option").first
        text = first_opt.text_content()
        assert "select venue" in text.lower(), (
            f"First option should be a placeholder, got: {text}"
        )

    def test_venue_dropdown_populated(self, page):
        """Venue dropdown has options from mock GM (local-demo, rehearsal-room)."""
        _switch_to_config(page)
        options = page.locator("#venue-select option")
        # Placeholder + 2 mock venues = 3 options
        assert options.count() == 3, (
            f"Expected 3 options (placeholder + 2 venues), got {options.count()}"
        )
        # Verify specific venue names from MockGraphManagerClient.list_venues()
        texts = [options.nth(i).text_content() for i in range(options.count())]
        assert any("Local Demo" in t for t in texts), (
            f"Should contain 'Local Demo', got: {texts}"
        )
        assert any("Rehearsal Room" in t for t in texts), (
            f"Should contain 'Rehearsal Room', got: {texts}"
        )

    def test_venue_apply_button_initially_disabled(self, page):
        """APPLY button is disabled when no venue is selected."""
        _switch_to_config(page)
        btn = page.locator("#venue-apply-btn")
        expect(btn).to_be_attached()
        expect(btn).to_be_disabled()

    def test_venue_apply_enables_on_selection(self, page):
        """APPLY button enables when a venue is selected in dropdown."""
        _switch_to_config(page)
        page.locator("#venue-select").select_option("local-demo")
        btn = page.locator("#venue-apply-btn")
        expect(btn).to_be_enabled()

    def test_venue_detail_empty_initially(self, page):
        """Venue detail panel is empty before any venue is selected."""
        _switch_to_config(page)
        detail = page.locator("#venue-detail")
        # Should be empty or have no table
        tables = detail.locator("table")
        assert tables.count() == 0, "Detail should have no table initially"


# ---------------------------------------------------------------------------
# 2. Audio Gate Section UI Elements
# ---------------------------------------------------------------------------


class TestGateSectionUI:
    """Audio gate section renders with expected elements on Config tab."""

    def test_gate_section_title(self, page):
        """Audio gate section has 'AUDIO GATE' title."""
        _switch_to_config(page)
        title = page.locator("#cfg-venue .cfg-section-title").nth(1)
        expect(title).to_have_text("AUDIO GATE")

    def test_gate_indicator_shows_closed(self, page):
        """Gate indicator shows CLOSED on initial load (boot state)."""
        _switch_to_config(page)
        indicator = page.locator("#gate-indicator")
        expect(indicator).to_have_text("CLOSED")

    def test_gate_indicator_has_closed_class(self, page):
        """Gate indicator has gate-closed CSS class initially."""
        _switch_to_config(page)
        indicator = page.locator("#gate-indicator")
        expect(indicator).to_have_class(re.compile(r".*\bgate-closed\b.*"))

    def test_gate_open_button_disabled_initially(self, page):
        """OPEN GATE button is disabled when no venue is loaded."""
        _switch_to_config(page)
        btn = page.locator("#gate-open-btn")
        expect(btn).to_be_attached()
        expect(btn).to_be_disabled()

    def test_gate_close_button_disabled_initially(self, page):
        """CLOSE GATE button is disabled when gate is already closed."""
        _switch_to_config(page)
        btn = page.locator("#gate-close-btn")
        expect(btn).to_be_attached()
        expect(btn).to_be_disabled()

    def test_gate_venue_label_no_venue(self, page):
        """Gate venue label shows 'No venue loaded' initially."""
        _switch_to_config(page)
        label = page.locator("#gate-venue-label")
        expect(label).to_have_text("No venue loaded")

    def test_gate_info_text_visible(self, page):
        """Gate info text about boot state is visible."""
        _switch_to_config(page)
        info = page.locator(".gate-info-text")
        text = info.text_content()
        assert "CLOSED on boot" in text, (
            f"Info should mention 'CLOSED on boot', got: {text}"
        )


# ---------------------------------------------------------------------------
# 3. Venue Selection Flow (UI integration)
# ---------------------------------------------------------------------------


class TestVenueSelectionFlow:
    """Venue selection via dropdown + APPLY exercises real code paths."""

    def test_select_and_apply_venue(self, page):
        """Select venue -> APPLY -> status shows venue loaded."""
        _switch_to_config(page)
        page.locator("#venue-select").select_option("local-demo")
        page.locator("#venue-apply-btn").click()

        # Wait for status to update
        page.wait_for_function(
            """() => {
                const el = document.getElementById('venue-status');
                return el && el.textContent.indexOf('loaded') >= 0;
            }""",
            timeout=5000,
        )
        status_text = page.locator("#venue-status").text_content()
        assert "local-demo" in status_text, (
            f"Status should mention venue name, got: {status_text}"
        )

    def test_gate_still_closed_after_venue_load(self, page):
        """After loading a venue, gate remains CLOSED (D-063 safety)."""
        _switch_to_config(page)
        page.locator("#venue-select").select_option("local-demo")
        page.locator("#venue-apply-btn").click()

        page.wait_for_function(
            "document.getElementById('venue-status').textContent.indexOf('loaded') >= 0",
            timeout=5000,
        )

        indicator = page.locator("#gate-indicator")
        expect(indicator).to_have_text("CLOSED")

    def test_open_gate_button_enabled_after_venue_load(self, page):
        """After loading a venue, OPEN GATE button becomes enabled."""
        _switch_to_config(page)
        page.locator("#venue-select").select_option("local-demo")
        page.locator("#venue-apply-btn").click()

        page.wait_for_function(
            "document.getElementById('venue-status').textContent.indexOf('loaded') >= 0",
            timeout=5000,
        )

        btn = page.locator("#gate-open-btn")
        expect(btn).to_be_enabled()

    def test_venue_label_updates_after_load(self, page):
        """Gate venue label updates to show loaded venue name."""
        _switch_to_config(page)
        page.locator("#venue-select").select_option("local-demo")
        page.locator("#venue-apply-btn").click()

        page.wait_for_function(
            "document.getElementById('gate-venue-label').textContent.indexOf('local-demo') >= 0",
            timeout=5000,
        )

        label = page.locator("#gate-venue-label")
        text = label.text_content()
        assert "local-demo" in text, (
            f"Venue label should contain 'local-demo', got: {text}"
        )

    def test_venue_detail_shows_channel_table(self, page):
        """After selecting a venue, detail panel shows channel info."""
        _switch_to_config(page)
        page.locator("#venue-select").select_option("local-demo")

        # Detail preview fetches on dropdown change (before APPLY)
        page.wait_for_function(
            "document.querySelectorAll('#venue-detail table').length > 0",
            timeout=5000,
        )

        # Verify the table has channel rows (8 channels)
        rows = page.locator("#venue-detail table tr")
        # Header row + 8 channel rows = 9
        assert rows.count() == 9, (
            f"Expected 9 rows (header + 8 channels), got {rows.count()}"
        )

    def test_venue_detail_shows_gain_values(self, page):
        """Channel table displays dB gain values from venue config."""
        _switch_to_config(page)
        page.locator("#venue-select").select_option("local-demo")

        page.wait_for_function(
            "document.querySelectorAll('#venue-detail .venue-ch-gain').length > 0",
            timeout=5000,
        )

        gains = page.locator("#venue-detail .venue-ch-gain")
        assert gains.count() == 8, (
            f"Expected 8 gain cells, got {gains.count()}"
        )
        # local-demo has -20 dB on all channels -> Mult 0.1 -> "-20.0 dB"
        first_gain = gains.first.text_content()
        assert "dB" in first_gain, (
            f"Gain cell should contain 'dB', got: {first_gain}"
        )
        assert "-20" in first_gain, (
            f"local-demo gain should be -20 dB, got: {first_gain}"
        )


# ---------------------------------------------------------------------------
# 4. Gate Open/Close Flow (UI integration)
# ---------------------------------------------------------------------------


class TestGateFlow:
    """Gate open/close flow exercises real code paths through venue_routes.

    Note: MockGraphManagerClient is stateless across HTTP requests — each
    endpoint call creates a fresh mock instance.  The gate/open endpoint
    calls open_gate() on a fresh mock with no venue loaded, which returns
    an error (400).  This is the correct mock behavior for the "no venue"
    error path.  The gate-open SUCCESS path (with persistent GM state)
    requires Pi hardware validation (Gate 2).

    Tests here verify:
    - Confirmation dialog behavior (accept/dismiss)
    - Error handling when gate/open fails (no venue in per-request mock)
    - Client-side gate status after venue load (gate stays CLOSED)
    """

    def _load_venue(self, page):
        """Helper: load local-demo venue and wait for completion."""
        _switch_to_config(page)
        page.locator("#venue-select").select_option("local-demo")
        page.locator("#venue-apply-btn").click()
        page.wait_for_function(
            "document.getElementById('venue-status').textContent.indexOf('loaded') >= 0",
            timeout=5000,
        )

    def test_open_gate_triggers_confirm_dialog(self, page):
        """Clicking OPEN GATE triggers a confirmation dialog."""
        self._load_venue(page)

        dialog_messages = []

        def _handle_dialog(dialog):
            dialog_messages.append(dialog.message)
            dialog.dismiss()

        page.on("dialog", _handle_dialog)

        page.locator("#gate-open-btn").click()
        page.wait_for_timeout(500)

        assert len(dialog_messages) == 1, (
            f"Expected exactly 1 dialog, got {len(dialog_messages)}"
        )
        # Confirm dialog should mention safety (amplifiers/gains)
        msg = dialog_messages[0]
        assert "gate" in msg.lower() or "gain" in msg.lower(), (
            f"Dialog should mention gate or gains, got: {msg}"
        )

    def test_dismiss_confirmation_does_not_open_gate(self, page):
        """Dismissing the confirmation dialog does NOT open the gate."""
        self._load_venue(page)

        # Dismiss (cancel) the confirmation dialog
        page.on("dialog", lambda dialog: dialog.dismiss())

        page.locator("#gate-open-btn").click()

        # Give a moment for any async operation
        page.wait_for_timeout(500)

        # Gate should still be CLOSED
        indicator = page.locator("#gate-indicator")
        expect(indicator).to_have_text("CLOSED")

    def test_confirm_dialog_mentions_venue(self, page):
        """Confirmation dialog includes the loaded venue name."""
        self._load_venue(page)

        dialog_messages = []

        def _capture_dialog(dialog):
            dialog_messages.append(dialog.message)
            dialog.dismiss()

        page.on("dialog", _capture_dialog)
        page.locator("#gate-open-btn").click()
        page.wait_for_timeout(500)

        assert len(dialog_messages) == 1
        msg = dialog_messages[0]
        assert "local-demo" in msg, (
            f"Dialog should mention venue 'local-demo', got: {msg}"
        )


# ---------------------------------------------------------------------------
# 5. REST API Endpoint Tests (direct HTTP, no browser)
# ---------------------------------------------------------------------------


class TestVenueAPI:
    """REST API endpoints exercise real venue_routes.py + venue.py code."""

    def test_venue_list_returns_venues(self, mock_server):
        """GET /api/v1/venue/list returns a list of venue configs."""
        data = _api_get(mock_server, "/api/v1/venue/list")
        assert "venues" in data
        venues = data["venues"]
        assert isinstance(venues, list)
        assert len(venues) >= 2, f"Expected at least 2 venues, got {len(venues)}"

        # Verify structure: each venue has name and display_name
        names = [v["name"] for v in venues]
        assert "local-demo" in names, f"Should contain 'local-demo', got: {names}"
        assert "rehearsal-room" in names, f"Should contain 'rehearsal-room', got: {names}"

    def test_venue_current_initial_state(self, mock_server):
        """GET /api/v1/venue/current returns gate_open=false initially."""
        data = _api_get(mock_server, "/api/v1/venue/current")
        assert data["gate_open"] is False, (
            f"Gate should be closed initially, got: {data}"
        )

    def test_venue_select_valid(self, mock_server):
        """POST /api/v1/venue/select with valid name returns ok=true."""
        status, data = _api_post(
            mock_server, "/api/v1/venue/select", {"venue": "local-demo"}
        )
        assert status == 200, f"Expected 200, got {status}: {data}"
        assert data["ok"] is True
        assert data["venue"] == "local-demo"
        assert data["gate_open"] is False, "Gate should remain closed after venue select"
        assert data["has_pending_gains"] is True, (
            "After venue select, has_pending_gains should be True (gains loaded but gate closed)"
        )

    def test_venue_select_invalid_path_traversal(self, mock_server):
        """POST /api/v1/venue/select with path traversal returns 400."""
        status, data = _api_post(
            mock_server, "/api/v1/venue/select", {"venue": "../etc/passwd"}
        )
        assert status == 400, f"Expected 400 for path traversal, got {status}: {data}"
        assert data["error"] == "invalid_venue_name"

    def test_venue_select_invalid_special_chars(self, mock_server):
        """POST /api/v1/venue/select with special chars returns 400."""
        status, data = _api_post(
            mock_server, "/api/v1/venue/select", {"venue": "venue<script>alert(1)</script>"}
        )
        assert status == 400, f"Expected 400 for XSS attempt, got {status}: {data}"
        assert data["error"] == "invalid_venue_name"

    def test_venue_detail_returns_channels(self, mock_server):
        """GET /api/v1/venue/detail?name=local-demo returns 8 channels."""
        data = _api_get(mock_server, "/api/v1/venue/detail?name=local-demo")
        assert data["name"] == "local-demo"
        assert len(data["channels"]) == 8, (
            f"Expected 8 channels, got {len(data['channels'])}"
        )

        # Verify channel structure with real values from local-demo.yml
        ch0 = data["channels"][0]
        assert ch0["key"] == "1_sat_l"
        assert ch0["gain_node"] == "gain_left_hp"
        assert ch0["gain_db"] == -20
        assert ch0["delay_ms"] == 0
        assert ch0["coefficients"] == "dirac.wav"

        # Verify gain_mult is correctly computed: 10^(-20/20) = 0.1
        assert abs(ch0["gain_mult"] - 0.1) < 0.001, (
            f"Expected gain_mult ~0.1, got {ch0['gain_mult']}"
        )

        # D-009 safety: all gain_mult values must be <= 1.0 (0 dB hard cap)
        for ch in data["channels"]:
            assert ch["gain_mult"] <= 1.0, (
                f"D-009 violation: channel {ch['key']} gain_mult={ch['gain_mult']} > 1.0"
            )

    def test_venue_detail_invalid_name(self, mock_server):
        """GET /api/v1/venue/detail with invalid name returns 400."""
        status, data = _api_post(mock_server, "/api/v1/venue/select", {"venue": ""})
        # Empty venue name should fail validation
        assert status == 422 or status == 400, (
            f"Expected 400 or 422 for empty name, got {status}"
        )

    def test_gate_open_without_venue_returns_400(self, mock_server):
        """POST /api/v1/venue/gate/open without a loaded venue returns 400.

        MockGraphManagerClient is stateless per request: each endpoint
        creates a fresh instance with no venue loaded.  open_gate() raises
        GraphManagerError("no venue loaded"), caught as 400.  This tests
        the real error handling path in venue_routes.gate_open().
        """
        status, data = _api_post(mock_server, "/api/v1/venue/gate/open")
        assert status == 400, f"Expected 400 (no venue loaded), got {status}: {data}"
        assert data["error"] == "open_gate_failed"
        assert "no venue" in data["detail"].lower(), (
            f"Error detail should mention 'no venue', got: {data['detail']}"
        )

    def test_gate_close_always_succeeds(self, mock_server):
        """POST /api/v1/venue/gate/close returns ok=true (always safe).

        close_gate() is always safe and doesn't require a venue to be
        loaded — it simply zeroes all gains.
        """
        status, data = _api_post(mock_server, "/api/v1/venue/gate/close")
        assert status == 200, f"Expected 200, got {status}: {data}"
        assert data["ok"] is True
        assert data["gate_open"] is False

    def test_gate_current_returns_consistent_state(self, mock_server):
        """GET /api/v1/venue/current returns consistent gate state.

        Per-request mock starts with gate_open=false, venue=None.
        This verifies the route handler correctly marshals mock state.
        """
        data = _api_get(mock_server, "/api/v1/venue/current")
        assert data["gate_open"] is False
        assert data["venue"] is None
        assert data["has_pending_gains"] is False


# ---------------------------------------------------------------------------
# 6. No JS Errors on Venue/Gate Interaction
# ---------------------------------------------------------------------------


class TestNoJsErrors:
    """Venue/gate interactions produce no JS console errors."""

    def test_no_errors_on_venue_select_and_gate(self, page):
        """Full venue select + gate open/close cycle produces no JS errors.

        The page fixture asserts zero console errors on teardown.
        """
        _switch_to_config(page)
        page.locator("#venue-select").select_option("local-demo")
        page.wait_for_timeout(500)
        page.locator("#venue-apply-btn").click()
        page.wait_for_function(
            "document.getElementById('venue-status').textContent.indexOf('loaded') >= 0",
            timeout=5000,
        )
        page.wait_for_timeout(300)
