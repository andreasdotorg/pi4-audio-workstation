"""Tests for POST /api/v1/test-tool/calibration/verify (US-096 QE gap).

Covers:
    1. Happy path: plausible SPL measurement passes verification
    2. Failure: SPL outside plausible range (30-100 dB) fails
    3. Siggen not enabled: returns 503
    4. Measurement failure: pcm-bridge unreachable returns error
    5. Siggen play failure: returns 502
"""

import json
import math
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _mock_siggen_rpc_ok(cmd, timeout=5.0):
    """Mock signal-gen RPC that always succeeds."""
    return {"type": "ack", "cmd": cmd.get("cmd"), "ok": True}


def _mock_siggen_rpc_fail(cmd, timeout=5.0):
    """Mock signal-gen RPC that rejects the command."""
    return {"type": "ack", "cmd": cmd.get("cmd"), "ok": False,
            "error": "internal error"}


def _mock_siggen_rpc_connection_error(cmd, timeout=5.0):
    """Mock signal-gen RPC that raises ConnectionError."""
    raise ConnectionError("Connection refused")


def _mock_levels_response(rms_linear):
    """Build a mock urllib response with pcm-bridge levels JSON."""
    data = {"channels": {"2": {"rms": rms_linear}}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda s, *a: None
    return mock_resp


class TestCalibrationVerifyHappyPath:
    """Plausible SPL measurement passes verification."""

    def test_plausible_spl_passes(self, client):
        """A measured SPL of ~70 dB is plausible for -20 dBFS tone."""
        # rms_linear for ~70 dB SPL: rms_dbfs + 121.4 = 70 => rms_dbfs = -51.4
        # rms_linear = 10^(-51.4/20) = 0.00269
        rms_linear = 10 ** (-51.4 / 20)

        with patch("app.test_tool.routes.SIGGEN_MODE", True), \
             patch("app.test_tool.routes._siggen_rpc",
                   side_effect=_mock_siggen_rpc_ok), \
             patch("urllib.request.urlopen",
                   return_value=_mock_levels_response(rms_linear)):
            resp = client.post("/api/v1/test-tool/calibration/verify")

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert 60 < data["measured_spl_db"] < 80
        assert data["test_level_dbfs"] == -20.0
        assert data["test_freq_hz"] == 1000.0

    def test_high_plausible_spl_passes(self, client):
        """A measured SPL of ~90 dB still passes (within 30-100 range)."""
        # rms_dbfs + 121.4 = 90 => rms_dbfs = -31.4
        rms_linear = 10 ** (-31.4 / 20)

        with patch("app.test_tool.routes.SIGGEN_MODE", True), \
             patch("app.test_tool.routes._siggen_rpc",
                   side_effect=_mock_siggen_rpc_ok), \
             patch("urllib.request.urlopen",
                   return_value=_mock_levels_response(rms_linear)):
            resp = client.post("/api/v1/test-tool/calibration/verify")

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert 85 < data["measured_spl_db"] < 95


class TestCalibrationVerifyFailure:
    """SPL outside plausible range fails verification."""

    def test_too_low_spl_fails(self, client):
        """SPL below 30 dB fails plausibility check."""
        # rms_dbfs + 121.4 = 20 => rms_dbfs = -101.4
        rms_linear = 10 ** (-101.4 / 20)

        with patch("app.test_tool.routes.SIGGEN_MODE", True), \
             patch("app.test_tool.routes._siggen_rpc",
                   side_effect=_mock_siggen_rpc_ok), \
             patch("urllib.request.urlopen",
                   return_value=_mock_levels_response(rms_linear)):
            resp = client.post("/api/v1/test-tool/calibration/verify")

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False

    def test_too_high_spl_fails(self, client):
        """SPL above 100 dB fails plausibility check."""
        # rms_dbfs + 121.4 = 110 => rms_dbfs = -11.4
        rms_linear = 10 ** (-11.4 / 20)

        with patch("app.test_tool.routes.SIGGEN_MODE", True), \
             patch("app.test_tool.routes._siggen_rpc",
                   side_effect=_mock_siggen_rpc_ok), \
             patch("urllib.request.urlopen",
                   return_value=_mock_levels_response(rms_linear)):
            resp = client.post("/api/v1/test-tool/calibration/verify")

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False


class TestCalibrationVerifySiggenNotEnabled:
    """Siggen not enabled returns 503."""

    def test_returns_503_when_siggen_off(self, client):
        """Endpoint returns 503 when PI4AUDIO_SIGGEN is not set."""
        with patch("app.test_tool.routes.SIGGEN_MODE", False):
            resp = client.post("/api/v1/test-tool/calibration/verify")

        assert resp.status_code == 503
        data = resp.json()
        assert data["error"] == "siggen_not_enabled"


class TestCalibrationVerifyMeasurementFailure:
    """pcm-bridge unreachable returns measurement_failed error."""

    def test_pcm_bridge_unreachable(self, client):
        """When pcm-bridge levels endpoint fails, returns measurement_failed."""
        with patch("app.test_tool.routes.SIGGEN_MODE", True), \
             patch("app.test_tool.routes._siggen_rpc",
                   side_effect=_mock_siggen_rpc_ok), \
             patch("urllib.request.urlopen",
                   side_effect=ConnectionError("refused")):
            resp = client.post("/api/v1/test-tool/calibration/verify")

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert data["error"] == "measurement_failed"
        assert "pcm-bridge" in data["detail"]

    def test_pcm_bridge_returns_zero_rms(self, client):
        """When pcm-bridge returns rms=0, measured_spl is None -> error."""
        with patch("app.test_tool.routes.SIGGEN_MODE", True), \
             patch("app.test_tool.routes._siggen_rpc",
                   side_effect=_mock_siggen_rpc_ok), \
             patch("urllib.request.urlopen",
                   return_value=_mock_levels_response(0)):
            resp = client.post("/api/v1/test-tool/calibration/verify")

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert data["error"] == "measurement_failed"


class TestCalibrationVerifySiggenFailure:
    """Siggen play command failure returns 502."""

    def test_play_rejected(self, client):
        """When signal-gen rejects the play command, returns 502."""
        with patch("app.test_tool.routes.SIGGEN_MODE", True), \
             patch("app.test_tool.routes._siggen_rpc",
                   side_effect=_mock_siggen_rpc_fail):
            resp = client.post("/api/v1/test-tool/calibration/verify")

        assert resp.status_code == 502
        data = resp.json()
        assert data["error"] == "play_failed"

    def test_siggen_connection_error(self, client):
        """When signal-gen is unreachable, returns 502."""
        with patch("app.test_tool.routes.SIGGEN_MODE", True), \
             patch("app.test_tool.routes._siggen_rpc",
                   side_effect=_mock_siggen_rpc_connection_error):
            resp = client.post("/api/v1/test-tool/calibration/verify")

        assert resp.status_code == 502
        data = resp.json()
        assert data["error"] == "siggen_error"
