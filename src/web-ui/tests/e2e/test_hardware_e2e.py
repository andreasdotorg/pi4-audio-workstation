"""E2E tests for US-093: Amplifier and DAC hardware configuration CRUD.

Verifies the complete hardware config lifecycle against the real local-demo
stack: list, create, read, update, delete for both amplifier and DAC profiles.
Also tests validation (reject invalid data) and safety (reject path traversal
in profile names).

The local-demo stack provides:
    - PI4AUDIO_HARDWARE_DIR = /tmp/pi4audio-demo/hardware
    - Seed data: mcgrey-pa4504 amplifier, behringer-ada8200 DAC

Prerequisites:
    - ``nix run .#local-demo`` running
    - No mocks -- all operations happen against real YAML files

Usage:
    nix run .#test-e2e
"""

import pytest


pytestmark = [pytest.mark.e2e, pytest.mark.destructive]

# Seed data from local-demo (copied from configs/hardware/).
SEED_AMP = "mcgrey-pa4504"
SEED_DAC = "behringer-ada8200"

# Test profile names (cleaned up after each test).
TEST_AMP_SLUG = "e2e-test-amp"
TEST_DAC_SLUG = "e2e-test-dac"

# Valid amplifier payload for create/update tests.
VALID_AMP = {
    "name": "E2E Test Amp",
    "slug": TEST_AMP_SLUG,
    "type": "class_d",
    "channels": 2,
    "power_per_channel_watts": 200,
    "impedance_rated_ohms": 8,
    "voltage_gain": 30.0,
}

# Valid DAC payload for create/update tests.
VALID_DAC = {
    "name": "E2E Test DAC",
    "slug": TEST_DAC_SLUG,
    "type": "usb_audio",
    "channels": 2,
    "output_0dbfs_vrms": 2.0,
}


def _cleanup_test_profiles(api_post, api_get):
    """Delete test profiles if they exist (best-effort cleanup)."""
    for name in (TEST_AMP_SLUG,):
        status, _ = api_get(f"/api/v1/hardware/amplifiers/{name}")
        if status == 200:
            api_post_delete(api_post, f"/api/v1/hardware/amplifiers/{name}")
    for name in (TEST_DAC_SLUG,):
        status, _ = api_get(f"/api/v1/hardware/dacs/{name}")
        if status == 200:
            api_post_delete(api_post, f"/api/v1/hardware/dacs/{name}")


def _api_put(base_url, path, body, timeout=10.0):
    """PUT helper for update operations."""
    import json
    import urllib.request
    import urllib.error
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else {}


def _api_delete(base_url, path, timeout=10.0):
    """DELETE helper for removal operations."""
    import json
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        f"{base_url}{path}",
        method="DELETE",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else {}


class TestAmplifierList:
    """GET /api/v1/hardware/amplifiers lists seed data."""

    def test_list_returns_seed_amp(self, api_get):
        """Seed amplifier profile appears in the listing."""
        status, body = api_get("/api/v1/hardware/amplifiers")
        assert status == 200
        amps = body.get("amplifiers", [])
        names = [a["name"] for a in amps]
        assert SEED_AMP in names, (
            f"Expected '{SEED_AMP}' in amplifier list, got {names}"
        )

    def test_read_seed_amp(self, api_get):
        """Read the seeded McGrey PA4504 amplifier profile."""
        status, body = api_get(f"/api/v1/hardware/amplifiers/{SEED_AMP}")
        assert status == 200
        assert body.get("name") == "McGrey PA4504"
        assert body.get("type") == "class_d"
        assert body.get("channels") == 4
        assert body.get("power_per_channel_watts") == 450
        assert body.get("impedance_rated_ohms") == 4
        assert body.get("voltage_gain") == 42.4


class TestAmplifierCRUD:
    """Create, read, update, delete amplifier profiles."""

    def test_create_read_update_delete(self, api_post, api_get, base_url):
        """Full CRUD lifecycle for an amplifier profile."""
        # Cleanup any leftover from a previous failed run.
        _api_delete(base_url, f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")

        # Create
        status, body = api_post("/api/v1/hardware/amplifiers", VALID_AMP)
        assert status == 201, f"Create failed: {status} {body}"
        assert body.get("ok") is True
        assert body.get("name") == TEST_AMP_SLUG

        try:
            # Read back
            status, body = api_get(
                f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")
            assert status == 200
            assert body.get("name") == "E2E Test Amp"
            assert body.get("type") == "class_d"
            assert body.get("channels") == 2
            assert body.get("voltage_gain") == 30.0

            # Update
            updated = {**VALID_AMP, "channels": 4, "voltage_gain": 35.0}
            updated.pop("slug", None)
            status, body = _api_put(
                base_url,
                f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}",
                updated,
            )
            assert status == 200, f"Update failed: {status} {body}"
            assert body.get("ok") is True

            # Verify update
            status, body = api_get(
                f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")
            assert status == 200
            assert body.get("channels") == 4
            assert body.get("voltage_gain") == 35.0

        finally:
            # Delete (cleanup)
            status, body = _api_delete(
                base_url,
                f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}",
            )
            assert status == 200, f"Delete failed: {status} {body}"
            assert body.get("ok") is True

        # Verify deletion
        status, _ = api_get(
            f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")
        assert status == 404

    def test_create_conflict(self, api_post, api_get, base_url):
        """Creating a duplicate amplifier returns 409."""
        _api_delete(base_url, f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")
        status, _ = api_post("/api/v1/hardware/amplifiers", VALID_AMP)
        assert status == 201

        try:
            status, body = api_post("/api/v1/hardware/amplifiers", VALID_AMP)
            assert status == 409, (
                f"Expected 409 for duplicate, got {status}: {body}"
            )
            assert body.get("error") == "already_exists"
        finally:
            _api_delete(base_url,
                        f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")

    def test_read_nonexistent(self, api_get):
        """Reading a non-existent amplifier returns 404."""
        status, body = api_get(
            "/api/v1/hardware/amplifiers/nonexistent-amp-xyz")
        assert status == 404
        assert body.get("error") == "not_found"

    def test_delete_nonexistent(self, base_url):
        """Deleting a non-existent amplifier returns 404."""
        status, body = _api_delete(
            base_url, "/api/v1/hardware/amplifiers/nonexistent-amp-xyz")
        assert status == 404
        assert body.get("error") == "not_found"


class TestDacList:
    """GET /api/v1/hardware/dacs lists seed data."""

    def test_list_returns_seed_dac(self, api_get):
        """Seed DAC profile appears in the listing."""
        status, body = api_get("/api/v1/hardware/dacs")
        assert status == 200
        dacs = body.get("dacs", [])
        names = [d["name"] for d in dacs]
        assert SEED_DAC in names, (
            f"Expected '{SEED_DAC}' in DAC list, got {names}"
        )

    def test_read_seed_dac(self, api_get):
        """Read the seeded Behringer ADA8200 DAC profile."""
        status, body = api_get(f"/api/v1/hardware/dacs/{SEED_DAC}")
        assert status == 200
        assert body.get("name") == "Behringer ADA8200"
        assert body.get("type") == "adat_converter"
        assert body.get("channels") == 8
        assert body.get("output_0dbfs_vrms") == 4.9


class TestDacCRUD:
    """Create, read, update, delete DAC profiles."""

    def test_create_read_update_delete(self, api_post, api_get, base_url):
        """Full CRUD lifecycle for a DAC profile."""
        _api_delete(base_url, f"/api/v1/hardware/dacs/{TEST_DAC_SLUG}")

        # Create
        status, body = api_post("/api/v1/hardware/dacs", VALID_DAC)
        assert status == 201, f"Create failed: {status} {body}"
        assert body.get("ok") is True
        assert body.get("name") == TEST_DAC_SLUG

        try:
            # Read back
            status, body = api_get(
                f"/api/v1/hardware/dacs/{TEST_DAC_SLUG}")
            assert status == 200
            assert body.get("name") == "E2E Test DAC"
            assert body.get("type") == "usb_audio"
            assert body.get("output_0dbfs_vrms") == 2.0

            # Update
            updated = {**VALID_DAC, "channels": 4, "output_0dbfs_vrms": 3.5}
            updated.pop("slug", None)
            status, body = _api_put(
                base_url,
                f"/api/v1/hardware/dacs/{TEST_DAC_SLUG}",
                updated,
            )
            assert status == 200, f"Update failed: {status} {body}"

            # Verify update
            status, body = api_get(
                f"/api/v1/hardware/dacs/{TEST_DAC_SLUG}")
            assert status == 200
            assert body.get("channels") == 4
            assert body.get("output_0dbfs_vrms") == 3.5

        finally:
            _api_delete(base_url,
                        f"/api/v1/hardware/dacs/{TEST_DAC_SLUG}")

        # Verify deletion
        status, _ = api_get(f"/api/v1/hardware/dacs/{TEST_DAC_SLUG}")
        assert status == 404


class TestAmplifierValidation:
    """Reject invalid amplifier data (422)."""

    def test_missing_required_fields(self, api_post, base_url):
        """Amplifier with missing required fields returns 422."""
        _api_delete(base_url, f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")
        status, body = api_post("/api/v1/hardware/amplifiers", {
            "name": "Incomplete Amp",
            "slug": TEST_AMP_SLUG,
            "type": "class_d",
            # Missing: channels, power_per_channel_watts,
            #          impedance_rated_ohms, voltage_gain
        })
        assert status == 422, f"Expected 422, got {status}: {body}"
        assert body.get("error") == "validation"

    def test_invalid_amp_type(self, api_post, base_url):
        """Amplifier with invalid type returns 422."""
        _api_delete(base_url, f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")
        bad = {**VALID_AMP, "type": "invalid_type"}
        status, body = api_post("/api/v1/hardware/amplifiers", bad)
        assert status == 422, f"Expected 422, got {status}: {body}"

    def test_negative_power(self, api_post, base_url):
        """Amplifier with negative power returns 422."""
        _api_delete(base_url, f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")
        bad = {**VALID_AMP, "power_per_channel_watts": -100}
        status, body = api_post("/api/v1/hardware/amplifiers", bad)
        assert status == 422, f"Expected 422, got {status}: {body}"

    def test_zero_voltage_gain(self, api_post, base_url):
        """Amplifier with zero voltage gain returns 422."""
        _api_delete(base_url, f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")
        bad = {**VALID_AMP, "voltage_gain": 0}
        status, body = api_post("/api/v1/hardware/amplifiers", bad)
        assert status == 422, f"Expected 422, got {status}: {body}"

    def test_zero_channels(self, api_post, base_url):
        """Amplifier with zero channels returns 422."""
        _api_delete(base_url, f"/api/v1/hardware/amplifiers/{TEST_AMP_SLUG}")
        bad = {**VALID_AMP, "channels": 0}
        status, body = api_post("/api/v1/hardware/amplifiers", bad)
        assert status == 422, f"Expected 422, got {status}: {body}"


class TestDacValidation:
    """Reject invalid DAC data (422)."""

    def test_missing_required_fields(self, api_post, base_url):
        """DAC with missing required fields returns 422."""
        _api_delete(base_url, f"/api/v1/hardware/dacs/{TEST_DAC_SLUG}")
        status, body = api_post("/api/v1/hardware/dacs", {
            "name": "Incomplete DAC",
            "slug": TEST_DAC_SLUG,
            # Missing: type, channels, output_0dbfs_vrms
        })
        assert status == 422, f"Expected 422, got {status}: {body}"

    def test_invalid_dac_type(self, api_post, base_url):
        """DAC with invalid type returns 422."""
        _api_delete(base_url, f"/api/v1/hardware/dacs/{TEST_DAC_SLUG}")
        bad = {**VALID_DAC, "type": "invalid_type"}
        status, body = api_post("/api/v1/hardware/dacs", bad)
        assert status == 422, f"Expected 422, got {status}: {body}"

    def test_negative_output_level(self, api_post, base_url):
        """DAC with negative output level returns 422."""
        _api_delete(base_url, f"/api/v1/hardware/dacs/{TEST_DAC_SLUG}")
        bad = {**VALID_DAC, "output_0dbfs_vrms": -1.0}
        status, body = api_post("/api/v1/hardware/dacs", bad)
        assert status == 422, f"Expected 422, got {status}: {body}"


class TestHardwareNameSafety:
    """S-001: Reject path traversal and invalid characters in profile names."""

    def test_amp_path_traversal_rejected(self, api_get):
        """Amplifier name with path traversal returns 400."""
        status, body = api_get("/api/v1/hardware/amplifiers/../../../etc/passwd")
        # FastAPI may normalize the path or the handler rejects it.
        assert status in (400, 404, 422), (
            f"Expected rejection for path traversal, got {status}: {body}"
        )

    def test_amp_dotdot_name_rejected(self, api_get):
        """Amplifier name starting with dot is rejected."""
        status, body = api_get("/api/v1/hardware/amplifiers/.hidden")
        assert status in (400, 404), (
            f"Expected 400/404 for dot-prefixed name, got {status}: {body}"
        )

    def test_dac_path_traversal_rejected(self, api_get):
        """DAC name with path traversal returns 400."""
        status, body = api_get("/api/v1/hardware/dacs/../../../etc/passwd")
        assert status in (400, 404, 422), (
            f"Expected rejection for path traversal, got {status}: {body}"
        )

    def test_amp_create_unsafe_name(self, api_post, base_url):
        """Creating amp with unsafe slug is rejected."""
        bad = {**VALID_AMP, "slug": "../../../tmp/evil"}
        status, body = api_post("/api/v1/hardware/amplifiers", bad)
        assert status == 400, (
            f"Expected 400 for unsafe name, got {status}: {body}"
        )
        if status == 400:
            assert body.get("error") == "invalid_name"
