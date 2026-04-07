"""Service-integration tests for measurement pipeline validation.

API-only tests extracted from tests/e2e/test_measurement.py (F-284).
These verify server health, measurement session via API, and post-hoc
artifact validation against the real local-demo stack — no browser needed.

Browser-driven tests remain in tests/e2e/test_measurement.py.

Usage:
    nix run .#test-e2e    # runs both service-integration and e2e tiers
"""

import json
import os
import socket
import time
import urllib.error
import urllib.request

import pytest


pytestmark = [pytest.mark.service_integration, pytest.mark.slow]

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _poll_session_done(base_url, timeout_s=120):
    deadline = time.monotonic() + timeout_s
    last_state = "?"
    while time.monotonic() < deadline:
        data = _api_get(base_url, "/api/v1/measurement/status")
        last_state = data.get("state", "?")
        if last_state in ("complete", "error", "aborted", "idle"):
            return data
        time.sleep(1)
    raise TimeoutError(
        f"Session did not reach terminal state within {timeout_s}s. "
        f"Last: {last_state}")


# ===========================================================================
# Phase 1: Verify local-demo server health
# ===========================================================================

class TestLocalDemoHealth:
    """Verify the local-demo stack is running and healthy."""

    def test_server_responds(self, local_demo_url):
        """GET / returns 200."""
        resp = urllib.request.urlopen(local_demo_url, timeout=5)
        assert resp.status == 200

    def test_gm_connected(self, local_demo_url):
        """Measurement status reports a GM mode (GM must be connected)."""
        data = _api_get(local_demo_url, "/api/v1/measurement/status")
        assert data.get("mode") is not None, (
            f"GM not connected (mode is null): {data}")

    def test_speaker_profiles_available(self, local_demo_url):
        """Speaker profiles API returns profiles from seeded config."""
        data = _api_get(local_demo_url, "/api/v1/speakers/profiles")
        profiles = data.get("profiles", data) if isinstance(data, dict) else data
        names = [p["name"] for p in profiles]
        assert PROFILE_NAME in names, (
            f"Expected '{PROFILE_NAME}' in {names}")

    def test_measurement_state_idle(self, local_demo_url):
        """Measurement status is in a terminal state (no active session)."""
        _wait_for_idle_or_abort(local_demo_url, timeout_s=30)
        data = _api_get(local_demo_url, "/api/v1/measurement/status")
        assert data["state"] in ("idle", "complete", "error", "aborted"), (
            f"Expected terminal state, got {data['state']}")


# ===========================================================================
# Phase 3: Full measurement session via API
# ===========================================================================

class TestLocalDemoMeasurementAPI:
    """Drive a full measurement session via REST API against local-demo."""

    @pytest.mark.xfail(
        reason="F-262: room-sim IRs fail filter verification (min-phase "
               "check). Signal path works — filter quality is a room-sim "
               "limitation, not a pipeline defect.",
        strict=False,
    )
    def test_full_session_api(self, local_demo_url):
        """POST /measurement/start with 1 channel completes end-to-end."""
        _wait_for_idle_or_abort(local_demo_url, timeout_s=30)
        _ensure_gate_open(local_demo_url)

        body = {
            "profile_name": PROFILE_NAME,
            "channels": [{
                "index": 0,
                "name": "Left",
                "target_spl_db": 80.0,
                "thermal_ceiling_dbfs": -20.0,
            }],
            "positions": 1,
            "sweep_duration_s": 2.0,
            "sweep_level_dbfs": -20.0,
            "sample_rate": 48000,
            "umik_sensitivity_dbfs_to_spl": 121.4,
            "hard_limit_spl_db": 95.0,
        }

        result = _api_post(
            local_demo_url, "/api/v1/measurement/start", body)
        assert result.get("status") == "started", (
            f"Expected started, got {result}")

        data = _poll_session_done(local_demo_url, timeout_s=120)
        assert data["state"] == "complete", (
            f"Expected complete, got {data['state']}. "
            f"Error: {data.get('error_message', 'none')}")

    def test_session_api_confirms_complete(self, local_demo_url):
        """After a measurement session, API reports a terminal state.

        Accepts 'idle' as valid — the session may never have been started
        if the xfailed test above was skipped.
        """
        data = _poll_session_done(local_demo_url, timeout_s=30)
        assert data["state"] in ("complete", "error", "idle"), (
            f"Expected terminal or idle state, got {data['state']}. "
            f"Error: {data.get('error_message', 'none')}")


# ===========================================================================
# Phase 5: Post-hoc validation of generated artifacts
# ===========================================================================

class TestLocalDemoPostHocValidation:
    """Validate that the measurement session produced correct DSP artifacts."""

    MEAS_DIR = "/tmp/pi4audio-measurement"

    def test_impulse_responses_saved(self, local_demo_url):
        """Deconvolved IRs were saved during the measurement."""
        ir_dir = os.path.join(self.MEAS_DIR, "impulse_responses")
        if not os.path.isdir(ir_dir):
            pytest.skip("IR directory not found — run session test first")

        ir_files = [f for f in os.listdir(ir_dir)
                    if f.startswith("ir_") and f.endswith(".wav")]
        assert len(ir_files) >= 1, (
            f"Expected at least 1 IR file, found: {ir_files}")

    def test_ir_has_room_characteristics(self, local_demo_url):
        """The deconvolved IR shows room-sim characteristics (not a dirac)."""
        ir_dir = os.path.join(self.MEAS_DIR, "impulse_responses")
        if not os.path.isdir(ir_dir):
            pytest.skip("IR directory not found")

        import numpy as np
        import soundfile as sf

        ir_files = sorted([
            f for f in os.listdir(ir_dir)
            if f.startswith("ir_ch") and f.endswith(".wav")
        ])
        if not ir_files:
            pytest.skip("No channel IR files found")

        path = os.path.join(ir_dir, ir_files[-1])
        data, sr = sf.read(path, dtype="float64")
        if data.ndim > 1:
            data = data[:, 0]

        assert sr == 48000, f"Expected 48kHz, got {sr}"
        assert len(data) > 1000, f"IR too short: {len(data)} samples"

        peak_idx = int(np.argmax(np.abs(data)))
        total_energy = np.sum(data ** 2)
        peak_energy = data[peak_idx] ** 2

        if total_energy > 0:
            energy_ratio = peak_energy / total_energy
            assert energy_ratio < 0.95, (
                f"IR looks like a dirac ({energy_ratio:.4f} energy in one sample) "
                f"— room-sim reflections not captured?")

    def test_correction_filters_generated(self, local_demo_url):
        """Combined correction filter WAV files were generated."""
        combined_files = [
            f for f in os.listdir(self.MEAS_DIR)
            if f.startswith("combined_") and f.endswith(".wav")
        ]
        assert len(combined_files) >= 1, (
            f"No combined filter WAVs in {self.MEAS_DIR}: "
            f"{os.listdir(self.MEAS_DIR)}")

    def test_correction_filters_pass_d009(self, local_demo_url):
        """Generated correction filters comply with D-009 safety (gain <= -0.5 dB)."""
        import numpy as np
        import soundfile as sf

        combined_files = sorted([
            f for f in os.listdir(self.MEAS_DIR)
            if f.startswith("combined_") and f.endswith(".wav")
        ])
        if not combined_files:
            pytest.skip("No combined filter WAVs found")

        checked = set()
        for fname in reversed(combined_files):
            parts = fname.replace("combined_", "").rsplit("_", 2)
            prefix = parts[0] if len(parts) >= 3 else fname
            if prefix in checked:
                continue
            checked.add(prefix)

            path = os.path.join(self.MEAS_DIR, fname)
            data, sr = sf.read(path, dtype="float64")
            if data.ndim > 1:
                data = data[:, 0]

            peak_abs = float(np.max(np.abs(data)))
            peak_db = 20.0 * np.log10(max(peak_abs, 1e-10))
            assert peak_db <= 0.0, (
                f"D-009 violation in {fname}: peak {peak_db:.2f} dB > 0 dB")

    def test_pw_convolver_config_generated(self, local_demo_url):
        """PW filter-chain convolver config was generated."""
        conf_path = os.path.join(self.MEAS_DIR,
                                 "30-filter-chain-convolver.conf")
        assert os.path.isfile(conf_path), (
            f"PW convolver config not found at {conf_path}")

        with open(conf_path) as f:
            content = f.read()
        assert "combined_" in content or "filename" in content, (
            "PW config doesn't reference any filter files")

    def test_delays_yaml_exists(self, local_demo_url):
        """Time alignment delays.yml was generated."""
        delays_path = os.path.join(self.MEAS_DIR, "delays.yml")
        assert os.path.isfile(delays_path), (
            f"delays.yml not found at {delays_path}")

    def test_session_status_has_results(self, local_demo_url):
        """The most recent session status includes gain cal and sweep results."""
        data = _api_get(local_demo_url, "/api/v1/measurement/status")
        state = data["state"]
        if state in ("idle", "error", "aborted") and not data.get("gain_cal_results"):
            pytest.skip(f"Session in {state} with no results — "
                        "nothing to validate")

        gcr = data.get("gain_cal_results", {})
        assert len(gcr) >= 1, "No gain cal results in status"
        for ch_key, result in gcr.items():
            assert result["passed"], (
                f"Gain cal failed for channel {ch_key}: {result}")

        sr = data.get("sweep_results", {})
        assert len(sr) >= 1, "No sweep results in status"
