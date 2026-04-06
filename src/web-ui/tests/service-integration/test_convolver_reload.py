"""US-112 — Convolver hot-reload via Reload control port.

Integration tests that verify the patched PipeWire convolver reloads
coefficients in-place without node destruction.

Requires:
    - Running local-demo stack with patched PipeWire (US-112)
    - PipeWire convolver node loaded (pi4audio-convolver)

Test tiers:
    - test_reload_via_control_port: @needs_pw — basic reload + node ID preserved
    - test_reload_failure_preserves_old: @needs_pw — bad file → old coeffs kept
    - test_reload_timing: @needs_pw — wall-clock < 100ms
    - test_deploy_reload_uses_control_port: @needs_pw — Python API uses Reload
"""

import json
import os
import shutil
import subprocess
import time

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _get_links() -> list[dict]:
    """Get current PipeWire links via pw-dump."""
    try:
        result = subprocess.run(
            ["pw-dump"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        objects = json.loads(result.stdout)
        return [
            obj for obj in objects
            if obj.get("type") == "PipeWire:Interface:Link"
        ]
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return []


NODE_NAME = "pi4audio-convolver"
COEFFS_DIR = os.environ.get("PI4AUDIO_COEFFS_DIR", "/tmp/pi4audio-test-coeffs")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.needs_pw
class TestReloadViaControlPort:
    """Test 1: Basic reload — node ID preserved, links unchanged."""

    def test_reload_preserves_node_id(self):
        """Set Reload=1.0 and verify node ID is unchanged."""
        node_id = _find_node_id(NODE_NAME)
        assert node_id is not None, f"Convolver node '{NODE_NAME}' not found"

        result = subprocess.run(
            ["pw-cli", "s", node_id, "Props",
             '{ params = [ "Reload" 1.0 ] }'],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0, (
            f"pw-cli set Props failed: {result.stderr.strip()}"
        )

        # Brief pause for reload to complete
        time.sleep(0.2)

        # Node ID must be the same (no destroy/recreate)
        node_id_after = _find_node_id(NODE_NAME)
        assert node_id_after == node_id, (
            f"Node ID changed: {node_id} -> {node_id_after}"
        )

    def test_reload_preserves_links(self):
        """Links to/from convolver are unchanged after reload."""
        node_id = _find_node_id(NODE_NAME)
        assert node_id is not None

        links_before = _get_links()
        link_ids_before = sorted(obj.get("id") for obj in links_before)

        result = subprocess.run(
            ["pw-cli", "s", node_id, "Props",
             '{ params = [ "Reload" 1.0 ] }'],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0

        time.sleep(0.2)

        links_after = _get_links()
        link_ids_after = sorted(obj.get("id") for obj in links_after)
        assert link_ids_before == link_ids_after, (
            f"Links changed: before={link_ids_before}, after={link_ids_after}"
        )


@pytest.mark.needs_pw
@pytest.mark.destructive
class TestReloadFailurePreservesOld:
    """Test 2: Bad coefficient file — old coefficients preserved."""

    def test_missing_file_keeps_old_coefficients(self):
        """Temporarily rename a coefficient WAV, trigger reload, verify node survives."""
        node_id = _find_node_id(NODE_NAME)
        assert node_id is not None, f"Convolver node '{NODE_NAME}' not found"

        # Find a coefficient file to temporarily move
        coeffs_dir = os.environ.get("PI4AUDIO_COEFFS_DIR", COEFFS_DIR)
        wav_files = [
            f for f in os.listdir(coeffs_dir)
            if f.endswith(".wav")
        ] if os.path.isdir(coeffs_dir) else []

        if not wav_files:
            pytest.skip("No coefficient WAV files found in COEFFS_DIR")

        target = os.path.join(coeffs_dir, wav_files[0])
        backup = target + ".bak"

        try:
            shutil.move(target, backup)

            # Trigger reload — should fail gracefully, keep old coefficients
            result = subprocess.run(
                ["pw-cli", "s", node_id, "Props",
                 '{ params = [ "Reload" 1.0 ] }'],
                capture_output=True, text=True, timeout=5,
            )
            # pw-cli itself succeeds (it just sets the parameter);
            # the convolver internally logs an error and keeps old coefficients

            time.sleep(0.3)

            # Node must still exist with same ID
            node_id_after = _find_node_id(NODE_NAME)
            assert node_id_after == node_id, (
                f"Node disappeared or changed after failed reload: "
                f"{node_id} -> {node_id_after}"
            )
        finally:
            # Restore the file
            if os.path.exists(backup):
                shutil.move(backup, target)


@pytest.mark.needs_pw
class TestReloadTiming:
    """Test 3: Reload completes within 100ms wall-clock time."""

    def test_reload_under_100ms(self):
        """Measure wall-clock time of Reload trigger.

        NOTE: This measures the pw-cli IPC round-trip (set Props + return),
        not the end-to-end audio coefficient swap time.  The actual pointer
        swap inside PipeWire is near-instantaneous; we are testing that the
        control-port path completes within 100ms wall-clock including IPC.
        """
        node_id = _find_node_id(NODE_NAME)
        assert node_id is not None, f"Convolver node '{NODE_NAME}' not found"

        t0 = time.monotonic()
        result = subprocess.run(
            ["pw-cli", "s", node_id, "Props",
             '{ params = [ "Reload" 1.0 ] }'],
            capture_output=True, text=True, timeout=5,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert result.returncode == 0, (
            f"pw-cli set Props failed: {result.stderr.strip()}"
        )
        assert elapsed_ms < 100, (
            f"Reload took {elapsed_ms:.1f}ms, exceeds 100ms threshold"
        )

        # Verify node survived
        node_id_after = _find_node_id(NODE_NAME)
        assert node_id_after == node_id


@pytest.mark.needs_pw
class TestDeployReloadUsesControlPort:
    """Test 4: Python reload_convolver() uses Reload control port."""

    def test_python_reload_preserves_node_id(self):
        """Call reload_convolver() and verify node ID + links unchanged."""
        deploy_mod = pytest.importorskip(
            "room_correction.deploy",
            reason="room_correction package not on sys.path",
        )

        node_id_before = _find_node_id(NODE_NAME)
        assert node_id_before is not None, f"Convolver node '{NODE_NAME}' not found"

        links_before = _get_links()
        link_ids_before = sorted(obj.get("id") for obj in links_before)

        success = deploy_mod.reload_convolver(node_name=NODE_NAME)
        assert success, "reload_convolver() returned False"

        node_id_after = _find_node_id(NODE_NAME)
        assert node_id_after == node_id_before, (
            f"Node ID changed: {node_id_before} -> {node_id_after} — "
            f"reload_convolver() may still be using destroy-and-recreate"
        )

        links_after = _get_links()
        link_ids_after = sorted(obj.get("id") for obj in links_after)
        assert link_ids_before == link_ids_after, (
            f"Links changed after reload_convolver(): "
            f"before={link_ids_before}, after={link_ids_after}"
        )
