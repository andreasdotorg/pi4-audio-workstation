"""Tests for hardware configuration CRUD API (US-093 / T-093-1).

Covers amplifier and DAC profile CRUD operations, validation, path
traversal rejection, and safe name checks.
"""

import os
import shutil
import tempfile

import pytest
import yaml
from starlette.testclient import TestClient

from app.main import app
import app.hardware_routes as hw_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _use_tmp_hardware_dir(tmp_path):
    """Point hardware_routes at a temp directory for each test."""
    amp_dir = tmp_path / "amplifiers"
    dac_dir = tmp_path / "dacs"
    amp_dir.mkdir()
    dac_dir.mkdir()

    original_pi = hw_mod._PI_HARDWARE_DIR
    original_repo = hw_mod._REPO_HARDWARE_DIR
    hw_mod._PI_HARDWARE_DIR = tmp_path
    hw_mod._REPO_HARDWARE_DIR = tmp_path
    yield tmp_path
    hw_mod._PI_HARDWARE_DIR = original_pi
    hw_mod._REPO_HARDWARE_DIR = original_repo


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_AMP = {
    "name": "Test Amp",
    "type": "class_d",
    "channels": 4,
    "power_per_channel_watts": 450,
    "impedance_rated_ohms": 4,
    "voltage_gain": 42.4,
}

VALID_DAC = {
    "name": "Test DAC",
    "type": "usb_audio",
    "channels": 8,
    "output_0dbfs_vrms": 4.9,
}


def _seed_amp(tmp_path, slug="test-amp", data=None):
    """Write an amp YAML file into the temp dir."""
    d = data or {**VALID_AMP}
    path = tmp_path / "amplifiers" / f"{slug}.yml"
    path.write_text(yaml.dump(d, default_flow_style=False))
    return path


def _seed_dac(tmp_path, slug="test-dac", data=None):
    """Write a DAC YAML file into the temp dir."""
    d = data or {**VALID_DAC}
    path = tmp_path / "dacs" / f"{slug}.yml"
    path.write_text(yaml.dump(d, default_flow_style=False))
    return path


# ===========================================================================
# Amplifier CRUD
# ===========================================================================

class TestListAmplifiers:
    def test_empty(self, client):
        resp = client.get("/api/v1/hardware/amplifiers")
        assert resp.status_code == 200
        assert resp.json()["amplifiers"] == []

    def test_with_entries(self, client, _use_tmp_hardware_dir):
        _seed_amp(_use_tmp_hardware_dir, "amp-a", {**VALID_AMP, "name": "Amp A"})
        _seed_amp(_use_tmp_hardware_dir, "amp-b", {**VALID_AMP, "name": "Amp B"})
        resp = client.get("/api/v1/hardware/amplifiers")
        assert resp.status_code == 200
        names = [a["name"] for a in resp.json()["amplifiers"]]
        assert "amp-a" in names
        assert "amp-b" in names


class TestGetAmplifier:
    def test_found(self, client, _use_tmp_hardware_dir):
        _seed_amp(_use_tmp_hardware_dir)
        resp = client.get("/api/v1/hardware/amplifiers/test-amp")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Amp"

    def test_not_found(self, client):
        resp = client.get("/api/v1/hardware/amplifiers/nonexistent")
        assert resp.status_code == 404

    def test_path_traversal(self, client):
        resp = client.get("/api/v1/hardware/amplifiers/../../../etc/passwd")
        assert resp.status_code in (400, 404, 422)


class TestCreateAmplifier:
    def test_success(self, client):
        resp = client.post("/api/v1/hardware/amplifiers", json=VALID_AMP)
        assert resp.status_code == 201
        assert resp.json()["ok"] is True
        assert resp.json()["name"] == "test-amp"

    def test_duplicate(self, client, _use_tmp_hardware_dir):
        _seed_amp(_use_tmp_hardware_dir)
        resp = client.post("/api/v1/hardware/amplifiers", json=VALID_AMP)
        assert resp.status_code == 409

    def test_missing_fields(self, client):
        resp = client.post("/api/v1/hardware/amplifiers", json={"name": "Bad"})
        assert resp.status_code == 422

    def test_invalid_type(self, client):
        body = {**VALID_AMP, "type": "nuclear"}
        resp = client.post("/api/v1/hardware/amplifiers", json=body)
        assert resp.status_code == 422

    def test_negative_power(self, client):
        body = {**VALID_AMP, "power_per_channel_watts": -100}
        resp = client.post("/api/v1/hardware/amplifiers", json=body)
        assert resp.status_code == 422

    def test_custom_slug(self, client):
        body = {**VALID_AMP, "slug": "my-custom-slug"}
        resp = client.post("/api/v1/hardware/amplifiers", json=body)
        assert resp.status_code == 201
        assert resp.json()["name"] == "my-custom-slug"


class TestUpdateAmplifier:
    def test_success(self, client, _use_tmp_hardware_dir):
        _seed_amp(_use_tmp_hardware_dir)
        updated = {**VALID_AMP, "power_per_channel_watts": 600}
        resp = client.put("/api/v1/hardware/amplifiers/test-amp", json=updated)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_not_found(self, client):
        resp = client.put("/api/v1/hardware/amplifiers/nope", json=VALID_AMP)
        assert resp.status_code == 404

    def test_invalid_data(self, client, _use_tmp_hardware_dir):
        _seed_amp(_use_tmp_hardware_dir)
        bad = {**VALID_AMP, "channels": -1}
        resp = client.put("/api/v1/hardware/amplifiers/test-amp", json=bad)
        assert resp.status_code == 422

    def test_path_traversal_name(self, client):
        resp = client.put("/api/v1/hardware/amplifiers/../../etc/passwd", json=VALID_AMP)
        assert resp.status_code in (400, 404, 422)


class TestDeleteAmplifier:
    def test_success(self, client, _use_tmp_hardware_dir):
        _seed_amp(_use_tmp_hardware_dir)
        resp = client.delete("/api/v1/hardware/amplifiers/test-amp")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Verify actually deleted.
        resp2 = client.get("/api/v1/hardware/amplifiers/test-amp")
        assert resp2.status_code == 404

    def test_not_found(self, client):
        resp = client.delete("/api/v1/hardware/amplifiers/nope")
        assert resp.status_code == 404

    def test_path_traversal(self, client):
        resp = client.delete("/api/v1/hardware/amplifiers/../../../etc/passwd")
        assert resp.status_code in (400, 404, 422)


# ===========================================================================
# DAC CRUD
# ===========================================================================

class TestListDacs:
    def test_empty(self, client):
        resp = client.get("/api/v1/hardware/dacs")
        assert resp.status_code == 200
        assert resp.json()["dacs"] == []

    def test_with_entries(self, client, _use_tmp_hardware_dir):
        _seed_dac(_use_tmp_hardware_dir, "dac-a", {**VALID_DAC, "name": "DAC A"})
        _seed_dac(_use_tmp_hardware_dir, "dac-b", {**VALID_DAC, "name": "DAC B"})
        resp = client.get("/api/v1/hardware/dacs")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()["dacs"]]
        assert "dac-a" in names
        assert "dac-b" in names


class TestGetDac:
    def test_found(self, client, _use_tmp_hardware_dir):
        _seed_dac(_use_tmp_hardware_dir)
        resp = client.get("/api/v1/hardware/dacs/test-dac")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test DAC"

    def test_not_found(self, client):
        resp = client.get("/api/v1/hardware/dacs/nonexistent")
        assert resp.status_code == 404


class TestCreateDac:
    def test_success(self, client):
        resp = client.post("/api/v1/hardware/dacs", json=VALID_DAC)
        assert resp.status_code == 201
        assert resp.json()["ok"] is True
        assert resp.json()["name"] == "test-dac"

    def test_duplicate(self, client, _use_tmp_hardware_dir):
        _seed_dac(_use_tmp_hardware_dir)
        resp = client.post("/api/v1/hardware/dacs", json=VALID_DAC)
        assert resp.status_code == 409

    def test_missing_fields(self, client):
        resp = client.post("/api/v1/hardware/dacs", json={"name": "Bad"})
        assert resp.status_code == 422

    def test_invalid_type(self, client):
        body = {**VALID_DAC, "type": "quantum"}
        resp = client.post("/api/v1/hardware/dacs", json=body)
        assert resp.status_code == 422

    def test_negative_output(self, client):
        body = {**VALID_DAC, "output_0dbfs_vrms": -1.0}
        resp = client.post("/api/v1/hardware/dacs", json=body)
        assert resp.status_code == 422


class TestUpdateDac:
    def test_success(self, client, _use_tmp_hardware_dir):
        _seed_dac(_use_tmp_hardware_dir)
        updated = {**VALID_DAC, "channels": 16}
        resp = client.put("/api/v1/hardware/dacs/test-dac", json=updated)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_not_found(self, client):
        resp = client.put("/api/v1/hardware/dacs/nope", json=VALID_DAC)
        assert resp.status_code == 404


class TestDeleteDac:
    def test_success(self, client, _use_tmp_hardware_dir):
        _seed_dac(_use_tmp_hardware_dir)
        resp = client.delete("/api/v1/hardware/dacs/test-dac")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        resp2 = client.get("/api/v1/hardware/dacs/test-dac")
        assert resp2.status_code == 404

    def test_not_found(self, client):
        resp = client.delete("/api/v1/hardware/dacs/nope")
        assert resp.status_code == 404


# ===========================================================================
# Validation edge cases
# ===========================================================================

class TestValidation:
    def test_amp_empty_name(self, client):
        body = {**VALID_AMP, "name": "  "}
        resp = client.post("/api/v1/hardware/amplifiers", json=body)
        assert resp.status_code == 422

    def test_amp_zero_channels(self, client):
        body = {**VALID_AMP, "channels": 0}
        resp = client.post("/api/v1/hardware/amplifiers", json=body)
        assert resp.status_code == 422

    def test_amp_string_channels(self, client):
        body = {**VALID_AMP, "channels": "four"}
        resp = client.post("/api/v1/hardware/amplifiers", json=body)
        assert resp.status_code == 422

    def test_amp_zero_voltage_gain(self, client):
        body = {**VALID_AMP, "voltage_gain": 0}
        resp = client.post("/api/v1/hardware/amplifiers", json=body)
        assert resp.status_code == 422

    def test_dac_empty_name(self, client):
        body = {**VALID_DAC, "name": ""}
        resp = client.post("/api/v1/hardware/dacs", json=body)
        assert resp.status_code == 422

    def test_dac_string_output(self, client):
        body = {**VALID_DAC, "output_0dbfs_vrms": "high"}
        resp = client.post("/api/v1/hardware/dacs", json=body)
        assert resp.status_code == 422

    def test_safe_name_rejects_dots_slash(self, client):
        resp = client.get("/api/v1/hardware/amplifiers/../secret")
        assert resp.status_code in (400, 404, 422)

    def test_safe_name_rejects_leading_dot(self, client):
        resp = client.get("/api/v1/hardware/amplifiers/.hidden")
        assert resp.status_code in (400, 404, 422)
