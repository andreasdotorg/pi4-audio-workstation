"""Tests for T-088-5 / T-088-8: UMIK-1 calibration endpoint and routing.

Covers:
    - Successful parsing of a valid miniDSP calibration file
    - 404 when calibration file does not exist
    - 422 when calibration file contains no usable data
    - Header lines (starting with " or *) are skipped
    - Malformed numeric lines are skipped gracefully
    - Whitespace-only lines are skipped
    - Endpoint works without SIGGEN mode (read-only data)
    - Response arrays are parallel (same length)
    - Frequencies are monotonically increasing (frontend binary search)
"""

import textwrap
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.test_tool.routes import _parse_umik1_calibration


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def cal_file(tmp_path):
    """Write a realistic miniDSP UMIK-1 calibration file and return its path."""
    content = textwrap.dedent("""\
        "Sens Factor =-1.378dB, SERNO: 7161942"
        * Freq(Hz)  dB
        20.000	-0.13
        21.135	-0.11
        50.000	0.02
        100.000	0.15
        1000.000	0.00
        10000.000	-0.22
        20000.000	-1.05
    """)
    p = tmp_path / "umik1_cal.txt"
    p.write_text(content)
    return str(p)


@pytest.fixture
def empty_cal_file(tmp_path):
    """Calibration file with only header lines (no usable data)."""
    content = textwrap.dedent("""\
        "Sens Factor =-1.378dB, SERNO: 7161942"
        * Freq(Hz)  dB
        * This file has no data lines
    """)
    p = tmp_path / "empty_cal.txt"
    p.write_text(content)
    return str(p)


@pytest.fixture
def malformed_cal_file(tmp_path):
    """Calibration file with some malformed lines mixed in."""
    content = textwrap.dedent("""\
        "Header"
        20.000	-0.13
        not_a_number	also_bad
        100.000	0.15
        single_column
        1000.000	0.00
    """)
    p = tmp_path / "malformed_cal.txt"
    p.write_text(content)
    return str(p)


# ── Unit tests for _parse_umik1_calibration ───────────────────────

class TestParseCalibration:

    def test_valid_file(self, cal_file):
        freqs, db = _parse_umik1_calibration(cal_file)
        assert len(freqs) == 7
        assert len(db) == 7
        assert freqs[0] == pytest.approx(20.0)
        assert db[0] == pytest.approx(-0.13)
        assert freqs[-1] == pytest.approx(20000.0)
        assert db[-1] == pytest.approx(-1.05)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _parse_umik1_calibration(str(tmp_path / "nonexistent.txt"))

    def test_empty_data_raises(self, empty_cal_file):
        with pytest.raises(ValueError, match="No calibration data"):
            _parse_umik1_calibration(empty_cal_file)

    def test_malformed_lines_skipped(self, malformed_cal_file):
        freqs, db = _parse_umik1_calibration(malformed_cal_file)
        assert len(freqs) == 3
        assert freqs == [pytest.approx(20.0), pytest.approx(100.0),
                         pytest.approx(1000.0)]
        assert db == [pytest.approx(-0.13), pytest.approx(0.15),
                      pytest.approx(0.0)]

    def test_whitespace_only_lines_skipped(self, tmp_path):
        content = "20.000\t-0.13\n   \n\t\n100.000\t0.15\n"
        p = tmp_path / "ws_cal.txt"
        p.write_text(content)
        freqs, db = _parse_umik1_calibration(str(p))
        assert len(freqs) == 2

    def test_parallel_arrays(self, cal_file):
        freqs, db = _parse_umik1_calibration(cal_file)
        assert len(freqs) == len(db)

    def test_frequencies_monotonically_increasing(self, cal_file):
        """Frontend binary search requires sorted frequencies."""
        freqs, _ = _parse_umik1_calibration(cal_file)
        for i in range(1, len(freqs)):
            assert freqs[i] > freqs[i - 1], (
                f"Freq[{i}]={freqs[i]} not > freq[{i-1}]={freqs[i-1]}"
            )


# ── Endpoint integration tests ────────────────────────────────────

class TestCalibrationEndpoint:

    def test_success(self, client, cal_file):
        with patch("app.test_tool.routes.UMIK1_CAL_PATH", cal_file):
            resp = client.get("/api/v1/test-tool/calibration")
        assert resp.status_code == 200
        data = resp.json()
        assert "frequencies" in data
        assert "db_corrections" in data
        assert len(data["frequencies"]) == 7
        assert len(data["db_corrections"]) == 7
        assert data["frequencies"][0] == pytest.approx(20.0)
        assert data["db_corrections"][0] == pytest.approx(-0.13)

    def test_file_not_found(self, client, tmp_path):
        missing = str(tmp_path / "does_not_exist.txt")
        with patch("app.test_tool.routes.UMIK1_CAL_PATH", missing):
            resp = client.get("/api/v1/test-tool/calibration")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"] == "calibration_file_not_found"

    def test_empty_data(self, client, empty_cal_file):
        with patch("app.test_tool.routes.UMIK1_CAL_PATH", empty_cal_file):
            resp = client.get("/api/v1/test-tool/calibration")
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"] == "calibration_parse_error"

    def test_works_without_siggen_mode(self, client, cal_file):
        """Calibration is read-only data — does NOT require PI4AUDIO_SIGGEN=1."""
        with patch("app.test_tool.routes.UMIK1_CAL_PATH", cal_file), \
             patch("app.test_tool.routes.SIGGEN_MODE", False):
            resp = client.get("/api/v1/test-tool/calibration")
        assert resp.status_code == 200

    def test_response_arrays_parallel(self, client, cal_file):
        """frequencies and db_corrections must have the same length."""
        with patch("app.test_tool.routes.UMIK1_CAL_PATH", cal_file):
            data = client.get("/api/v1/test-tool/calibration").json()
        assert len(data["frequencies"]) == len(data["db_corrections"])

    def test_response_frequencies_sorted(self, client, cal_file):
        """Frontend interpolation relies on sorted frequency array."""
        with patch("app.test_tool.routes.UMIK1_CAL_PATH", cal_file):
            data = client.get("/api/v1/test-tool/calibration").json()
        freqs = data["frequencies"]
        for i in range(1, len(freqs)):
            assert freqs[i] > freqs[i - 1]
