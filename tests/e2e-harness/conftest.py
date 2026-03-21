"""E2E harness pytest fixtures (EH-6, D-040 adapted).

Session-scoped fixture that orchestrates the full E2E test stack:
1. Generate dirac IR WAV files for the E2E convolver (passthrough)
2. Export room IR WAV files for the room simulator (EH-1)
3. Generate the E2E convolver config from template
4. Start PipeWire, PW convolver, GraphManager, room simulator, signal gen
5. Wire the PipeWire audio graph (EH-5)
6. Yield harness object for tests
7. Tear down in reverse order

D-040 adaptation: CamillaDSP replaced by PW filter-chain convolver +
GraphManager.  The convolver uses dirac IRs (passthrough) so the room
simulator is the ONLY acoustic mock in the test graph.

Tests using the harness must be marked with ``@pytest.mark.pw_integration``.
The fixture auto-skips when PipeWire is not available.
"""

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

# -- Marker registration ------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "pw_integration: requires PipeWire and PW filter-chain "
        "(auto-skipped if unavailable)",
    )


# -- Auto-skip when PipeWire unavailable --------------------------------------

def pytest_collection_modifyitems(config, items):
    if sys.platform != "linux":
        reason = "PipeWire E2E tests require Linux"
    elif shutil.which("pipewire") is None:
        reason = "PipeWire not found on PATH"
    elif shutil.which("pw-filter-chain") is None:
        reason = "pw-filter-chain not found on PATH"
    else:
        return  # all prerequisites met
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "pw_integration" in item.keywords:
            item.add_marker(skip)


# -- Harness data object -------------------------------------------------------

@dataclass
class E2EHarness:
    """Data object yielded by the ``e2e_harness`` fixture."""

    process_manager: object
    """ProcessManager instance."""

    ir_dir: Path
    """Directory containing exported room IR WAVs (EH-1)."""

    dirac_dir: Path
    """Directory containing dirac IR WAVs for the E2E convolver."""

    room_config: Path
    """Path to the room config YAML used for IR generation."""

    gm_host: str
    """GraphManager RPC host."""

    gm_port: int
    """GraphManager RPC port."""

    siggen_rpc: tuple
    """Signal generator RPC address as ``(host, port)`` tuple."""


# -- Paths ---------------------------------------------------------------------

_HARNESS_DIR = Path(__file__).parent
_PROJECT_ROOT = _HARNESS_DIR.parent.parent
_ROOM_CONFIG = _PROJECT_ROOT / "src" / "room-correction" / "mock" / "room_config.yml"
_CONVOLVER_TEMPLATE = _HARNESS_DIR / "e2e-convolver.conf.template"
_ROOM_SIM_SCRIPT = str(_HARNESS_DIR / "start-room-sim.sh")
_SIGGEN_CARGO_DEBUG = (
    _PROJECT_ROOT / "tools" / "signal-gen" / "target" / "debug" / "pi4audio-signal-gen"
)
_GRAPHMGR_CARGO_DEBUG = (
    _PROJECT_ROOT / "src" / "graph-manager" / "target" / "debug" / "pi4audio-graph-manager"
)

SAMPLE_RATE = 48000
NUM_CONVOLVER_CHANNELS = 4


def _find_siggen():
    """Locate the signal generator binary, or return None."""
    path = shutil.which("pi4audio-signal-gen")
    if path:
        return path
    if _SIGGEN_CARGO_DEBUG.is_file():
        return str(_SIGGEN_CARGO_DEBUG)
    return None


def _find_graphmgr():
    """Locate the GraphManager binary, or return None."""
    path = shutil.which("pi4audio-graph-manager")
    if path:
        return path
    if _GRAPHMGR_CARGO_DEBUG.is_file():
        return str(_GRAPHMGR_CARGO_DEBUG)
    return None


def _generate_dirac_irs(output_dir, num_channels=NUM_CONVOLVER_CHANNELS,
                        sr=SAMPLE_RATE, length=1024):
    """Generate dirac impulse WAV files for the E2E convolver.

    Each file is a single-sample impulse at sample 0 (value 1.0),
    rest zeros.  This makes the convolver a passthrough, isolating
    the room simulator as the only acoustic mock.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for ch in range(num_channels):
        ir = np.zeros(length, dtype=np.float32)
        ir[0] = 1.0  # dirac impulse
        wav_path = output_dir / f"dirac_ch{ch}.wav"
        sf.write(str(wav_path), ir, sr, subtype="FLOAT")
        paths.append(wav_path)

    return paths


def _generate_convolver_config(template_path, dirac_dir, output_path):
    """Substitute @IR_DIR@ in the convolver template to produce a config."""
    template = template_path.read_text()
    config = template.replace("@IR_DIR@", str(dirac_dir))
    output_path.write_text(config)
    return output_path


# -- Session-scoped fixture ----------------------------------------------------

@pytest.fixture(scope="session")
def e2e_harness(tmp_path_factory):
    """Start the full E2E stack and yield an ``E2EHarness`` object.

    The fixture generates dirac IRs, exports room IRs, generates the
    convolver config, starts all processes, wires the PipeWire graph,
    yields, and tears everything down on exit.

    Tests that use this fixture must be marked ``@pytest.mark.pw_integration``.
    """
    # Skip checks (belt-and-suspenders with collection hook above)
    if sys.platform != "linux":
        pytest.skip("PipeWire E2E harness requires Linux")
    if shutil.which("pipewire") is None:
        pytest.skip("PipeWire not available")
    if shutil.which("pw-filter-chain") is None:
        pytest.skip("pw-filter-chain not available")

    # Lazy imports so macOS collection doesn't fail on missing deps
    sys.path.insert(0, str(_HARNESS_DIR))
    sys.path.insert(0, str(_PROJECT_ROOT / "src" / "room-correction"))
    from mock.export_room_irs import export_room_irs
    from process_manager import ProcessManager, GRAPHMGR_E2E_PORT
    from pw_wiring import wire_e2e_graph, teardown_wiring

    # 1. Generate dirac IRs for the E2E convolver (passthrough)
    dirac_dir = Path(tmp_path_factory.mktemp("e2e-dirac"))
    _generate_dirac_irs(dirac_dir)

    # 2. Export room IR WAVs to a temp directory
    ir_dir = Path(tmp_path_factory.mktemp("e2e-irs"))
    if _ROOM_CONFIG.is_file():
        export_room_irs(ir_dir, _ROOM_CONFIG)
    else:
        pytest.skip(f"Room config not found: {_ROOM_CONFIG}")

    # 3. Generate convolver config from template
    convolver_config = Path(tmp_path_factory.mktemp("e2e-conf")) / "e2e-convolver.conf"
    _generate_convolver_config(_CONVOLVER_TEMPLATE, dirac_dir, convolver_config)

    # 4. Start processes
    siggen_port = 9877
    siggen_bin = _find_siggen()
    graphmgr_bin = _find_graphmgr()

    pm = ProcessManager(
        convolver_config=str(convolver_config),
        graphmgr_bin=graphmgr_bin,
        graphmgr_port=GRAPHMGR_E2E_PORT,
        room_sim_script=_ROOM_SIM_SCRIPT,
        room_sim_ir_dir=str(ir_dir),
        siggen_bin=siggen_bin,
        siggen_port=siggen_port,
    )
    pm.start_all()

    try:
        # 5. Wire PipeWire graph
        wire_e2e_graph()

        # 6. Yield harness to tests
        yield E2EHarness(
            process_manager=pm,
            ir_dir=ir_dir,
            dirac_dir=dirac_dir,
            room_config=_ROOM_CONFIG,
            gm_host="127.0.0.1",
            gm_port=GRAPHMGR_E2E_PORT,
            siggen_rpc=("127.0.0.1", siggen_port),
        )
    finally:
        # 7. Teardown: wiring first, then processes (reverse order)
        try:
            teardown_wiring()
        except Exception:
            pass
        pm.stop_all()
