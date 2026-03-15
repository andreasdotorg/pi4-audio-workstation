"""E2E harness pytest fixtures (EH-6).

Session-scoped fixture that orchestrates the full E2E test stack:
1. Export room IR WAV files (EH-1)
2. Start PipeWire, CamillaDSP, room simulator, signal gen (EH-4)
3. Wire the PipeWire audio graph (EH-5)
4. Yield harness object for tests
5. Tear down in reverse order

Tests using the harness must be marked with ``@pytest.mark.pw_integration``.
The fixture auto-skips on macOS (no PipeWire).
"""

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

# -- Marker registration ------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "pw_integration: requires PipeWire (auto-skipped on macOS)",
    )


# -- Auto-skip on macOS -------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    if sys.platform != "linux":
        skip = pytest.mark.skip(reason="PipeWire E2E tests require Linux")
        for item in items:
            if "pw_integration" in item.keywords:
                item.add_marker(skip)


# -- Harness data object -------------------------------------------------------

@dataclass
class E2EHarness:
    """Data object yielded by the ``e2e_harness`` fixture."""

    process_manager: object
    """ProcessManager instance (EH-4)."""

    ir_dir: Path
    """Directory containing exported room IR WAVs (EH-1)."""

    camilladsp_host: str
    """CamillaDSP WebSocket host."""

    camilladsp_port: int
    """CamillaDSP WebSocket port."""

    siggen_host: str
    """Signal generator RPC host."""

    siggen_port: int
    """Signal generator RPC port."""


# -- Paths ---------------------------------------------------------------------

_HARNESS_DIR = Path(__file__).parent
_PROJECT_ROOT = _HARNESS_DIR.parent.parent
_ROOM_CONFIG = _PROJECT_ROOT / "scripts" / "room-correction" / "mock" / "room_config.yml"
_CDSP_CONFIG = _HARNESS_DIR / "camilladsp-e2e.yml"
_ROOM_SIM_SCRIPT = str(_HARNESS_DIR / "start-room-sim.sh")


# -- Session-scoped fixture ----------------------------------------------------

@pytest.fixture(scope="session")
def e2e_harness(tmp_path_factory):
    """Start the full E2E stack and yield an ``E2EHarness`` object.

    The fixture exports room IRs, starts all processes, wires the PipeWire
    graph, yields, and tears everything down on exit.  Tests that use this
    fixture must be marked ``@pytest.mark.pw_integration``.
    """
    # Guard: skip immediately on non-Linux (belt-and-suspenders with the
    # collection hook above — this catches direct fixture requests).
    if sys.platform != "linux":
        pytest.skip("PipeWire E2E harness requires Linux")

    # Lazy imports so macOS collection doesn't fail on missing deps
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "room-correction"))
    from mock.export_room_irs import export_room_irs
    from process_manager import ProcessManager, CAMILLADSP_E2E_PORT
    from pw_wiring import wire_e2e_graph, teardown_wiring

    # 1. Export room IR WAVs to a temp directory
    ir_dir = Path(tmp_path_factory.mktemp("e2e-irs"))
    export_room_irs(ir_dir, _ROOM_CONFIG)

    # 2. Start processes
    siggen_port = 9877
    pm = ProcessManager(
        camilladsp_bin=shutil.which("camilladsp") or "camilladsp",
        camilladsp_config=str(_CDSP_CONFIG),
        camilladsp_port=CAMILLADSP_E2E_PORT,
        room_sim_script=_ROOM_SIM_SCRIPT,
        room_sim_ir_dir=str(ir_dir),
        siggen_bin=shutil.which("pi4-audio-siggen"),
        siggen_port=siggen_port,
    )
    pm.start_all()

    try:
        # 3. Wire PipeWire graph
        wire_e2e_graph()

        # 4. Yield harness to tests
        yield E2EHarness(
            process_manager=pm,
            ir_dir=ir_dir,
            camilladsp_host="127.0.0.1",
            camilladsp_port=CAMILLADSP_E2E_PORT,
            siggen_host="127.0.0.1",
            siggen_port=siggen_port,
        )
    finally:
        # 5. Teardown: wiring first, then processes (reverse order)
        try:
            teardown_wiring()
        except Exception:
            pass
        pm.stop_all()
