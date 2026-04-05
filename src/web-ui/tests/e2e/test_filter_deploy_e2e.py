"""E2E tests for US-090: FIR filter generation, deployment, and rollback.

Verifies the complete filter pipeline against the real local-demo stack:
generate crossover FIR filters, deploy to coefficients directory, verify
convolver loaded them, and roll back to a previous version.

The local-demo stack provides:
    - PI4AUDIO_COEFFS_DIR = /tmp/pi4audio-demo/coeffs
    - PI4AUDIO_FILTER_OUTPUT_DIR = /tmp/pi4audio-demo/filters
    - PI4AUDIO_PW_CONF_DIR = /tmp/pw-test-xdg-config/pipewire/pipewire.conf.d
    - Speaker profiles copied from configs/speakers/profiles/

Prerequisites:
    - ``nix run .#local-demo`` running
    - No mocks — all filter generation, D-009 verification, and deployment
      happen against real files and the real PipeWire convolver

Usage:
    nix run .#test-e2e
"""

import os
import subprocess
import time

import pytest


pytestmark = [pytest.mark.e2e, pytest.mark.slow]

# Profile that exists in local-demo seed data and has a simple topology.
PROFILE = "2way-80hz-sealed"

# Expected channels for a 2-way profile.
EXPECTED_CHANNELS = {"sat_left", "sat_right", "sub1", "sub2"}

# Convolver node name in PipeWire.
CONVOLVER_NODE = "pi4audio-convolver"


def _find_node_id(node_name: str) -> str | None:
    """Find PipeWire node ID by name via pw-cli."""
    try:
        result = subprocess.run(
            ["pw-cli", "list-objects", "Node"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    current_id = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("id ") and "type PipeWire:Interface:Node" in stripped:
            parts = stripped.split(",", 1)
            current_id = parts[0].split()[1] if len(parts[0].split()) >= 2 else None
        elif current_id and f'node.name = "{node_name}"' in stripped:
            return current_id
    return None


class TestFilterGenerate:
    """POST /api/v1/filters/generate with a real speaker profile."""

    def test_generate_returns_channels_and_verification(self, api_post):
        """Generate crossover filters for a 2-way profile."""
        status, body = api_post(
            "/api/v1/filters/generate",
            {"profile": PROFILE},
            timeout=60.0,
        )
        assert status == 200, (
            f"Filter generation failed: {status} {body}"
        )
        assert body.get("profile") == PROFILE
        assert body.get("all_pass") is True, (
            f"Verification failed: {body.get('verification')}"
        )

        channels = body.get("channels", {})
        assert set(channels.keys()) >= EXPECTED_CHANNELS, (
            f"Missing channels. Got {set(channels.keys())}, "
            f"expected at least {EXPECTED_CHANNELS}"
        )

        # Verify each channel has a real file path
        for ch, path in channels.items():
            assert path.endswith(".wav"), f"Channel {ch} path not a WAV: {path}"

        # Verification results should be present
        verification = body.get("verification", [])
        assert len(verification) >= len(EXPECTED_CHANNELS), (
            f"Expected >= {len(EXPECTED_CHANNELS)} verification results, "
            f"got {len(verification)}"
        )

        # PW config should be generated
        assert "pw_conf_path" in body, "Missing pw_conf_path in response"

    def test_generate_with_custom_taps(self, api_post):
        """Generate with 8192 taps (faster, still valid)."""
        status, body = api_post(
            "/api/v1/filters/generate",
            {"profile": PROFILE, "n_taps": 8192},
            timeout=60.0,
        )
        assert status == 200, f"Generation failed: {status} {body}"
        assert body.get("n_taps") == 8192
        assert body.get("all_pass") is True


class TestFilterDeployAndVerify:
    """Generate + deploy filters, verify convolver state."""

    def test_deploy_and_verify_active(self, api_post, api_get):
        """Generate -> deploy -> verify active filters match deployed version."""
        # Step 1: Generate
        gen_status, gen_body = api_post(
            "/api/v1/filters/generate",
            {"profile": PROFILE, "n_taps": 8192},
            timeout=60.0,
        )
        assert gen_status == 200 and gen_body.get("all_pass"), (
            f"Generation failed: {gen_status} {gen_body}"
        )
        output_dir = gen_body["output_dir"]

        # Step 2: Deploy
        dep_status, dep_body = api_post(
            "/api/v1/filters/deploy",
            {"output_dir": output_dir},
            timeout=30.0,
        )
        assert dep_status == 200, (
            f"Deploy failed: {dep_status} {dep_body}"
        )
        assert dep_body.get("deployed") is True, (
            f"Deploy not confirmed: {dep_body}"
        )
        assert dep_body.get("reload_required") is True

        # Step 3: Verify active filters via API
        act_status, act_body = api_get("/api/v1/filters/active")
        assert act_status == 200
        active = act_body.get("active", {})
        # At least some channels should have active filters after deploy
        assert len(active) > 0, (
            f"No active filters after deploy: {act_body}"
        )

    @pytest.mark.needs_pw
    def test_convolver_survives_deploy(self, api_post):
        """Convolver node still exists after deploy (no crash)."""
        node_id_before = _find_node_id(CONVOLVER_NODE)
        assert node_id_before is not None, (
            f"Convolver node '{CONVOLVER_NODE}' not found before deploy"
        )

        # Generate + deploy
        gen_status, gen_body = api_post(
            "/api/v1/filters/generate",
            {"profile": PROFILE, "n_taps": 8192},
            timeout=60.0,
        )
        assert gen_status == 200 and gen_body.get("all_pass")

        dep_status, dep_body = api_post(
            "/api/v1/filters/deploy",
            {"output_dir": gen_body["output_dir"]},
            timeout=30.0,
        )
        assert dep_status == 200 and dep_body.get("deployed")

        # Convolver should still be alive
        node_id_after = _find_node_id(CONVOLVER_NODE)
        assert node_id_after is not None, (
            "Convolver node disappeared after deploy"
        )


class TestDeployD009SafetyInterlock:
    """D-009 safety interlock prevents deploying unsafe filters."""

    def test_deploy_rejects_nonexistent_dir(self, api_post):
        """Deploy with a non-existent output_dir returns 404."""
        status, body = api_post(
            "/api/v1/filters/deploy",
            {"output_dir": "/tmp/pi4audio-demo/filters/nonexistent-dir"},
            timeout=10.0,
        )
        assert status == 404, (
            f"Expected 404 for nonexistent dir, got {status}: {body}"
        )

    def test_deploy_rejects_path_traversal(self, api_post):
        """S-001: Deploy rejects output_dir outside allowed base."""
        status, body = api_post(
            "/api/v1/filters/deploy",
            {"output_dir": "/etc/passwd"},
            timeout=10.0,
        )
        assert status == 400, (
            f"Expected 400 for path traversal, got {status}: {body}"
        )
        assert body.get("error") == "invalid_output_dir"


class TestDeployEmptyDir:
    """Deploy with an empty output directory is rejected."""

    def test_deploy_empty_dir_rejected(self, api_post):
        """Deploy pointing at a dir with no combined_*.wav files -> 422."""
        # Create an empty subdir under the allowed filter output base
        output_base = os.environ.get(
            "PI4AUDIO_FILTER_OUTPUT_DIR", "/tmp/pi4audio-demo/filters"
        )
        empty_dir = os.path.join(output_base, "empty-test-dir")
        os.makedirs(empty_dir, exist_ok=True)

        try:
            status, body = api_post(
                "/api/v1/filters/deploy",
                {"output_dir": empty_dir},
                timeout=10.0,
            )
            assert status == 422, (
                f"Expected 422 for empty dir, got {status}: {body}"
            )
            assert body.get("deployed") is False
            # _verify_all_wavs returns (False, []) for no WAVs,
            # which triggers the d009_failed path in _run_deploy
            assert body.get("reason") in ("no_filters", "d009_failed"), (
                f"Expected rejection reason, got: {body}"
            )
        finally:
            # Cleanup the empty test dir
            if os.path.isdir(empty_dir):
                os.rmdir(empty_dir)


class TestFilterVersionsAndRollback:
    """Generate v1 -> deploy -> generate v2 -> deploy -> rollback to v1."""

    def test_versions_endpoint_returns_data(self, api_get):
        """GET /api/v1/filters/versions returns channel data."""
        status, body = api_get("/api/v1/filters/versions")
        assert status == 200
        assert "channels" in body
        assert "coeffs_dir" in body

    def test_rollback_restores_previous_version(self, api_post, api_get):
        """Full rollback cycle: gen v1 -> deploy -> gen v2 -> deploy -> rollback v1."""
        # Generate v1
        _, v1 = api_post(
            "/api/v1/filters/generate",
            {"profile": PROFILE, "n_taps": 8192},
            timeout=60.0,
        )
        assert v1.get("all_pass"), f"v1 generation failed: {v1}"
        v1_dir = v1["output_dir"]

        # Deploy v1
        _, d1 = api_post(
            "/api/v1/filters/deploy",
            {"output_dir": v1_dir},
            timeout=30.0,
        )
        assert d1.get("deployed"), f"v1 deploy failed: {d1}"

        # Record v1 active state
        _, active_v1 = api_get("/api/v1/filters/active")
        v1_active = active_v1.get("active", {})

        # Get v1 timestamp from versions listing
        _, versions_after_v1 = api_get("/api/v1/filters/versions")
        v1_timestamps = set()
        for ch, entries in versions_after_v1.get("channels", {}).items():
            for entry in entries:
                if entry.get("active"):
                    v1_timestamps.add(entry["timestamp"])

        # Brief pause to ensure v2 gets a different timestamp
        time.sleep(2)

        # Generate v2
        _, v2 = api_post(
            "/api/v1/filters/generate",
            {"profile": PROFILE, "n_taps": 8192},
            timeout=60.0,
        )
        assert v2.get("all_pass"), f"v2 generation failed: {v2}"

        # Deploy v2
        _, d2 = api_post(
            "/api/v1/filters/deploy",
            {"output_dir": v2["output_dir"]},
            timeout=30.0,
        )
        assert d2.get("deployed"), f"v2 deploy failed: {d2}"

        # Verify v2 is now active (different from v1)
        _, active_v2 = api_get("/api/v1/filters/active")
        v2_active = active_v2.get("active", {})
        assert v2_active != v1_active, (
            "v2 active should differ from v1 active after deploy"
        )

        # Rollback to v1 timestamp
        if not v1_timestamps:
            pytest.skip("No v1 timestamp found in versions listing")

        v1_ts = next(iter(v1_timestamps))
        rb_status, rb_body = api_post(
            "/api/v1/filters/rollback",
            {"version_timestamp": v1_ts},
            timeout=30.0,
        )
        assert rb_status == 200, (
            f"Rollback failed: {rb_status} {rb_body}"
        )
        assert rb_body.get("rolled_back") is True, (
            f"Rollback not confirmed: {rb_body}"
        )
        assert rb_body.get("reload_required") is True

        # Verify rolled-back active filters reference v1 timestamp
        _, active_rb = api_get("/api/v1/filters/active")
        rb_active = active_rb.get("active", {})
        for ch, filename in rb_active.items():
            assert v1_ts in filename, (
                f"After rollback, channel {ch} active file '{filename}' "
                f"does not contain v1 timestamp '{v1_ts}'"
            )
