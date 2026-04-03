"""Tests for thermal monitor + limiter wiring into app startup and profile activation.

Verifies (R-2, US-092):
  1. App lifespan creates thermal_monitor and thermal_limiter on app.state
  2. Profile activation configures thermal monitor from ceilings
  3. Profile activation configures thermal limiter with channel mappings
  4. Profile switch reconfigures both components
  5. Thermal routes return real data (not 503) after startup
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# room-correction package (sibling) — needed for thermal_ceiling patching.
_RC_ROOT = Path(__file__).resolve().parents[2] / "room-correction"
if str(_RC_ROOT) not in sys.path:
    sys.path.insert(0, str(_RC_ROOT))

from app.collectors.thermal_monitor import ThermalMonitor
from app.thermal_limiter import ThermalGainLimiter


# -- Helpers ------------------------------------------------------------------

def _run(coro):
    """Run async coroutine in sync test context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _mock_levels(n_channels=4):
    mock = MagicMock()
    mock.rms.return_value = [-120.0] * n_channels
    return mock


# -- Test: _configure_thermal_protection function ----------------------------

class TestConfigureThermalProtection:
    """Unit tests for the _configure_thermal_protection helper."""

    def test_configures_monitor_from_profile(self, tmp_path):
        """Profile activation configures thermal monitor with correct channels."""
        from app.speaker_routes import _configure_thermal_protection

        monitor = ThermalMonitor(_mock_levels())
        limiter = ThermalGainLimiter(monitor, is_mock=True)

        # Create mock ceilings data that load_channel_ceilings would return.
        mock_ceilings = {
            "sat_left": {
                "channel": 0, "pe_max_watts": 7.0,
                "impedance_ohm": 4.0, "sensitivity_db_spl": 87.5,
                "identity": "chn50p", "pw_gain_mult": 0.001,
                "ceiling_dbfs": -20.0, "pw_gain_db": -60.0,
            },
            "sub1": {
                "channel": 2, "pe_max_watts": 200.0,
                "impedance_ohm": 4.0, "sensitivity_db_spl": 88.0,
                "identity": "ps28", "pw_gain_mult": 0.000631,
                "ceiling_dbfs": -20.0, "pw_gain_db": -64.0,
            },
        }

        profile = {
            "name": "Test Profile", "topology": "2way",
            "speakers": {
                "sat_left": {"identity": "chn50p", "channel": 0,
                             "role": "satellite", "filter_type": "highpass"},
                "sub1": {"identity": "ps28", "channel": 2,
                         "role": "subwoofer", "filter_type": "lowpass"},
            },
        }
        target_gains = {"gain_left_hp": 0.001, "gain_sub1_lp": 0.000631}

        with patch("thermal_ceiling.load_channel_ceilings",
                   return_value=mock_ceilings):
            _configure_thermal_protection(
                "test-profile", profile, target_gains,
                monitor, limiter)

        # Monitor should have 2 channels configured.
        snap = monitor.snapshot()
        assert len(snap) == 2
        names = {s["name"] for s in snap}
        assert names == {"sat_left", "sub1"}
        # Check ceiling values propagated.
        sat = next(s for s in snap if s["name"] == "sat_left")
        assert sat["ceiling_watts"] == 7.0

    def test_configures_limiter_channels(self, tmp_path):
        """Profile activation configures limiter with gain node mappings."""
        from app.speaker_routes import _configure_thermal_protection

        monitor = ThermalMonitor(_mock_levels())
        limiter = ThermalGainLimiter(monitor, is_mock=True)

        mock_ceilings = {
            "sat_left": {
                "channel": 0, "pe_max_watts": 7.0,
                "impedance_ohm": 4.0, "sensitivity_db_spl": 87.5,
                "identity": "chn50p", "pw_gain_mult": 0.001,
            },
            "sat_right": {
                "channel": 1, "pe_max_watts": 7.0,
                "impedance_ohm": 4.0, "sensitivity_db_spl": 87.5,
                "identity": "chn50p", "pw_gain_mult": 0.001,
            },
        }

        profile = {
            "speakers": {
                "sat_left": {"identity": "chn50p", "channel": 0,
                             "role": "satellite"},
                "sat_right": {"identity": "chn50p", "channel": 1,
                              "role": "satellite"},
            },
        }
        target_gains = {"gain_left_hp": 0.001, "gain_right_hp": 0.001}

        with patch("thermal_ceiling.load_channel_ceilings",
                   return_value=mock_ceilings):
            _configure_thermal_protection(
                "test", profile, target_gains, monitor, limiter)

        # Limiter should have 2 channels.
        limiter_snap = limiter.snapshot()
        assert len(limiter_snap["channels"]) == 2
        ch_names = {c["name"] for c in limiter_snap["channels"]}
        assert ch_names == {"sat_left", "sat_right"}
        # Check gain node names mapped correctly.
        for ch in limiter_snap["channels"]:
            if ch["name"] == "sat_left":
                assert ch["gain_node"] == "gain_left_hp"
            elif ch["name"] == "sat_right":
                assert ch["gain_node"] == "gain_right_hp"

    def test_noop_when_monitor_is_none(self):
        """No-op when thermal_monitor is None (graceful degradation)."""
        from app.speaker_routes import _configure_thermal_protection

        # Should not raise.
        _configure_thermal_protection(
            "test", {}, {}, None, None)

    def test_handles_load_ceilings_failure(self):
        """Graceful fallback when load_channel_ceilings raises."""
        from app.speaker_routes import _configure_thermal_protection

        monitor = ThermalMonitor(_mock_levels())
        limiter = ThermalGainLimiter(monitor, is_mock=True)

        with patch("thermal_ceiling.load_channel_ceilings",
                   side_effect=FileNotFoundError("profile not found")):
            # Should not raise — logs a warning.
            _configure_thermal_protection(
                "nonexistent", {}, {}, monitor, limiter)

        # Monitor should still have 0 channels (not configured).
        assert len(monitor.snapshot()) == 0

    def test_profile_switch_reconfigures(self):
        """Switching profiles reconfigures both monitor and limiter."""
        from app.speaker_routes import _configure_thermal_protection

        monitor = ThermalMonitor(_mock_levels(8))
        limiter = ThermalGainLimiter(monitor, is_mock=True)

        # First profile: 2 channels.
        ceilings_2way = {
            "sat_left": {
                "channel": 0, "pe_max_watts": 7.0,
                "impedance_ohm": 4.0, "sensitivity_db_spl": 87.5,
                "identity": "chn50p", "pw_gain_mult": 0.001,
            },
            "sub1": {
                "channel": 2, "pe_max_watts": 200.0,
                "impedance_ohm": 4.0, "sensitivity_db_spl": 88.0,
                "identity": "ps28", "pw_gain_mult": 0.000631,
            },
        }
        profile_2way = {
            "speakers": {
                "sat_left": {"identity": "chn50p", "channel": 0,
                             "role": "satellite"},
                "sub1": {"identity": "ps28", "channel": 2,
                         "role": "subwoofer"},
            },
        }
        gains_2way = {"gain_left_hp": 0.001, "gain_sub1_lp": 0.000631}

        with patch("thermal_ceiling.load_channel_ceilings",
                   return_value=ceilings_2way):
            _configure_thermal_protection(
                "2way", profile_2way, gains_2way, monitor, limiter)

        assert len(monitor.snapshot()) == 2
        assert len(limiter.snapshot()["channels"]) == 2

        # Switch to profile with 4 channels.
        ceilings_4ch = {
            f"ch{i}": {
                "channel": i, "pe_max_watts": 50.0,
                "impedance_ohm": 8.0, "sensitivity_db_spl": 90.0,
                "identity": "mid", "pw_gain_mult": 0.01,
            }
            for i in range(4)
        }
        profile_4ch = {
            "speakers": {
                f"ch{i}": {"identity": "mid", "channel": i, "role": "satellite"}
                for i in range(4)
            },
        }
        gains_4ch = {f"gain_ch{i}": 0.01 for i in range(4)}

        with patch("thermal_ceiling.load_channel_ceilings",
                   return_value=ceilings_4ch):
            _configure_thermal_protection(
                "4ch", profile_4ch, gains_4ch, monitor, limiter)

        assert len(monitor.snapshot()) == 4
        assert len(limiter.snapshot()["channels"]) == 4


# -- Test: activate_profile wires thermal components -------------------------

class TestActivateProfileThermalWiring:
    """Integration test: activate_profile passes thermal components."""

    def test_activate_passes_thermal_to_impl(self, tmp_path, monkeypatch):
        """activate_profile extracts thermal components from app.state."""
        from fastapi.testclient import TestClient
        from app.main import app

        # Verify app.state has thermal components after startup.
        # In mock mode, these should be created.
        with TestClient(app) as client:
            # The lifespan should have created thermal_monitor.
            assert hasattr(app.state, "thermal_monitor")
            assert hasattr(app.state, "thermal_limiter")
            assert isinstance(app.state.thermal_monitor, ThermalMonitor)
            assert isinstance(app.state.thermal_limiter, ThermalGainLimiter)


# -- Test: thermal routes return data (not 503) after startup ----------------

class TestThermalRoutesAfterStartup:
    """Thermal API endpoints should return real responses, not 503."""

    def test_thermal_status_returns_200(self):
        """GET /api/v1/thermal/status returns 200 after startup."""
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/api/v1/thermal/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "channels" in data
            assert isinstance(data["channels"], list)

    def test_thermal_limiter_returns_200(self):
        """GET /api/v1/thermal/limiter returns 200 after startup."""
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/api/v1/thermal/limiter")
            assert resp.status_code == 200
            data = resp.json()
            assert "channels" in data

    def test_thermal_limiter_audit_returns_200(self):
        """GET /api/v1/thermal/limiter/audit returns 200 after startup."""
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/api/v1/thermal/limiter/audit")
            assert resp.status_code == 200
            data = resp.json()
            assert "entries" in data
