"""Tier 1 signal generator integration tests (EH-7, D-040 adapted).

Tests the RT signal generator through the real PipeWire + PW filter-chain
convolver + room-simulator graph.  All tests require Linux with PipeWire
and are auto-skipped on macOS.

D-040 adaptation: CamillaDSP replaced by PW filter-chain convolver.
The convolver uses dirac IRs (passthrough) so only the room simulator
provides acoustic simulation.

Uses the ``e2e_harness`` session fixture from conftest.py (EH-6) which
starts all processes and wires the audio graph before the first test.

Tests
-----
1. test_sine_through_convolver -- play 1kHz sine, verify capture level
2. test_sweep_playrec_deconvolve -- sweep + deconvolve -> verify IR peak
3. test_level_above_cap_rejected -- request > -20 dBFS -> expect error
4. test_emergency_stop -- play continuous, stop, verify silence
"""

import sys
import os

import numpy as np
import pytest

# Add module paths for signal_gen_client (SG-9) and room-correction
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src", "measurement"))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src", "room-correction"))

from signal_gen_client import SignalGenClient, SignalGenError

pytestmark = pytest.mark.pw_integration

SAMPLE_RATE = 48000


@pytest.fixture
def siggen(e2e_harness):
    """Connect a SignalGenClient to the E2E signal generator."""
    host, port = e2e_harness.siggen_rpc
    client = SignalGenClient(host=host, port=port)
    client.connect()
    yield client
    # Ensure playback is stopped after each test
    try:
        client.stop()
    except Exception:
        pass
    client.close()


# -- Test 1: Sine through PW convolver ----------------------------------------

def test_sine_through_convolver(siggen):
    """Play a 1kHz sine on channel 0 and verify the capture picks up signal.

    The signal path is:
      signal-gen -> PW convolver (dirac passthrough) -> room-sim -> capture.
    A 1kHz sine at -20 dBFS passes through the convolver unmodified (dirac
    IR = unity gain), then the room-sim convolves with the room IR
    (peak-normalized to 1.0).  Capture level should be roughly -20 dBFS
    or above.  We check that capture peak is above -60 dBFS (well above
    the noise floor) to confirm signal is flowing.
    """
    siggen.play(
        signal="sine",
        channels=[1],
        level_dbfs=-20.0,
        freq=1000.0,
    )

    # Let the signal propagate through the graph
    import time
    time.sleep(0.5)

    result = siggen.capture_level()
    peak_dbfs = result.get("peak_dbfs", -200.0)

    siggen.stop()

    assert peak_dbfs > -60.0, (
        f"Capture peak {peak_dbfs:.1f} dBFS is below -60 dBFS -- "
        f"signal not reaching the capture through convolver + room-sim"
    )


# -- Test 2: Sweep playrec + deconvolve --------------------------------------

def test_sweep_playrec_deconvolve(siggen, e2e_harness):
    """Play a sweep through the full graph and deconvolve to recover the IR.

    The deconvolved IR should have a clear direct-path peak (peak-to-RMS
    ratio > 3.0), confirming that the PipeWire graph is correctly wired and
    the room simulator convolver is functioning.
    """
    from room_correction import sweep, deconvolution

    # Generate a 2-second log sweep
    test_sweep = sweep.generate_log_sweep(duration=2.0, sr=SAMPLE_RATE)

    # Build 4-channel output buffer (active on ch0 = main_left)
    n_channels = 4
    output_buffer = np.zeros((len(test_sweep), n_channels), dtype=np.float32)
    output_buffer[:, 0] = test_sweep.astype(np.float32)

    # Play and record through the E2E graph
    recording = siggen.playrec(output_buffer, samplerate=SAMPLE_RATE)
    siggen.wait()

    rec_mono = recording[:, 0].astype(np.float64)

    # Deconvolve to recover the room IR
    ir = deconvolution.deconvolve(
        rec_mono, test_sweep,
        regularization=1e-3,
        sr=SAMPLE_RATE,
        ir_duration_s=0.5,
    )

    # The IR should have a clear direct-path peak
    peak = np.max(np.abs(ir))
    rms = np.sqrt(np.mean(ir ** 2))
    peak_to_rms = peak / max(rms, 1e-10)

    assert peak_to_rms > 3.0, (
        f"IR peak-to-RMS ratio {peak_to_rms:.1f} too low -- "
        f"expected > 3.0 for a room IR with clear direct path"
    )

    # Verify the IR is not all zeros
    assert peak > 1e-6, f"IR peak {peak:.2e} is effectively zero"


# -- Test 3: Level above cap rejected ----------------------------------------

def test_level_above_cap_rejected(siggen):
    """Request a level above the safety cap (-20 dBFS) and verify rejection.

    Per AD-D037-3, the signal generator must reject level requests that
    exceed --max-level-dbfs (default -20.0).  The rejection must be an
    explicit error, not a silent clamp.
    """
    with pytest.raises(SignalGenError, match="exceeds cap"):
        siggen.play(
            signal="sine",
            channels=[1],
            level_dbfs=-10.0,  # above -20.0 cap
            freq=1000.0,
        )


# -- Test 4: Emergency stop --------------------------------------------------

def test_emergency_stop(siggen):
    """Play a continuous signal, stop it, and verify capture goes silent.

    The stop command triggers a 20ms cosine fade-out (SG-2 SafetyLimits).
    After the fade completes, the capture level should drop to the noise
    floor (below -60 dBFS).
    """
    import time

    # Start continuous playback
    siggen.play(
        signal="sine",
        channels=[1],
        level_dbfs=-20.0,
        freq=1000.0,
    )
    time.sleep(0.3)

    # Verify signal is flowing before stop
    pre_stop = siggen.capture_level()
    pre_peak = pre_stop.get("peak_dbfs", -200.0)
    assert pre_peak > -60.0, (
        f"Signal not flowing before stop: peak {pre_peak:.1f} dBFS"
    )

    # Emergency stop
    siggen.stop()

    # Wait for fade-out (20ms) + propagation
    time.sleep(0.2)

    # Verify silence
    post_stop = siggen.capture_level()
    post_peak = post_stop.get("peak_dbfs", -200.0)

    assert post_peak < -60.0, (
        f"Signal still present after stop: peak {post_peak:.1f} dBFS -- "
        f"expected silence (< -60 dBFS)"
    )
