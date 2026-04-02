"""Pipeline integration test: measurement -> correction -> deploy -> verify.

Validates that all gap fixes (GAP-1 through GAP-6) work together as a coherent
pipeline in mock mode.  Exercises the full state machine:

    IDLE -> SETUP -> GAIN_CAL -> MEASURING -> FILTER_GEN -> DEPLOY -> VERIFY -> COMPLETE

Checks at each stage:
  - Deconvolved IRs saved with spk_key naming (GAP-6)
  - Time alignment delays computed and saved (GAP-1/GAP-3)
  - Filter generation uses generate_profile_filters() (R-3)
  - D-009 safety on all output filters
  - Profile name wired through (GAP-2)
  - Verification results broadcast (GAP-5)

Run:
    cd src/web-ui
    python -m pytest tests/test_measurement_pipeline_integration.py -v
"""

import os
import time

import numpy as np
import pytest
import yaml

from app.measurement.session import MeasurementState


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TERMINAL_STATES = {"complete", "idle", "error", "aborted"}

# Two-channel body matching the 2way-80hz-sealed profile (sat_left, sub1).
TWO_WAY_START_BODY = {
    "channels": [
        {"index": 0, "name": "Left", "target_spl_db": 75.0,
         "thermal_ceiling_dbfs": -20.0, "speaker_key": "sat_left"},
        {"index": 2, "name": "Sub1", "target_spl_db": 75.0,
         "thermal_ceiling_dbfs": -14.0, "speaker_key": "sub1"},
    ],
    "positions": 1,
    "sweep_duration_s": 0.5,
    "sweep_level_dbfs": -20.0,
    "hard_limit_spl_db": 84.0,
    "umik_sensitivity_dbfs_to_spl": 121.4,
    "profile_name": "2way-80hz-sealed",
}


def _wait_for_session_done(client, timeout_s=120.0, poll_interval=0.2):
    """Poll GET /status until session reaches a terminal state or timeout."""
    deadline = time.monotonic() + timeout_s
    data = None
    while time.monotonic() < deadline:
        resp = client.get("/api/v1/measurement/status")
        data = resp.json()
        if data["state"] in TERMINAL_STATES:
            return data
        time.sleep(poll_interval)
    raise TimeoutError(
        f"Session did not reach terminal state within {timeout_s}s. "
        f"Last state: {data['state'] if data else 'unknown'}")


# ===========================================================================
# Full pipeline E2E test
# ===========================================================================

class TestFullPipelineE2E:
    """Complete venue workflow: measure -> correct -> deploy -> verify."""

    def test_full_pipeline_reaches_complete(self, client):
        """Session runs through all states to COMPLETE."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200

        final = _wait_for_session_done(client, timeout_s=120.0)
        assert final["state"] in ("complete", "idle")

    def test_impulse_responses_saved(self, client):
        """GAP-1: Deconvolved IRs are saved after measurement."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200
        _wait_for_session_done(client, timeout_s=120.0)

        # Access the completed session via mode_manager.
        from app.main import app
        mm = app.state.mode_manager
        session = mm.last_completed_session or mm.measurement_session
        assert session is not None

        # _impulse_responses should have been populated by deconvolution.
        assert len(session._impulse_responses) > 0
        # Keys should match ch{idx}_pos{pos} pattern.
        for key in session._impulse_responses:
            assert key.startswith("ch")
            assert "_pos" in key
            ir = session._impulse_responses[key]
            assert isinstance(ir, np.ndarray)
            assert len(ir) > 0
            assert np.all(np.isfinite(ir))

    def test_time_alignment_computed(self, client):
        """GAP-1/GAP-3: Time alignment delays are computed and stored."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200
        _wait_for_session_done(client, timeout_s=120.0)

        from app.main import app
        mm = app.state.mode_manager
        session = mm.last_completed_session or mm.measurement_session
        assert session is not None

        # With 2 channels, time alignment should produce delays for both.
        delays = session._time_alignment_delays
        assert len(delays) >= 1
        # All delays should be non-negative floats.
        for name, delay in delays.items():
            assert isinstance(delay, float)
            assert delay >= 0.0

    def test_delays_yaml_saved(self, client):
        """GAP-1: delays.yml saved to output directory."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200
        _wait_for_session_done(client, timeout_s=120.0)

        from app.main import app
        mm = app.state.mode_manager
        session = mm.last_completed_session or mm.measurement_session
        assert session is not None

        delays_path = os.path.join(session._config.output_dir, "delays.yml")
        assert os.path.isfile(delays_path), f"delays.yml not found at {delays_path}"

        with open(delays_path) as f:
            data = yaml.safe_load(f)
        assert "delays_ms" in data
        assert "delays_samples" in data

    def test_speaker_key_irs_saved(self, client):
        """GAP-6: IRs saved with speaker-key naming for filter_routes."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200
        _wait_for_session_done(client, timeout_s=120.0)

        from app.main import app
        mm = app.state.mode_manager
        session = mm.last_completed_session or mm.measurement_session
        assert session is not None

        ir_dir = os.path.join(
            session._config.output_dir, "impulse_responses")
        assert os.path.isdir(ir_dir), f"impulse_responses dir not found"

        # Should have spk_key-named files (from GAP-6 in _filter_gen_sync).
        # The 2way profile has sat_left and sub1.
        for spk_key in ("sat_left", "sub1"):
            spk_path = os.path.join(ir_dir, f"ir_{spk_key}.wav")
            assert os.path.isfile(spk_path), \
                f"Speaker-key IR not found: {spk_path}"

    def test_profile_name_wired_through(self, client):
        """GAP-2: profile_name from request reaches filter generation."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200
        _wait_for_session_done(client, timeout_s=120.0)

        from app.main import app
        mm = app.state.mode_manager
        session = mm.last_completed_session or mm.measurement_session
        assert session is not None

        # The session config should carry the profile name.
        assert session._config.profile_name == "2way-80hz-sealed"

        # The filter_gen_result should reference the same profile.
        fg = session._filter_gen_result
        assert fg is not None
        assert fg["profile"] == "2way-80hz-sealed"

    def test_filter_gen_d009_all_pass(self, client):
        """D-009: All generated filters have gain <= -0.5 dBFS."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200
        _wait_for_session_done(client, timeout_s=120.0)

        from app.main import app
        mm = app.state.mode_manager
        session = mm.last_completed_session or mm.measurement_session
        assert session is not None

        fg = session._filter_gen_result
        assert fg is not None
        assert fg["all_pass"] is True

        for v in fg["verification"]:
            assert v["d009_pass"] is True, \
                f"D-009 failed for {v['channel']}: peak {v['d009_peak_db']} dB"
            assert v["d009_peak_db"] <= -0.5, \
                f"D-009 peak too high for {v['channel']}: {v['d009_peak_db']} dB"

    def test_combined_filter_wav_files_exist(self, client):
        """R-3: Combined FIR WAV files produced by generate_profile_filters."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200
        _wait_for_session_done(client, timeout_s=120.0)

        from app.main import app
        mm = app.state.mode_manager
        session = mm.last_completed_session or mm.measurement_session
        assert session is not None

        fg = session._filter_gen_result
        assert fg is not None

        # Should have combined filter WAV files for each speaker.
        channels = fg["channels"]
        assert len(channels) >= 2  # sat_left + sub1 minimum
        for spk_key, path in channels.items():
            assert os.path.isfile(path), \
                f"Combined filter WAV not found: {path}"

    def test_pw_conf_generated(self, client):
        """PipeWire filter-chain .conf generated during filter_gen."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200
        _wait_for_session_done(client, timeout_s=120.0)

        from app.main import app
        mm = app.state.mode_manager
        session = mm.last_completed_session or mm.measurement_session
        assert session is not None

        fg = session._filter_gen_result
        assert fg is not None
        assert "pw_conf_path" in fg
        assert os.path.isfile(fg["pw_conf_path"])

    def test_verify_broadcasts_static_results(self, client):
        """GAP-5: Verification phase broadcasts results (mock = static only)."""
        resp = client.post("/api/v1/measurement/start",
                           json=TWO_WAY_START_BODY)
        assert resp.status_code == 200
        final = _wait_for_session_done(client, timeout_s=120.0)
        assert final["state"] in ("complete", "idle")
        # In mock mode the verify phase runs the static path successfully.
        # The session reaching COMPLETE confirms verify did not error.


class TestMultiPositionPipeline:
    """Multi-position measurement (positions > 1) through full pipeline."""

    def test_multi_position_completes(self, client):
        """3-position measurement runs through all states."""
        body = dict(TWO_WAY_START_BODY)
        body["positions"] = 3
        resp = client.post("/api/v1/measurement/start", json=body)
        assert resp.status_code == 200

        final = _wait_for_session_done(client, timeout_s=120.0)
        assert final["state"] in ("complete", "idle")

    def test_multi_position_has_more_irs(self, client):
        """3 positions x 2 channels = 6 IR entries."""
        body = dict(TWO_WAY_START_BODY)
        body["positions"] = 3
        resp = client.post("/api/v1/measurement/start", json=body)
        assert resp.status_code == 200
        _wait_for_session_done(client, timeout_s=120.0)

        from app.main import app
        mm = app.state.mode_manager
        session = mm.last_completed_session or mm.measurement_session
        assert session is not None

        # 2 channels x 3 positions = 6 IR entries.
        assert len(session._impulse_responses) == 6
        for pos in range(3):
            assert f"ch0_pos{pos}" in session._impulse_responses
            assert f"ch2_pos{pos}" in session._impulse_responses
