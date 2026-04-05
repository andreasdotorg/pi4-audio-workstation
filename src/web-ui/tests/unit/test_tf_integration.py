"""Integration tests for transfer function REST and WebSocket endpoints (US-120 T-120-07).

Tests the /api/v1/tf/* REST endpoints and /ws/transfer-function WebSocket
against the live FastAPI app in mock mode (PI_AUDIO_MOCK=1).

Uses the shared ``client`` fixture from conftest.py which runs the full app
lifespan (startup + shutdown).

F-270: Added TestTfMockFallback to exercise the real-mode code path when
PCM sources are missing.
"""

import json

import pytest

import app.transfer_function_routes as tf_routes


class TestTfModeEndpoints:
    """REST endpoint tests for /api/v1/tf/*."""

    def test_get_mode_returns_initial_state(self, client):
        resp = client.get("/api/v1/tf/mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False
        assert data["filter_mode"] == "design"
        assert data["previous_gm_mode"] is None

    def test_set_mode_design(self, client):
        resp = client.post(
            "/api/v1/tf/mode",
            json={"filter_mode": "design"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filter_mode"] == "design"

    def test_set_mode_verify(self, client):
        resp = client.post(
            "/api/v1/tf/mode",
            json={"filter_mode": "verify"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filter_mode"] == "verify"
        assert data["switched"] is True

    def test_set_mode_invalid_returns_400(self, client):
        resp = client.post(
            "/api/v1/tf/mode",
            json={"filter_mode": "invalid"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_filter_mode"

    def test_set_mode_invalid_json_returns_400(self, client):
        resp = client.post(
            "/api/v1/tf/mode",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_start_requires_confirmation(self, client):
        """POST /api/v1/tf/start without confirmed=true returns 400 (S-012)."""
        resp = client.post(
            "/api/v1/tf/start",
            json={},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "confirmation_required"

    def test_start_with_confirmation(self, client):
        """POST /api/v1/tf/start with confirmed=true activates measurement."""
        resp = client.post(
            "/api/v1/tf/start",
            json={"confirmed": True, "filter_mode": "design"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["filter_mode"] == "design"

    def test_start_then_get_mode_shows_active(self, client):
        """After start, GET /mode shows active=true."""
        client.post("/api/v1/tf/start", json={"confirmed": True})
        resp = client.get("/api/v1/tf/mode")
        assert resp.json()["active"] is True

    def test_stop_deactivates(self, client):
        """POST /api/v1/tf/stop deactivates measurement."""
        # Activate first.
        client.post("/api/v1/tf/start", json={"confirmed": True})
        # Stop.
        resp = client.post("/api/v1/tf/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False

    def test_stop_when_not_active(self, client):
        """Stopping when not active returns success with message."""
        # Ensure stopped state.
        client.post("/api/v1/tf/stop")
        resp = client.post("/api/v1/tf/stop")
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_start_preserves_previous_mode(self, client):
        """Starting measurement saves the previous GM mode for restoration."""
        resp = client.post(
            "/api/v1/tf/start",
            json={"confirmed": True},
        )
        data = resp.json()
        # In mock mode, the default GM mode is "standby".
        assert data["previous_gm_mode"] is not None

    def test_mode_switch_round_trip(self, client):
        """Switch design -> verify -> design and verify state is correct."""
        client.post("/api/v1/tf/mode", json={"filter_mode": "design"})
        resp = client.get("/api/v1/tf/mode")
        assert resp.json()["filter_mode"] == "design"

        client.post("/api/v1/tf/mode", json={"filter_mode": "verify"})
        resp = client.get("/api/v1/tf/mode")
        assert resp.json()["filter_mode"] == "verify"

        client.post("/api/v1/tf/mode", json={"filter_mode": "design"})
        resp = client.get("/api/v1/tf/mode")
        assert resp.json()["filter_mode"] == "design"


class TestTfWebSocket:
    """WebSocket tests for /ws/transfer-function."""

    def test_ws_connects_and_receives_frame(self, client):
        """WebSocket connects in mock mode and receives a JSON frame."""
        with client.websocket_connect("/ws/transfer-function") as ws:
            raw = ws.receive_text()
            frame = json.loads(raw)
            # Verify required fields from TransferFunctionResult.to_json_dict().
            assert "magnitude_db" in frame
            assert "phase_deg" in frame
            assert "coherence" in frame
            assert "freq_axis" in frame
            assert "blocks_accumulated" in frame
            assert "warming_up" in frame

    def test_ws_frame_has_delay_fields(self, client):
        """Mock WebSocket frames include delay and connection status."""
        with client.websocket_connect("/ws/transfer-function") as ws:
            raw = ws.receive_text()
            frame = json.loads(raw)
            assert "delay_ms" in frame
            assert "delay_confidence" in frame
            assert "ref_connected" in frame
            assert "meas_connected" in frame

    def test_ws_magnitude_is_list_of_floats(self, client):
        """Magnitude array is a non-empty list of numbers."""
        with client.websocket_connect("/ws/transfer-function") as ws:
            raw = ws.receive_text()
            frame = json.loads(raw)
            mag = frame["magnitude_db"]
            assert isinstance(mag, list)
            assert len(mag) > 0
            assert all(isinstance(v, (int, float)) for v in mag)

    def test_ws_coherence_values_in_range(self, client):
        """Coherence values are between 0 and 1."""
        with client.websocket_connect("/ws/transfer-function") as ws:
            raw = ws.receive_text()
            frame = json.loads(raw)
            coh = frame["coherence"]
            assert isinstance(coh, list)
            for v in coh:
                assert 0.0 <= v <= 1.0, f"Coherence {v} out of [0,1]"

    def test_ws_freq_axis_ascending(self, client):
        """Frequency axis is strictly ascending."""
        with client.websocket_connect("/ws/transfer-function") as ws:
            raw = ws.receive_text()
            frame = json.loads(raw)
            freq = frame["freq_axis"]
            assert len(freq) > 1
            for i in range(1, len(freq)):
                assert freq[i] > freq[i - 1], (
                    f"freq_axis not ascending at index {i}: "
                    f"{freq[i-1]} >= {freq[i]}"
                )

    def test_ws_multiple_frames_accumulate(self, client):
        """Receiving multiple frames shows blocks_accumulated increasing."""
        with client.websocket_connect("/ws/transfer-function") as ws:
            first = json.loads(ws.receive_text())
            second = json.loads(ws.receive_text())
            assert second["blocks_accumulated"] >= first["blocks_accumulated"]

    def test_ws_arrays_same_length(self, client):
        """All spectral arrays have the same length as freq_axis."""
        with client.websocket_connect("/ws/transfer-function") as ws:
            frame = json.loads(ws.receive_text())
            n = len(frame["freq_axis"])
            assert len(frame["magnitude_db"]) == n
            assert len(frame["coherence"]) == n
            # phase_deg may have None values (coherence-gated), but same length.
            assert len(frame["phase_deg"]) == n


class TestTfMockFallback:
    """F-270: Test the real-mode code path when PCM sources are missing.

    Monkeypatches MOCK_MODE to False so the WebSocket handler takes the
    real code path.  Without PI4AUDIO_PCM_SOURCES configured, the
    'capture-usb' source is missing — the handler must gracefully fall
    back to mock mode with ``mock_fallback=true`` in the JSON frames
    instead of closing the WebSocket with code 4004.
    """

    def test_ws_falls_back_when_pcm_source_missing(self, client, monkeypatch):
        """WS handler falls back to mock when capture-usb is unavailable."""
        monkeypatch.setattr(tf_routes, "MOCK_MODE", False)
        monkeypatch.delenv("PI4AUDIO_PCM_SOURCES", raising=False)

        with client.websocket_connect("/ws/transfer-function") as ws:
            raw = ws.receive_text()
            frame = json.loads(raw)
            # Must receive valid spectral data, not a close frame.
            assert "magnitude_db" in frame
            assert "freq_axis" in frame
            assert len(frame["magnitude_db"]) > 0
            # The fallback must be visible — not silent.
            assert frame.get("mock_fallback") is True

    def test_ws_fallback_frame_has_all_fields(self, client, monkeypatch):
        """Fallback frames have the same fields as normal mock frames."""
        monkeypatch.setattr(tf_routes, "MOCK_MODE", False)
        monkeypatch.delenv("PI4AUDIO_PCM_SOURCES", raising=False)

        with client.websocket_connect("/ws/transfer-function") as ws:
            frame = json.loads(ws.receive_text())
            for field in ("magnitude_db", "phase_deg", "coherence",
                          "freq_axis", "blocks_accumulated", "warming_up",
                          "delay_ms", "ref_connected", "meas_connected"):
                assert field in frame, f"Missing field in fallback: {field}"

    def test_ws_no_fallback_in_normal_mock(self, client):
        """Normal mock mode (PI_AUDIO_MOCK=1) does NOT set mock_fallback."""
        with client.websocket_connect("/ws/transfer-function") as ws:
            frame = json.loads(ws.receive_text())
            assert frame.get("mock_fallback") is False
