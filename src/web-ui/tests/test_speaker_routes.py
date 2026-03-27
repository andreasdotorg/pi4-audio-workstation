"""Tests for US-089: Speaker config CRUD API.

Phase 1 (read):
    - List identities/profiles returns all YAML files
    - Get identity/profile by name returns parsed YAML
    - 404 for unknown, path traversal rejected
    - display_name from YAML 'name' field

Phase 2 (write):
    - Create, update, delete identities and profiles
    - Schema validation rejects invalid bodies
    - Conflict detection (409 on duplicate create)
    - All writes use a temp directory (no real file mutation)
"""

from unittest.mock import patch
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from app.main import app

try:
    from app.speaker_routes import (
        _list_yamls, _read_yaml, _speakers_dir, _SAFE_NAME,
        _validate_identity, _validate_profile, _slugify,
        _write_yaml, _delete_yaml,
        _VALID_TOPOLOGIES, _VALID_ROLES, _VALID_ENCLOSURE_TYPES,
        _VALID_GM_MODES, _MAX_CHANNEL,
    )
except ImportError:
    pytest.skip("speaker_routes not available (pre-commit)", allow_module_level=True)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────

def _get_speakers_dir():
    """Return the speakers dir that the routes will resolve to."""
    d = _speakers_dir()
    assert d is not None, "configs/speakers/ directory not found"
    return d


# ── Unit tests: _SAFE_NAME regex ─────────────────────────────────

class TestSafeName:
    def test_allows_normal_names(self):
        assert _SAFE_NAME.match("wideband-selfbuilt-v1")
        assert _SAFE_NAME.match("bose-ps28-iii-sub")
        assert _SAFE_NAME.match("2way-80hz-sealed")
        assert _SAFE_NAME.match("markaudio-chn-50p-sealed-1l16")

    def test_rejects_traversal(self):
        assert _SAFE_NAME.match("../etc/passwd") is None
        assert _SAFE_NAME.match("..") is None

    def test_rejects_leading_dot(self):
        assert _SAFE_NAME.match(".hidden") is None

    def test_rejects_slashes(self):
        assert _SAFE_NAME.match("foo/bar") is None
        assert _SAFE_NAME.match("foo\\bar") is None

    def test_rejects_empty(self):
        assert _SAFE_NAME.match("") is None


# ── Unit tests: _list_yamls ──────────────────────────────────────

class TestListYamls:
    def test_identities_not_empty(self):
        items = _list_yamls("identities")
        assert len(items) >= 3, f"Expected at least 3 identities, got {len(items)}"

    def test_profiles_not_empty(self):
        items = _list_yamls("profiles")
        assert len(items) >= 2, f"Expected at least 2 profiles, got {len(items)}"

    def test_items_have_required_keys(self):
        items = _list_yamls("identities")
        for item in items:
            assert "name" in item, f"Missing 'name' key in {item}"
            assert "display_name" in item, f"Missing 'display_name' key in {item}"

    def test_nonexistent_subdir_returns_empty(self):
        items = _list_yamls("nonexistent")
        assert items == []

    def test_display_name_from_yaml(self):
        """display_name should come from the YAML 'name' field."""
        items = _list_yamls("identities")
        wideband = [i for i in items if i["name"] == "wideband-selfbuilt-v1"]
        assert len(wideband) == 1
        assert wideband[0]["display_name"] == "Wideband Self-Built v1"


# ── Unit tests: _read_yaml ───────────────────────────────────────

class TestReadYaml:
    def test_read_known_identity(self):
        data = _read_yaml("identities", "wideband-selfbuilt-v1")
        assert data is not None
        assert data["name"] == "Wideband Self-Built v1"
        assert data["type"] == "sealed"
        assert data["impedance_ohm"] == 8

    def test_read_known_profile(self):
        data = _read_yaml("profiles", "2way-80hz-sealed")
        assert data is not None
        assert data["name"] == "PA 2-Way 80Hz Sealed"
        assert data["topology"] == "2way"
        assert data["crossover"]["frequency_hz"] == 80

    def test_read_unknown_returns_none(self):
        data = _read_yaml("identities", "does-not-exist")
        assert data is None

    def test_path_traversal_returns_none(self):
        data = _read_yaml("identities", "../profiles/bose-home")
        assert data is None

    def test_empty_name_returns_none(self):
        # Empty string doesn't match _SAFE_NAME
        data = _read_yaml("identities", "")
        assert data is None

    def test_profile_speakers_section(self):
        """Profile YAML has speakers with identity references."""
        data = _read_yaml("profiles", "bose-home")
        assert data is not None
        speakers = data.get("speakers", {})
        assert "sat_left" in speakers
        assert speakers["sat_left"]["identity"] == "bose-jewel-double-cube"
        assert speakers["sat_left"]["role"] == "satellite"

    def test_identity_has_safety_fields(self):
        """Identity YAML should contain D-029 safety fields."""
        data = _read_yaml("identities", "bose-ps28-iii-sub")
        assert data is not None
        assert "mandatory_hpf_hz" in data
        assert "max_boost_db" in data
        assert data["mandatory_hpf_hz"] == 42


# ── Integration tests: HTTP endpoints ────────────────────────────

class TestListIdentitiesEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/v1/speakers/identities")
        assert resp.status_code == 200

    def test_response_has_identities_key(self, client):
        data = client.get("/api/v1/speakers/identities").json()
        assert "identities" in data

    def test_identities_list_not_empty(self, client):
        data = client.get("/api/v1/speakers/identities").json()
        assert len(data["identities"]) >= 3


class TestGetIdentityEndpoint:
    def test_known_identity(self, client):
        resp = client.get("/api/v1/speakers/identities/wideband-selfbuilt-v1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Wideband Self-Built v1"

    def test_unknown_identity_404(self, client):
        resp = client.get("/api/v1/speakers/identities/nonexistent")
        assert resp.status_code == 404

    def test_traversal_rejected(self, client):
        resp = client.get("/api/v1/speakers/identities/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code == 404


class TestListProfilesEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/v1/speakers/profiles")
        assert resp.status_code == 200

    def test_response_has_profiles_key(self, client):
        data = client.get("/api/v1/speakers/profiles").json()
        assert "profiles" in data

    def test_profiles_list_not_empty(self, client):
        data = client.get("/api/v1/speakers/profiles").json()
        assert len(data["profiles"]) >= 2


class TestGetProfileEndpoint:
    def test_known_profile(self, client):
        resp = client.get("/api/v1/speakers/profiles/2way-80hz-sealed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["topology"] == "2way"
        assert data["crossover"]["frequency_hz"] == 80

    def test_unknown_profile_404(self, client):
        resp = client.get("/api/v1/speakers/profiles/nonexistent")
        assert resp.status_code == 404

    def test_bose_home_profile(self, client):
        resp = client.get("/api/v1/speakers/profiles/bose-home")
        assert resp.status_code == 200
        data = resp.json()
        assert "speakers" in data
        assert data["speakers"]["sub2"]["polarity"] == "inverted"


# ── Unit tests: validation ───────────────────────────────────────

_VALID_IDENTITY = {
    "name": "Test Speaker",
    "type": "sealed",
    "impedance_ohm": 8,
    "sensitivity_db_spl": 90,
    "max_boost_db": 0,
    "mandatory_hpf_hz": 30,
}

_VALID_PROFILE = {
    "name": "Test Profile",
    "topology": "2way",
    "crossover": {"frequency_hz": 80, "slope_db_per_oct": 48, "type": "linkwitz-riley"},
    "speakers": {
        "sat_left": {"identity": "test-spk", "role": "satellite", "channel": 0},
        "sub1": {"identity": "test-sub", "role": "subwoofer", "channel": 2},
    },
}


class TestValidateIdentity:
    def test_valid(self):
        assert _validate_identity(_VALID_IDENTITY) is None

    def test_missing_field(self):
        body = {k: v for k, v in _VALID_IDENTITY.items() if k != "type"}
        err = _validate_identity(body)
        assert err is not None
        assert "type" in err

    def test_invalid_type(self):
        body = {**_VALID_IDENTITY, "type": "magicbox"}
        assert _validate_identity(body) is not None

    def test_non_dict(self):
        assert _validate_identity("not a dict") is not None

    def test_empty_name(self):
        body = {**_VALID_IDENTITY, "name": ""}
        assert _validate_identity(body) is not None

    def test_impedance_not_number(self):
        body = {**_VALID_IDENTITY, "impedance_ohm": "eight"}
        assert _validate_identity(body) is not None

    def test_missing_sensitivity(self):
        body = {k: v for k, v in _VALID_IDENTITY.items() if k != "sensitivity_db_spl"}
        err = _validate_identity(body)
        assert err is not None
        assert "sensitivity_db_spl" in err

    def test_sensitivity_not_number(self):
        body = {**_VALID_IDENTITY, "sensitivity_db_spl": "loud"}
        assert _validate_identity(body) is not None

    def test_sensitivity_null_rejected(self):
        body = {**_VALID_IDENTITY, "sensitivity_db_spl": None}
        assert _validate_identity(body) is not None


class TestValidateProfile:
    def test_valid(self):
        assert _validate_profile(_VALID_PROFILE) is None

    def test_missing_crossover(self):
        body = {k: v for k, v in _VALID_PROFILE.items() if k != "crossover"}
        err = _validate_profile(body)
        assert err is not None
        assert "crossover" in err

    def test_crossover_missing_field(self):
        body = {**_VALID_PROFILE, "crossover": {"frequency_hz": 80}}
        assert _validate_profile(body) is not None

    def test_empty_speakers(self):
        body = {**_VALID_PROFILE, "speakers": {}}
        assert _validate_profile(body) is not None

    def test_speaker_missing_role(self):
        bad_speakers = {"sat": {"identity": "x", "channel": 0}}
        body = {**_VALID_PROFILE, "speakers": bad_speakers}
        assert _validate_profile(body) is not None

    def test_speaker_invalid_role(self):
        bad_speakers = {"sat": {"identity": "x", "role": "woofer", "channel": 0}}
        body = {**_VALID_PROFILE, "speakers": bad_speakers}
        assert _validate_profile(body) is not None

    def test_invalid_topology(self):
        body = {**_VALID_PROFILE, "topology": "5way"}
        assert _validate_profile(body) is not None

    def test_channel_out_of_range(self):
        bad_speakers = {"sat": {"identity": "x", "role": "satellite", "channel": 8}}
        body = {**_VALID_PROFILE, "speakers": bad_speakers}
        assert _validate_profile(body) is not None

    def test_channel_negative(self):
        bad_speakers = {"sat": {"identity": "x", "role": "satellite", "channel": -1}}
        body = {**_VALID_PROFILE, "speakers": bad_speakers}
        assert _validate_profile(body) is not None


class TestSlugify:
    def test_simple(self):
        assert _slugify("Test Speaker v1") == "test-speaker-v1"

    def test_special_chars(self):
        assert _slugify("Bose (PS28-III)") == "bose-ps28-iii"

    def test_empty(self):
        assert _slugify("") == "unnamed"

    def test_leading_trailing(self):
        assert _slugify("  Hello World  ") == "hello-world"


# ── Write endpoint tests (use temp dir) ──────────────────────────

@pytest.fixture
def tmp_speakers(tmp_path, monkeypatch):
    """Create a temp speakers dir and monkeypatch _speakers_dir to use it."""
    identities = tmp_path / "identities"
    profiles = tmp_path / "profiles"
    identities.mkdir()
    profiles.mkdir()

    # Seed with one identity and one profile so update/delete tests work.
    seed_id = {**_VALID_IDENTITY, "name": "Seed Speaker"}
    (identities / "seed-speaker.yml").write_text(
        yaml.dump(seed_id, default_flow_style=False, sort_keys=False))
    seed_prof = {**_VALID_PROFILE, "name": "Seed Profile"}
    (profiles / "seed-profile.yml").write_text(
        yaml.dump(seed_prof, default_flow_style=False, sort_keys=False))

    import app.speaker_routes as mod
    monkeypatch.setattr(mod, "_speakers_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def write_client(tmp_speakers):
    """TestClient with speakers dir patched to tmp."""
    return TestClient(app)


class TestCreateIdentity:
    def test_create_success(self, write_client):
        body = {**_VALID_IDENTITY, "slug": "new-test-spk"}
        resp = write_client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 201
        assert resp.json()["name"] == "new-test-spk"

    def test_create_auto_slug(self, write_client):
        body = {**_VALID_IDENTITY, "name": "Auto Named Speaker"}
        resp = write_client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 201
        assert resp.json()["name"] == "auto-named-speaker"

    def test_create_duplicate_409(self, write_client):
        body = {**_VALID_IDENTITY, "slug": "seed-speaker"}
        resp = write_client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 409

    def test_create_invalid_body_422(self, write_client):
        body = {"name": "Missing fields"}
        resp = write_client.post("/api/v1/speakers/identities", json=body)
        assert resp.status_code == 422

    def test_created_file_readable(self, write_client, tmp_speakers):
        body = {**_VALID_IDENTITY, "slug": "readable-test"}
        write_client.post("/api/v1/speakers/identities", json=body)
        resp = write_client.get("/api/v1/speakers/identities/readable-test")
        assert resp.status_code == 200
        assert resp.json()["impedance_ohm"] == 8


class TestUpdateIdentity:
    def test_update_success(self, write_client):
        body = {**_VALID_IDENTITY, "name": "Updated Name"}
        resp = write_client.put("/api/v1/speakers/identities/seed-speaker", json=body)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_update_not_found_404(self, write_client):
        body = _VALID_IDENTITY
        resp = write_client.put("/api/v1/speakers/identities/nonexistent", json=body)
        assert resp.status_code == 404

    def test_update_invalid_body_422(self, write_client):
        resp = write_client.put(
            "/api/v1/speakers/identities/seed-speaker",
            json={"name": "No type"})
        assert resp.status_code == 422

    def test_update_persists(self, write_client):
        body = {**_VALID_IDENTITY, "name": "Persisted", "impedance_ohm": 4}
        write_client.put("/api/v1/speakers/identities/seed-speaker", json=body)
        resp = write_client.get("/api/v1/speakers/identities/seed-speaker")
        assert resp.json()["impedance_ohm"] == 4


class TestDeleteIdentity:
    def test_delete_success(self, write_client):
        resp = write_client.delete("/api/v1/speakers/identities/seed-speaker")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_not_found_404(self, write_client):
        resp = write_client.delete("/api/v1/speakers/identities/nonexistent")
        assert resp.status_code == 404

    def test_delete_removes_file(self, write_client):
        write_client.delete("/api/v1/speakers/identities/seed-speaker")
        resp = write_client.get("/api/v1/speakers/identities/seed-speaker")
        assert resp.status_code == 404


class TestCreateProfile:
    def test_create_success(self, write_client):
        body = {**_VALID_PROFILE, "slug": "new-test-prof"}
        resp = write_client.post("/api/v1/speakers/profiles", json=body)
        assert resp.status_code == 201
        assert resp.json()["name"] == "new-test-prof"

    def test_create_duplicate_409(self, write_client):
        body = {**_VALID_PROFILE, "slug": "seed-profile"}
        resp = write_client.post("/api/v1/speakers/profiles", json=body)
        assert resp.status_code == 409

    def test_create_invalid_body_422(self, write_client):
        body = {"name": "Missing fields"}
        resp = write_client.post("/api/v1/speakers/profiles", json=body)
        assert resp.status_code == 422

    def test_created_profile_readable(self, write_client):
        body = {**_VALID_PROFILE, "slug": "readable-prof"}
        write_client.post("/api/v1/speakers/profiles", json=body)
        resp = write_client.get("/api/v1/speakers/profiles/readable-prof")
        assert resp.status_code == 200
        assert resp.json()["topology"] == "2way"


class TestUpdateProfile:
    def test_update_success(self, write_client):
        body = {**_VALID_PROFILE, "name": "Updated Profile"}
        resp = write_client.put("/api/v1/speakers/profiles/seed-profile", json=body)
        assert resp.status_code == 200

    def test_update_not_found_404(self, write_client):
        resp = write_client.put(
            "/api/v1/speakers/profiles/nonexistent", json=_VALID_PROFILE)
        assert resp.status_code == 404

    def test_update_invalid_body_422(self, write_client):
        resp = write_client.put(
            "/api/v1/speakers/profiles/seed-profile",
            json={"name": "No topology"})
        assert resp.status_code == 422


class TestDeleteProfile:
    def test_delete_success(self, write_client):
        resp = write_client.delete("/api/v1/speakers/profiles/seed-profile")
        assert resp.status_code == 200

    def test_delete_not_found_404(self, write_client):
        resp = write_client.delete("/api/v1/speakers/profiles/nonexistent")
        assert resp.status_code == 404

    def test_delete_removes_file(self, write_client):
        write_client.delete("/api/v1/speakers/profiles/seed-profile")
        resp = write_client.get("/api/v1/speakers/profiles/seed-profile")
        assert resp.status_code == 404
