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

import math
import textwrap
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.test_tool.routes import (
    _parse_umik1_calibration,
    _parse_umik1_sensitivity,
    _a_weighting_db,
    _validate_cal_file,
)


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

    def test_response_includes_sensitivity(self, client, cal_file):
        """US-096: calibration response includes sensitivity from header."""
        with patch("app.test_tool.routes.UMIK1_CAL_PATH", cal_file):
            data = client.get("/api/v1/test-tool/calibration").json()
        assert "sensitivity_db" in data
        assert data["sensitivity_db"] == pytest.approx(-1.378)

    def test_response_includes_a_weighting(self, client, cal_file):
        """US-096: calibration response includes A-weighting curve."""
        with patch("app.test_tool.routes.UMIK1_CAL_PATH", cal_file):
            data = client.get("/api/v1/test-tool/calibration").json()
        assert "a_weighting" in data
        assert len(data["a_weighting"]) == len(data["frequencies"])

    def test_response_includes_cal_file_name(self, client, cal_file):
        """US-096: calibration response includes cal file name."""
        with patch("app.test_tool.routes.UMIK1_CAL_PATH", cal_file):
            data = client.get("/api/v1/test-tool/calibration").json()
        assert "cal_file" in data
        assert data["cal_file"].endswith(".txt")


# ── US-096: Sensitivity parsing ──────────────────────────────────

class TestSensitivityParsing:

    def test_extracts_sensitivity(self, cal_file):
        sens = _parse_umik1_sensitivity(cal_file)
        assert sens == pytest.approx(-1.378)

    def test_no_sensitivity_returns_none(self, tmp_path):
        """File without Sens Factor header returns None."""
        content = "20.000\t-0.13\n1000.000\t0.00\n"
        p = tmp_path / "no_sens.txt"
        p.write_text(content)
        assert _parse_umik1_sensitivity(str(p)) is None

    def test_positive_sensitivity(self, tmp_path):
        content = '"Sens Factor =2.5dB, SERNO: 123"\n20.000\t0.0\n'
        p = tmp_path / "pos_sens.txt"
        p.write_text(content)
        assert _parse_umik1_sensitivity(str(p)) == pytest.approx(2.5)


# ── US-096: A-weighting (IEC 61672) ─────────────────────────────

class TestAWeighting:

    def test_1khz_is_zero(self):
        """A-weighting at 1 kHz reference is 0 dB."""
        assert _a_weighting_db(1000.0) == pytest.approx(0.0, abs=0.05)

    def test_20hz_strong_attenuation(self):
        """A-weighting at 20 Hz is approximately -50 dB."""
        a20 = _a_weighting_db(20.0)
        assert a20 < -48
        assert a20 > -52

    def test_10khz_slight_attenuation(self):
        """A-weighting at 10 kHz is approximately -2.5 dB."""
        a10k = _a_weighting_db(10000.0)
        assert -5 < a10k < 0

    def test_zero_freq_returns_large_negative(self):
        assert _a_weighting_db(0.0) < -100

    def test_negative_freq_returns_large_negative(self):
        assert _a_weighting_db(-100.0) < -100

    def test_2khz_peak(self):
        """A-weighting peaks around 2-4 kHz (slight boost ~1 dB)."""
        a2k = _a_weighting_db(2500.0)
        assert -1 < a2k < 2

    def test_monotonic_below_2khz(self):
        """A-weighting increases monotonically from 20 Hz to ~2 kHz."""
        freqs = [20, 50, 100, 200, 500, 1000, 2000]
        vals = [_a_weighting_db(f) for f in freqs]
        for i in range(1, len(vals)):
            assert vals[i] >= vals[i - 1], (
                f"A-weight not monotonic: {freqs[i-1]}Hz={vals[i-1]:.1f} > "
                f"{freqs[i]}Hz={vals[i]:.1f}")


# ── US-096: Cal file validation ──────────────────────────────────

class TestCalFileValidation:

    def test_valid_file(self, cal_file):
        result = _validate_cal_file(cal_file)
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["sensitivity_db"] == pytest.approx(-1.378)
        assert result["num_points"] == 7

    def test_missing_file(self, tmp_path):
        result = _validate_cal_file(str(tmp_path / "nope.txt"))
        assert result["valid"] is False
        assert any("not found" in e.lower() for e in result["errors"])

    def test_no_header(self, tmp_path):
        content = "20.000\t-0.13\n1000.000\t0.00\n"
        p = tmp_path / "no_header.txt"
        p.write_text(content)
        result = _validate_cal_file(str(p))
        assert result["valid"] is False
        assert any("header" in e.lower() for e in result["errors"])

    def test_too_few_points(self, tmp_path):
        content = '"Sens Factor =-1.0dB, SERNO: 1"\n20.0\t0.0\n100.0\t0.0\n'
        p = tmp_path / "few_pts.txt"
        p.write_text(content)
        result = _validate_cal_file(str(p))
        assert result["valid"] is False
        assert any("too few" in e.lower() for e in result["errors"])

    def test_freq_range_info(self, cal_file):
        result = _validate_cal_file(cal_file)
        assert result["freq_range"] is not None
        assert result["freq_range"][0] == pytest.approx(20.0)
        assert result["freq_range"][1] == pytest.approx(20000.0)


# ── US-096: Cal file management endpoints ────────────────────────

class TestCalFileManagement:

    def test_list_files_empty_dir(self, client, tmp_path):
        """Empty cal dir returns empty list."""
        cal_dir = str(tmp_path / "cal")
        with patch("app.test_tool.routes.UMIK1_CAL_DIR", cal_dir):
            resp = client.get("/api/v1/test-tool/calibration/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["files"] == []

    def test_list_files_with_content(self, client, tmp_path, cal_file):
        """Cal dir with files returns them."""
        import shutil
        cal_dir = tmp_path / "cal"
        cal_dir.mkdir()
        shutil.copy(cal_file, str(cal_dir / "test_cal.txt"))
        with patch("app.test_tool.routes.UMIK1_CAL_DIR", str(cal_dir)):
            resp = client.get("/api/v1/test-tool/calibration/files")
        data = resp.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["name"] == "test_cal.txt"
        assert data["files"][0]["sensitivity_db"] == pytest.approx(-1.378)

    def test_validate_upload_valid(self, client, cal_file):
        """Valid cal file content validates successfully."""
        with open(cal_file) as f:
            content = f.read()
        resp = client.post("/api/v1/test-tool/calibration/validate",
                           content=content.encode())
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    def test_validate_upload_invalid(self, client):
        """Invalid content fails validation."""
        resp = client.post("/api/v1/test-tool/calibration/validate",
                           content=b"just garbage text\nno data here\n")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    def test_upload_saves_file(self, client, tmp_path, cal_file):
        """Upload endpoint saves validated file."""
        with open(cal_file) as f:
            content = f.read()
        cal_dir = str(tmp_path / "cal_upload")
        with patch("app.test_tool.routes.UMIK1_CAL_DIR", cal_dir):
            resp = client.post("/api/v1/test-tool/calibration/upload",
                               json={"name": "uploaded.txt",
                                     "content": content})
        assert resp.status_code == 200
        data = resp.json()
        assert data["saved"] is True
        import os
        assert os.path.isfile(os.path.join(cal_dir, "uploaded.txt"))

    def test_upload_rejects_invalid(self, client, tmp_path):
        """Upload rejects invalid cal file content."""
        cal_dir = str(tmp_path / "cal_reject")
        with patch("app.test_tool.routes.UMIK1_CAL_DIR", cal_dir):
            resp = client.post("/api/v1/test-tool/calibration/upload",
                               json={"name": "bad.txt",
                                     "content": "no data"})
        assert resp.status_code == 422

    def test_upload_rejects_bad_filename(self, client):
        """Upload rejects path-traversal filenames."""
        resp = client.post("/api/v1/test-tool/calibration/upload",
                           json={"name": "../etc/passwd",
                                 "content": "x"})
        assert resp.status_code == 400
