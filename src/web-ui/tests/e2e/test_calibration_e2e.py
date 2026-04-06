"""E2E tests for US-096: UMIK-1 calibration pipeline.

Verifies calibration data retrieval, file listing, validation, and upload
against the real local-demo stack.

The calibration endpoints live under /api/v1/test-tool/calibration and
provide access to UMIK-1 calibration files (miniDSP format with frequency/dB
pairs and a sensitivity line).

The local-demo stack sets PI4AUDIO_SIGGEN=1 but does NOT set
PI4AUDIO_UMIK1_CAL or PI4AUDIO_CAL_DIR, so:
    - GET /calibration may 404 if no cal file exists at the default path
    - GET /calibration/files returns the default cal dir listing (may be empty)
    - POST /calibration/validate accepts raw text content
    - POST /calibration/upload saves to PI4AUDIO_CAL_DIR

Prerequisites:
    - ``nix run .#local-demo`` running
    - No mocks -- all operations happen against real endpoints

Usage:
    nix run .#test-e2e
"""

import os

import pytest


pytestmark = [pytest.mark.e2e]

# A minimal valid UMIK-1 calibration file content (miniDSP format).
# The header line must contain "Sens Factor" and frequency/dB pairs follow.
VALID_CAL_CONTENT = """\
"Sens Factor =-1.378dB, SERNO: 0000001"
20.000\t-0.32
30.000\t-0.15
50.000\t-0.05
100.000\t0.02
200.000\t0.05
500.000\t0.03
1000.000\t0.00
2000.000\t0.01
5000.000\t-0.10
10000.000\t-0.42
20000.000\t-2.81
"""

# Invalid content (not parseable as a cal file).
INVALID_CAL_CONTENT = """\
This is not a calibration file.
Just some random text without frequency/dB pairs.
"""

# Test upload filename (cleaned up after tests).
TEST_CAL_FILENAME = "e2e-test-cal-0000001.txt"


class TestCalibrationEndpoint:
    """GET /api/v1/test-tool/calibration returns calibration data.

    The response depends on whether a UMIK-1 cal file exists at the
    configured path. In local-demo, the default path is
    /home/ela/7161942.txt which may or may not exist.
    """

    def test_calibration_returns_data_or_404(self, api_get):
        """GET /calibration returns cal data (200) or not found (404)."""
        status, body = api_get("/api/v1/test-tool/calibration")
        assert status in (200, 404), (
            f"Expected 200 or 404, got {status}: {body}"
        )
        if status == 200:
            # Verify response structure.
            assert "frequencies" in body
            assert "db_corrections" in body
            assert "a_weighting" in body
            assert "cal_file" in body

            freqs = body["frequencies"]
            corrections = body["db_corrections"]
            a_weights = body["a_weighting"]

            # Frequencies should be non-empty and monotonically increasing.
            assert len(freqs) > 0, "Empty frequency array"
            for i in range(1, len(freqs)):
                assert freqs[i] > freqs[i - 1], (
                    f"Frequencies not monotonic at index {i}: "
                    f"{freqs[i - 1]} >= {freqs[i]}"
                )

            # Corrections and A-weighting arrays must match frequency length.
            assert len(corrections) == len(freqs), (
                f"corrections length {len(corrections)} != "
                f"frequencies length {len(freqs)}"
            )
            assert len(a_weights) == len(freqs), (
                f"a_weighting length {len(a_weights)} != "
                f"frequencies length {len(freqs)}"
            )

            # A-weighting at 1 kHz should be ~0 dB (reference frequency).
            # Find the closest frequency to 1000 Hz.
            closest_idx = min(
                range(len(freqs)),
                key=lambda i: abs(freqs[i] - 1000.0),
            )
            if abs(freqs[closest_idx] - 1000.0) < 50:
                a_1k = a_weights[closest_idx]
                assert -1.0 < a_1k < 1.0, (
                    f"A-weighting at ~1 kHz should be ~0 dB, got {a_1k}"
                )

            # A-weighting at low frequencies should be strongly negative.
            if freqs[0] <= 30.0:
                assert a_weights[0] < -20.0, (
                    f"A-weighting at {freqs[0]} Hz should be < -20 dB, "
                    f"got {a_weights[0]}"
                )

        elif status == 404:
            assert body.get("error") == "calibration_file_not_found"


class TestCalibrationFileListing:
    """GET /api/v1/test-tool/calibration/files lists available cal files."""

    def test_list_returns_structure(self, api_get):
        """File listing returns expected JSON structure."""
        status, body = api_get("/api/v1/test-tool/calibration/files")
        assert status == 200, f"Expected 200, got {status}: {body}"
        assert "files" in body
        assert "active" in body
        assert isinstance(body["files"], list)
        assert isinstance(body["active"], str)

    def test_file_entries_have_metadata(self, api_get):
        """Each file entry has name and sensitivity_db fields."""
        status, body = api_get("/api/v1/test-tool/calibration/files")
        assert status == 200
        for entry in body.get("files", []):
            assert "name" in entry, f"Missing 'name' in entry: {entry}"
            assert "sensitivity_db" in entry, (
                f"Missing 'sensitivity_db' in entry: {entry}"
            )


class TestCalibrationValidation:
    """POST /api/v1/test-tool/calibration/validate checks file content."""

    def test_validate_valid_cal_content(self, base_url):
        """Valid miniDSP calibration content passes validation."""
        import urllib.request
        import urllib.error
        import json

        req = urllib.request.Request(
            f"{base_url}/api/v1/test-tool/calibration/validate",
            data=VALID_CAL_CONTENT.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            body = json.loads(resp.read())
            status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            body = json.loads(raw) if raw else {}

        assert status == 200, f"Expected 200, got {status}: {body}"
        assert body.get("valid") is True, (
            f"Valid cal content should pass validation: {body}"
        )
        assert body.get("num_points", 0) > 0, (
            f"Expected non-zero point count: {body}"
        )
        assert body.get("sensitivity_db") is not None, (
            f"Expected sensitivity_db in response: {body}"
        )

    def test_validate_invalid_cal_content(self, base_url):
        """Invalid content fails validation."""
        import urllib.request
        import urllib.error
        import json

        req = urllib.request.Request(
            f"{base_url}/api/v1/test-tool/calibration/validate",
            data=INVALID_CAL_CONTENT.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            body = json.loads(resp.read())
            status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            body = json.loads(raw) if raw else {}

        assert status == 200, f"Expected 200, got {status}: {body}"
        assert body.get("valid") is False, (
            f"Invalid cal content should fail validation: {body}"
        )
        assert len(body.get("errors", [])) > 0, (
            f"Expected validation errors: {body}"
        )

    def test_validate_empty_content(self, base_url):
        """Empty content fails validation."""
        import urllib.request
        import urllib.error
        import json

        req = urllib.request.Request(
            f"{base_url}/api/v1/test-tool/calibration/validate",
            data=b"",
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            body = json.loads(resp.read())
            status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            body = json.loads(raw) if raw else {}

        assert status == 200, f"Expected 200, got {status}: {body}"
        assert body.get("valid") is False, (
            f"Empty content should fail validation: {body}"
        )


class TestCalibrationUpload:
    """POST /api/v1/test-tool/calibration/upload saves a cal file."""

    def test_upload_valid_file(self, api_post, api_get):
        """Upload a valid cal file and verify it appears in listing."""
        status, body = api_post(
            "/api/v1/test-tool/calibration/upload",
            {
                "name": TEST_CAL_FILENAME,
                "content": VALID_CAL_CONTENT,
            },
        )
        assert status == 200, f"Upload failed: {status} {body}"
        assert body.get("saved") is True, f"Upload not saved: {body}"
        assert body.get("name") == TEST_CAL_FILENAME

        # Verify the validation data is included in the response.
        validation = body.get("validation", {})
        assert validation.get("valid") is True, (
            f"Uploaded file should be valid: {validation}"
        )

        # Verify it appears in the file listing.
        list_status, list_body = api_get(
            "/api/v1/test-tool/calibration/files")
        if list_status == 200:
            file_names = [f["name"] for f in list_body.get("files", [])]
            assert TEST_CAL_FILENAME in file_names, (
                f"Uploaded file not in listing: {file_names}"
            )

    def test_upload_invalid_content_rejected(self, api_post):
        """Upload with invalid cal content is rejected (422)."""
        status, body = api_post(
            "/api/v1/test-tool/calibration/upload",
            {
                "name": "invalid-test.txt",
                "content": INVALID_CAL_CONTENT,
            },
        )
        assert status == 422, (
            f"Expected 422 for invalid content, got {status}: {body}"
        )
        assert body.get("error") == "validation_failed"

    def test_upload_unsafe_filename_rejected(self, api_post):
        """Upload with path traversal filename is rejected (400)."""
        status, body = api_post(
            "/api/v1/test-tool/calibration/upload",
            {
                "name": "../../../tmp/evil.txt",
                "content": VALID_CAL_CONTENT,
            },
        )
        assert status == 400, (
            f"Expected 400 for unsafe filename, got {status}: {body}"
        )
        assert body.get("error") == "invalid_filename"

    def test_upload_no_extension_rejected(self, api_post):
        """Upload without .txt extension is rejected (400)."""
        status, body = api_post(
            "/api/v1/test-tool/calibration/upload",
            {
                "name": "noextension",
                "content": VALID_CAL_CONTENT,
            },
        )
        assert status == 400, (
            f"Expected 400 for missing extension, got {status}: {body}"
        )

    def test_upload_empty_name_rejected(self, api_post):
        """Upload with empty filename is rejected (400)."""
        status, body = api_post(
            "/api/v1/test-tool/calibration/upload",
            {
                "name": "",
                "content": VALID_CAL_CONTENT,
            },
        )
        assert status == 400, (
            f"Expected 400 for empty filename, got {status}: {body}"
        )


class TestCalibrationMeasurementIntegration:
    """Verify measurement session stores calibration_file reference.

    POST /api/v1/measurement/start accepts a calibration_file parameter.
    In local-demo mock mode the session starts and stores the cal file
    reference in its config. The status endpoint reflects this back.
    """

    def test_measurement_start_accepts_cal_file(self, api_post, api_get):
        """Start a measurement with calibration_file, verify status shows it."""
        cal_file = "e2e-test-calibration.txt"

        # Start a measurement session with calibration_file set.
        # Minimal channel config required by StartRequest.
        start_status, start_body = api_post(
            "/api/v1/measurement/start",
            {
                "channels": [
                    {
                        "index": 0,
                        "name": "E2E Test Channel",
                        "target_spl_db": 75.0,
                        "thermal_ceiling_dbfs": -20.0,
                    }
                ],
                "calibration_file": cal_file,
                "positions": 1,
                "sweep_duration_s": 1.0,
                "sweep_level_dbfs": -40.0,
            },
            timeout=15.0,
        )

        # Session may start (200) or conflict if one is already running (409).
        # Also 503 if signal-gen is unavailable.
        if start_status == 409:
            pytest.skip("Measurement session already running (409)")
        if start_status == 503:
            pytest.skip("Signal generator unavailable (503)")

        assert start_status == 200, (
            f"Expected 200 from measurement/start, got {start_status}: "
            f"{start_body}"
        )
        assert start_body.get("status") == "started"

        try:
            # Check that the status endpoint reflects the calibration_file.
            status_code, status_body = api_get(
                "/api/v1/measurement/status"
            )
            assert status_code == 200, (
                f"Expected 200 from measurement/status, got {status_code}: "
                f"{status_body}"
            )

            # calibration info is nested under "calibration.file"
            cal_info = status_body.get("calibration", {})
            assert cal_info.get("file") == cal_file, (
                f"Expected calibration.file={cal_file!r}, "
                f"got {cal_info.get('file')!r} in status: {status_body}"
            )
        finally:
            # Always abort the session to clean up, regardless of assertions.
            api_post("/api/v1/measurement/abort", timeout=10.0)


class TestCalibrationVerifyGraceful:
    """POST /api/v1/test-tool/calibration/verify handles missing hardware.

    In local-demo without a real UMIK-1, the verify endpoint should fail
    gracefully rather than crash with a 500. This tests the hardware-absent
    code path.

    The /calibration/verify endpoint requires PI4AUDIO_SIGGEN=1 (set in
    local-demo). Without real UMIK-1 hardware, it should return a structured
    error (measurement_failed or siggen_error), not a server crash.
    """

    def test_verify_without_hardware_returns_error(self, api_post):
        """Calibration verify without UMIK-1 returns structured error."""
        status, body = api_post(
            "/api/v1/test-tool/calibration/verify",
            timeout=15.0,
        )
        # In local-demo with signal-gen but no UMIK-1:
        # - 200 with passed=false and error details, OR
        # - 502 if signal-gen play fails, OR
        # - 404/501 if the endpoint is not enabled
        # The key assertion: NOT a 500 server crash.
        assert status != 500, (
            f"Calibration verify crashed (500): {body}"
        )
        if status == 200:
            # Should report measurement failure, not success.
            if body.get("passed") is False:
                assert "error" in body or "detail" in body, (
                    f"Expected error details in failed verify: {body}"
                )
