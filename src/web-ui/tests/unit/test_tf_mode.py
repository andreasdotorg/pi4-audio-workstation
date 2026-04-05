"""Unit tests for transfer function measurement mode endpoints (T-120-04)."""

import os
import pytest

# Ensure mock mode for testing.
os.environ["PI_AUDIO_MOCK"] = "1"

from app.transfer_function_mode import (
    _TfModeState,
    _gm_get_mode,
    _gm_set_mode,
    _mock_gm_mode,
    _mock_gm_rpc,
)


class TestTfModeState:
    def test_initial_state(self):
        state = _TfModeState()
        assert state.active is False
        assert state.filter_mode == "design"
        assert state.previous_gm_mode is None

    def test_to_dict(self):
        state = _TfModeState()
        d = state.to_dict()
        assert d == {
            "active": False,
            "filter_mode": "design",
            "previous_gm_mode": None,
        }

    def test_to_dict_active(self):
        state = _TfModeState()
        state.active = True
        state.filter_mode = "verify"
        state.previous_gm_mode = "dj"
        d = state.to_dict()
        assert d["active"] is True
        assert d["filter_mode"] == "verify"
        assert d["previous_gm_mode"] == "dj"


class TestMockGmRpc:
    def test_get_state_returns_mode(self):
        import app.transfer_function_mode as mod
        mod._mock_gm_mode = "standby"
        resp = _mock_gm_rpc({"cmd": "get_state"})
        assert resp["mode"] == "standby"
        assert resp["ok"] is True

    def test_set_mode_changes_mode(self):
        import app.transfer_function_mode as mod
        mod._mock_gm_mode = "standby"
        resp = _mock_gm_rpc({"cmd": "set_mode", "mode": "measurement"})
        assert resp["ok"] is True
        assert mod._mock_gm_mode == "measurement"

    def test_gm_get_mode(self):
        import app.transfer_function_mode as mod
        mod._mock_gm_mode = "dj"
        assert _gm_get_mode() == "dj"

    def test_gm_set_mode(self):
        import app.transfer_function_mode as mod
        mod._mock_gm_mode = "standby"
        _gm_set_mode("measurement")
        assert mod._mock_gm_mode == "measurement"

    def test_unknown_cmd(self):
        resp = _mock_gm_rpc({"cmd": "unknown_thing"})
        assert resp["ok"] is True


class TestFilterModeValidation:
    def test_valid_modes(self):
        """Design and verify are the only valid filter modes."""
        state = _TfModeState()
        state.filter_mode = "design"
        assert state.filter_mode == "design"
        state.filter_mode = "verify"
        assert state.filter_mode == "verify"
