"""Tests for US-090: FIR generation API endpoint.

Covers:
    - Request validation (n_taps, sample_rate)
    - POST /api/v1/filters/generate with mocked pipeline
    - GET /api/v1/filters/profiles lists available profiles
    - Error handling (profile not found, pipeline failure)
    - VerificationResult serialization
"""

from unittest.mock import patch, MagicMock

import pytest
from starlette.testclient import TestClient

from app.main import app

try:
    from app.filter_routes import (
        FilterGenerateRequest,
        VerificationResult,
        _PROFILES_DIR,
    )
except ImportError:
    pytest.skip("filter_routes not available (pre-commit)", allow_module_level=True)


# -- Fixtures ---------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


def _mock_pipeline_result(profile="bose-home", all_pass=True):
    """Build a realistic pipeline result dict for mocking."""
    return {
        "profile": profile,
        "output_dir": "/tmp/test-output",
        "channels": {
            "left_hp": "/tmp/test-output/combined_left_hp.wav",
            "right_hp": "/tmp/test-output/combined_right_hp.wav",
            "sub1_lp": "/tmp/test-output/combined_sub1_lp.wav",
            "sub2_lp": "/tmp/test-output/combined_sub2_lp.wav",
        },
        "verification": [
            {
                "channel": "left_hp",
                "d009_pass": True,
                "d009_peak_db": -1.2,
                "min_phase_pass": True,
                "format_pass": True,
                "all_pass": True,
            },
        ],
        "all_pass": all_pass,
        "n_taps": 16384,
        "sample_rate": 48000,
        "crossover_freq_hz": 80,
        "slope_db_per_oct": 48,
        "pw_conf_path": "/tmp/test-output/30-filter-chain-convolver.conf",
    }


# -- Request model validation -----------------------------------------------

class TestFilterGenerateRequest:
    def test_valid_defaults(self):
        req = FilterGenerateRequest(profile="bose-home")
        assert req.n_taps == 16384
        assert req.sample_rate == 48000
        assert req.generate_pw_conf is True
        assert req.target_phon is None
        assert req.reference_phon == 80.0

    def test_valid_custom(self):
        req = FilterGenerateRequest(
            profile="test",
            n_taps=8192,
            sample_rate=96000,
            target_phon=65.0,
            generate_pw_conf=False,
        )
        assert req.n_taps == 8192
        assert req.sample_rate == 96000
        assert req.target_phon == 65.0
        assert req.generate_pw_conf is False

    def test_invalid_n_taps(self):
        with pytest.raises(Exception):
            FilterGenerateRequest(profile="test", n_taps=1000)

    def test_invalid_sample_rate(self):
        with pytest.raises(Exception):
            FilterGenerateRequest(profile="test", sample_rate=22050)

    def test_valid_n_taps_values(self):
        for taps in (4096, 8192, 16384, 32768):
            req = FilterGenerateRequest(profile="test", n_taps=taps)
            assert req.n_taps == taps

    def test_valid_sample_rates(self):
        for sr in (44100, 48000, 96000):
            req = FilterGenerateRequest(profile="test", sample_rate=sr)
            assert req.sample_rate == sr

    def test_optional_gains(self):
        req = FilterGenerateRequest(
            profile="test",
            gains_db={"sat_left": -20.0, "sub1": -24.0},
        )
        assert req.gains_db["sat_left"] == -20.0

    def test_optional_delays(self):
        req = FilterGenerateRequest(
            profile="test",
            delays_ms={"sub1": 3.5, "sub2": 4.2},
        )
        assert req.delays_ms["sub1"] == 3.5


# -- VerificationResult serialization ----------------------------------------

class TestVerificationResult:
    def test_to_dict_all_pass(self):
        vr = VerificationResult(
            channel="left_hp",
            d009_pass=True,
            d009_peak_db=-1.234,
            min_phase_pass=True,
            format_pass=True,
        )
        d = vr.to_dict()
        assert d["channel"] == "left_hp"
        assert d["d009_pass"] is True
        assert d["d009_peak_db"] == -1.23
        assert d["min_phase_pass"] is True
        assert d["format_pass"] is True
        assert d["all_pass"] is True

    def test_to_dict_d009_fail(self):
        vr = VerificationResult(
            channel="sub1_lp",
            d009_pass=False,
            d009_peak_db=0.5,
            min_phase_pass=True,
            format_pass=True,
        )
        d = vr.to_dict()
        assert d["all_pass"] is False
        assert d["d009_pass"] is False

    def test_to_dict_min_phase_fail(self):
        vr = VerificationResult(
            channel="right_hp",
            d009_pass=True,
            d009_peak_db=-0.8,
            min_phase_pass=False,
            format_pass=True,
        )
        assert vr.to_dict()["all_pass"] is False

    def test_to_dict_format_fail(self):
        vr = VerificationResult(
            channel="sub2_lp",
            d009_pass=True,
            d009_peak_db=-1.0,
            min_phase_pass=True,
            format_pass=False,
        )
        assert vr.to_dict()["all_pass"] is False

    def test_peak_db_rounding(self):
        vr = VerificationResult(
            channel="test",
            d009_pass=True,
            d009_peak_db=-1.23456789,
            min_phase_pass=True,
            format_pass=True,
        )
        assert vr.to_dict()["d009_peak_db"] == -1.23


# -- POST /api/v1/filters/generate ------------------------------------------

class TestGenerateEndpoint:
    @patch("app.filter_routes._run_pipeline")
    def test_generate_success(self, mock_pipeline, client):
        mock_pipeline.return_value = _mock_pipeline_result()
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile"] == "bose-home"
        assert data["all_pass"] is True
        assert "channels" in data
        assert "verification" in data

    @patch("app.filter_routes._run_pipeline")
    def test_generate_partial_failure_207(self, mock_pipeline, client):
        mock_pipeline.return_value = _mock_pipeline_result(all_pass=False)
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home"},
        )
        assert resp.status_code == 207

    @patch("app.filter_routes._run_pipeline")
    def test_generate_profile_not_found(self, mock_pipeline, client):
        mock_pipeline.side_effect = FileNotFoundError("Profile 'missing' not found")
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "missing"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"] == "profile_not_found"

    @patch("app.filter_routes._run_pipeline")
    def test_generate_pipeline_error(self, mock_pipeline, client):
        mock_pipeline.side_effect = RuntimeError("DSP computation failed")
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home"},
        )
        assert resp.status_code == 500
        assert resp.json()["error"] == "generation_failed"

    def test_generate_invalid_n_taps(self, client):
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "test", "n_taps": 999},
        )
        assert resp.status_code == 422

    def test_generate_invalid_sample_rate(self, client):
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "test", "sample_rate": 22050},
        )
        assert resp.status_code == 422

    def test_generate_missing_profile(self, client):
        resp = client.post(
            "/api/v1/filters/generate",
            json={},
        )
        assert resp.status_code == 422

    @patch("app.filter_routes._run_pipeline")
    def test_generate_with_custom_params(self, mock_pipeline, client):
        mock_pipeline.return_value = _mock_pipeline_result()
        resp = client.post(
            "/api/v1/filters/generate",
            json={
                "profile": "bose-home",
                "n_taps": 8192,
                "sample_rate": 96000,
                "target_phon": 65.0,
                "gains_db": {"sat_left": -20.0},
                "delays_ms": {"sub1": 3.5},
            },
        )
        assert resp.status_code == 200
        # Verify the request was passed through
        call_args = mock_pipeline.call_args[0][0]
        assert call_args.n_taps == 8192
        assert call_args.sample_rate == 96000
        assert call_args.target_phon == 65.0

    @patch("app.filter_routes._run_pipeline")
    def test_generate_pw_conf_in_result(self, mock_pipeline, client):
        result = _mock_pipeline_result()
        mock_pipeline.return_value = result
        resp = client.post(
            "/api/v1/filters/generate",
            json={"profile": "bose-home"},
        )
        data = resp.json()
        assert "pw_conf_path" in data


# -- GET /api/v1/filters/profiles -------------------------------------------

class TestProfilesEndpoint:
    def test_list_profiles(self, client):
        resp = client.get("/api/v1/filters/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert isinstance(data["profiles"], list)

    def test_profiles_contains_known(self, client):
        """If configs/speakers/profiles/ has files, they should appear."""
        resp = client.get("/api/v1/filters/profiles")
        profiles = resp.json()["profiles"]
        if _PROFILES_DIR.is_dir() and any(_PROFILES_DIR.glob("*.yml")):
            assert len(profiles) >= 1
