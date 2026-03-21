#!/usr/bin/env python3
"""
Near-field speaker measurement using log sweep and UMIK-1.

Measures the frequency response of a single speaker driver in near-field
(1-2cm from cone) using the Farina log sweep method. The script handles
the full measurement chain:

  1. Phase 1 (calibration): plays pink noise for a fixed duration so the
     operator can verify amp levels. Reports mic levels and gives a pass/fail
     verdict. Works non-interactively (safe for non-TTY SSH).
  2. Phase 2 (measurement): plays a log sweep through the speaker, records
     the UMIK-1 response, deconvolves to get the impulse response, computes
     the frequency response, and applies the UMIK-1 calibration file.

Audio routing is managed by GraphManager (D-040: PipeWire filter-chain
architecture). The script switches GraphManager to measurement mode, which
establishes signal-gen -> convolver -> USBStreamer links and UMIK-1 capture.
Convolver gain is controlled via pw-cli (attenuation on test channel, mute
on all others). The signal generator (pi4audio-signal-gen) provides audio
I/O with an immutable -20 dBFS hard cap enforced in the RT callback.

The UMIK-1 is a separate USB device from the USBStreamer, so input uses the
UMIK-1 directly while output goes through PipeWire's filter-chain convolver.

Outputs:
  - Frequency response text file (freq_hz, level_db)
  - Impulse response WAV file
  - Measurement summary with key metrics
  - Plot (PNG) if matplotlib is available

Requirements (on the Pi):
  python3, numpy, scipy, soundfile, sounddevice, pyyaml
  pi4audio-signal-gen (running on 127.0.0.1:4001)
  pi4audio-graph-manager (running on 127.0.0.1:4002)
  Optional: matplotlib (for plots)

Usage:
  python3 measure_nearfield.py \\
    --channel 0 \\
    --speaker-name "chn50p-left" \\
    --speaker-profile bose-home-chn50p \\
    --mic-device "UMIK" \\
    --calibration /home/ela/7161942.txt \\
    --output-dir ./measurements/ \\
    --sweep-duration 5 \\
    --sweep-level -20

SAFETY MODEL (defense-in-depth, see S-010 incident 2026-03-13):
  Hard cap at -20 dBFS. The signal generator enforces this immutably in
  its RT callback (safety.rs hard_clip()). Every sample is clamped to
  0.1 linear amplitude. This cannot be changed at runtime.
  At -20 dBFS into a 450W/4ohm amp: ~4.5W. CHN-50P rated 7W: survivable.
  Self-built wideband speakers: large margin.
  With convolver gain attenuation (-20dB on test channel):
    -20 dBFS sweep -> -40 dBFS at USBStreamer -> ~0.045W (safe)
  Non-test channels are muted (gain 0.0) via pw-cli.
  HPF for excursion protection is applied digitally to the sweep signal
  (numpy Butterworth filter). NOTE: The signal-gen does NOT include a
  built-in subsonic HPF. At -20 dBFS measurement levels, power is
  negligible (~0.14W into 4 ohm for broadband noise). Tracked as D-031
  known gap.

Measurement procedure:
  1. Position UMIK-1 in near-field of the driver (1-2cm, on-axis)
  2. Ensure PipeWire, signal-gen, and GraphManager are running
  3. Run this script (it switches GraphManager to measurement mode)
  4. During Phase 1: verify that mic levels are in the target range
     (peak -30 to -10 dBFS). Adjust amp if needed and re-run.
  5. Phase 1 completes automatically after the calibration duration
  6. The sweep plays automatically; do not move the mic during the sweep
  7. Results are saved to the output directory
  8. GraphManager is restored to production routing mode

Known limitation: if the script is killed by SIGKILL or OOM, GraphManager
remains in measurement mode and convolver gains may be non-production.
Recovery: restart GraphManager or set mode manually via RPC. The PipeWire
graph remains intact -- no USBStreamer reset or transients from mode switch.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time

import numpy as np
import soundfile as sf

# Force line-buffered stdout so output appears immediately over SSH. Non-TTY
# pipes default to block buffering, which hides progress from the operator.
# Line buffering flushes on every newline (i.e., every print() call).
if not sys.stdout.line_buffering:
    sys.stdout.reconfigure(line_buffering=True)
if not sys.stderr.line_buffering:
    sys.stderr.reconfigure(line_buffering=True)

# Add the src/room-correction directory to path so room_correction
# package is importable when running this script directly on the Pi.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Add src/measurement to path for SignalGenClient and GraphManagerClient
MEASUREMENT_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "measurement")
if MEASUREMENT_DIR not in sys.path:
    sys.path.insert(0, MEASUREMENT_DIR)

from room_correction import dsp_utils
from room_correction.sweep import generate_log_sweep
from room_correction.deconvolution import deconvolve
from room_correction.recording import apply_umik1_calibration
from config_generator import load_profile_with_identities

SAMPLE_RATE = dsp_utils.SAMPLE_RATE  # 48000

# Module-level sounddevice reference. Set to a MockSoundDevice instance in
# mock mode (--mock), or left as None for real sounddevice (imported locally
# in each function that needs it).
_sd_override = None

# Pre-flight check thresholds
WEBUI_SERVICE_NAME = "pi4-audio-webui.service"

# Recording integrity thresholds
REC_MIN_PEAK_DBFS = -40.0   # Below this: mic not receiving signal
REC_MAX_PEAK_DBFS = -1.0    # Above this: likely clipping
REC_MIN_SNR_DB = 20.0        # Minimum acceptable SNR for measurement

# Phase 1 calibration thresholds (mic peak dBFS)
CAL_TARGET_MIN_PEAK_DBFS = -40.0  # Below this: signal too quiet
CAL_TARGET_MAX_PEAK_DBFS = -10.0  # Above this: too loud / risk of clipping
CAL_CLIP_WARN_PEAK_DBFS = -3.0    # Near-clipping warning threshold
CAL_DEFAULT_DURATION_S = 10.0     # Default calibration duration (seconds)
CAL_BLOCK_DURATION_S = 5.0        # Each pink noise block length

# Xrun retry limits
MAX_XRUN_RETRIES = 3

# SAFETY: SWEEP_LEVEL_HARD_CAP_DBFS = -20.0
#
# Defense-in-depth: the signal generator enforces this immutably in its RT
# callback (safety.rs hard_clip()). At -20 dBFS into a 450W/4ohm amp: ~4.5W.
# CHN-50P rated 7W: survivable. Self-built wideband: large margin.
#
# With convolver gain attenuation (-20dB on test channel):
#   -20 dBFS sweep -> -40 dBFS at USBStreamer -> ~0.045W (safe)
#
# History: Originally -6 dBFS assuming -40dB CamillaDSP attenuation
# always present. S-010 (2026-03-13) demonstrated CamillaDSP bypass
# via sysdefault ALSA device. Hard cap lowered to survive bypass.
# D-040: CamillaDSP replaced by PipeWire filter-chain + signal-gen.
# Signal-gen hard cap is immutable (cannot be changed at runtime).
SWEEP_LEVEL_HARD_CAP_DBFS = -20.0

# Measurement gain parameters (applied via pw-cli to convolver gain nodes)
# MEASUREMENT_ATTENUATION_LINEAR is the Mult value for the test channel's
# convolver gain node. 0.1 = -20 dB. At -20dB + -20dBFS cap, net level at
# USBStreamer is -40 dBFS -> ~0.045W into 4 ohm (CHN-50P rated 7W: safe).
MEASUREMENT_ATTENUATION_DB = -20.0
MEASUREMENT_ATTENUATION_LINEAR = 0.1  # 10^(-20/20) = 0.1
MEASUREMENT_MUTE_LINEAR = 0.0         # Complete mute for non-test channels

# Convolver gain node names (match PipeWire filter-chain config)
# These are the linear builtin gain nodes in the production convolver.
CONVOLVER_GAIN_NODES = {
    0: "gain_left_hp",   # AUX0 - Left main
    1: "gain_right_hp",  # AUX1 - Right main
    2: "gain_sub1_lp",   # AUX2 - Sub 1
    3: "gain_sub2_lp",   # AUX3 - Sub 2
}

# Signal generator and GraphManager defaults
SIGNAL_GEN_DEFAULT_HOST = "127.0.0.1"
SIGNAL_GEN_DEFAULT_PORT = 4001
GRAPH_MANAGER_DEFAULT_HOST = "127.0.0.1"
GRAPH_MANAGER_DEFAULT_PORT = 4002


def find_device(name_substring, kind=None):
    """
    Find a sounddevice device index by name substring.

    Parameters
    ----------
    name_substring : str
        Substring to search for in device names (case-insensitive).
    kind : str or None
        'input', 'output', or None (any).

    Returns
    -------
    int or None
        Device index, or None if not found.
    """
    sd = _sd_override
    if sd is None:
        import sounddevice as sd
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if name_substring.lower() in dev['name'].lower():
            if kind == 'input' and dev['max_input_channels'] == 0:
                continue
            if kind == 'output' and dev['max_output_channels'] == 0:
                continue
            return idx
    return None


def list_audio_devices():
    """Print all available audio devices."""
    sd = _sd_override
    if sd is None:
        import sounddevice as sd
    print("\nAvailable audio devices:")
    print(sd.query_devices())
    print()


# ---------------------------------------------------------------------------
# Pre-flight checks (AD risk items 1 & 2)
# ---------------------------------------------------------------------------

def check_webui_stopped():
    """
    Pre-flight: verify pi4-audio-webui.service is not running.

    The web UI monitoring backend participates in the PipeWire audio graph
    and has been observed causing xruns (see change-S-005). It must be
    stopped before measurement to ensure clean audio.

    Returns
    -------
    bool
        True if the service is stopped (safe to proceed).
    """
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", WEBUI_SERVICE_NAME],
            capture_output=True, text=True, timeout=5
        )
        is_active = result.stdout.strip() == "active"
        if is_active:
            print(f"  FAIL: {WEBUI_SERVICE_NAME} is running!")
            print(f"  The web UI causes xruns during measurement.")
            print(f"  Stop it with: systemctl --user stop {WEBUI_SERVICE_NAME}")
            return False
        else:
            print(f"  OK: {WEBUI_SERVICE_NAME} is not active")
            return True
    except FileNotFoundError:
        # systemctl not available (e.g., running on macOS for development)
        print(f"  SKIP: systemctl not available (not running on Pi?)")
        return True
    except subprocess.TimeoutExpired:
        print(f"  WARN: systemctl check timed out, proceeding anyway")
        return True


def get_pipewire_xrun_count():
    """
    Query PipeWire xrun counter via pw-cli.

    Parses the output of `pw-cli info all` to find xrun-related properties.
    Falls back to parsing `pw-top` output or the PipeWire log if pw-cli
    doesn't expose xrun counters directly.

    Returns
    -------
    int or None
        Xrun count, or None if not determinable.
    """
    # Method 1: pw-cli dump to find xrun counters in node properties
    try:
        result = subprocess.run(
            ["pw-cli", "info", "all"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Parse xrun counters from node info
            # PipeWire exposes xruns in node properties as "info.xruns"
            xrun_total = 0
            for line in result.stdout.split('\n'):
                line_stripped = line.strip()
                # Look for xrun-related properties
                if 'xrun' in line_stripped.lower():
                    # Try to extract a numeric value
                    parts = line_stripped.split('=')
                    if len(parts) >= 2:
                        try:
                            xrun_total += int(parts[-1].strip().strip('"'))
                        except ValueError:
                            pass
            return xrun_total
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Method 2: pw-dump JSON output (more structured)
    try:
        result = subprocess.run(
            ["pw-dump"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            xrun_total = 0
            for obj in data:
                props = obj.get('info', {}).get('props', {})
                # Driver nodes track xruns
                xruns = props.get('clock.xrun-count', 0)
                if isinstance(xruns, int):
                    xrun_total += xruns
            return xrun_total
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    return None


def check_recording_integrity(recording, pre_roll, sr=SAMPLE_RATE):
    """
    Validate recording integrity before proceeding with deconvolution.

    Checks:
    - Peak level > -40 dBFS (mic is receiving signal)
    - Peak level < -1 dBFS (no clipping)
    - DC offset < 0.01 (no stuck ADC)
    - SNR estimate (signal RMS vs noise floor from pre-roll silence)

    Parameters
    ----------
    recording : np.ndarray
        Recorded signal (pre-roll already trimmed, starts at sweep onset).
    pre_roll : np.ndarray
        The silent pre-roll portion recorded BEFORE the sweep started.
        Used for noise floor estimation.
    sr : int
        Sample rate.

    Returns
    -------
    tuple of (bool, dict)
        (passed, details) where details contains the measured values.
    """
    peak = np.max(np.abs(recording))
    peak_dbfs = 20 * np.log10(max(peak, 1e-10))
    rms = np.sqrt(np.mean(recording ** 2))
    rms_dbfs = 20 * np.log10(max(rms, 1e-10))

    # DC offset check
    dc_offset = abs(np.mean(recording))

    # Noise floor from pre-roll silence (recorded before sweep started)
    if len(pre_roll) > 0:
        noise_rms = np.sqrt(np.mean(pre_roll ** 2))
        noise_dbfs = 20 * np.log10(max(noise_rms, 1e-10))
    else:
        noise_rms = 0.0
        noise_dbfs = -200.0

    # SNR estimate: signal RMS vs noise floor RMS
    snr_db = rms_dbfs - noise_dbfs if noise_rms > 0 else float('inf')

    details = {
        'peak_dbfs': peak_dbfs,
        'rms_dbfs': rms_dbfs,
        'dc_offset': dc_offset,
        'noise_floor_dbfs': noise_dbfs,
        'snr_db': snr_db,
    }

    issues = []

    if peak_dbfs < REC_MIN_PEAK_DBFS:
        issues.append(
            f"Peak too low: {peak_dbfs:.1f} dBFS < {REC_MIN_PEAK_DBFS} dBFS "
            f"(mic not receiving signal?)"
        )

    if peak_dbfs > REC_MAX_PEAK_DBFS:
        issues.append(
            f"Peak too high: {peak_dbfs:.1f} dBFS > {REC_MAX_PEAK_DBFS} dBFS "
            f"(likely clipping)"
        )

    if dc_offset > 0.01:
        issues.append(
            f"DC offset: {dc_offset:.4f} (>0.01, possible ADC issue)"
        )

    if snr_db < REC_MIN_SNR_DB:
        issues.append(
            f"SNR too low: {snr_db:.1f} dB < {REC_MIN_SNR_DB} dB "
            f"(noisy environment or mic too far)"
        )

    passed = len(issues) == 0
    details['issues'] = issues

    return passed, details


def check_process_not_running(process_name, description):
    """
    Pre-flight: verify a process is not running.

    Parameters
    ----------
    process_name : str
        Process name to search for via pgrep.
    description : str
        Human-readable description for messages.

    Returns
    -------
    bool
        True if the process is NOT running (safe to proceed).
    """
    try:
        result = subprocess.run(
            ["pgrep", "-x", process_name],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Process found
            print(f"  FAIL: {description} ({process_name}) is running!")
            print(f"  Close it before measurement to avoid xruns and CPU contention.")
            return False
        else:
            print(f"  OK: {description} not running")
            return True
    except FileNotFoundError:
        print(f"  SKIP: pgrep not available")
        return True
    except subprocess.TimeoutExpired:
        print(f"  WARN: pgrep check timed out")
        return True


def check_signal_gen_running():
    """
    Pre-flight: verify pi4audio-signal-gen is reachable.

    Attempts a TCP connection to the signal generator's RPC port.

    Returns
    -------
    bool
        True if the signal generator is reachable.
    """
    import socket
    try:
        sock = socket.create_connection(
            (SIGNAL_GEN_DEFAULT_HOST, SIGNAL_GEN_DEFAULT_PORT), timeout=2
        )
        sock.close()
        print(f"  OK: signal-gen reachable at "
              f"{SIGNAL_GEN_DEFAULT_HOST}:{SIGNAL_GEN_DEFAULT_PORT}")
        return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        print(f"  FAIL: signal-gen not reachable at "
              f"{SIGNAL_GEN_DEFAULT_HOST}:{SIGNAL_GEN_DEFAULT_PORT}")
        print("  pi4audio-signal-gen must be running for measurement.")
        return False


def check_graph_manager_running():
    """
    Pre-flight: verify pi4audio-graph-manager is reachable.

    Attempts a TCP connection to the GraphManager's RPC port.

    Returns
    -------
    bool
        True if the GraphManager is reachable.
    """
    import socket
    try:
        sock = socket.create_connection(
            (GRAPH_MANAGER_DEFAULT_HOST, GRAPH_MANAGER_DEFAULT_PORT), timeout=2
        )
        sock.close()
        print(f"  OK: GraphManager reachable at "
              f"{GRAPH_MANAGER_DEFAULT_HOST}:{GRAPH_MANAGER_DEFAULT_PORT}")
        return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        print(f"  FAIL: GraphManager not reachable at "
              f"{GRAPH_MANAGER_DEFAULT_HOST}:{GRAPH_MANAGER_DEFAULT_PORT}")
        print("  pi4audio-graph-manager must be running for measurement.")
        return False


def check_pipewire_running():
    """
    Pre-flight: verify PipeWire is running at FIFO priority.

    Returns
    -------
    bool
        True if PipeWire is running.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-x", "pipewire"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            print("  FAIL: PipeWire is not running!")
            return False
        pid = result.stdout.strip().split('\n')[0]

        chrt_result = subprocess.run(
            ["chrt", "-p", pid],
            capture_output=True, text=True, timeout=5
        )
        if chrt_result.returncode == 0:
            print(f"  OK: PipeWire running (PID {pid}), {chrt_result.stdout.strip()}")
        else:
            print(f"  OK: PipeWire running (PID {pid})")
        return True
    except FileNotFoundError:
        print("  SKIP: pgrep not available")
        return True
    except subprocess.TimeoutExpired:
        print("  WARN: PipeWire check timed out")
        return True


def run_preflight_checks():
    """
    Run all pre-flight checks before measurement.

    Checks:
    1. Web UI service stopped (xrun source)
    2. Mixxx not running (CPU contention)
    3. Reaper not running (CPU contention)
    4. Signal generator reachable (required for audio I/O)
    5. GraphManager reachable (required for routing)
    6. PipeWire running at FIFO (required for audio graph)
    7. PipeWire xrun baseline

    Returns
    -------
    bool
        True if all checks pass.
    """
    print("\n" + "=" * 60)
    print("PRE-FLIGHT CHECKS")
    print("=" * 60)

    n_checks = 7
    all_ok = True

    print(f"\n[1/{n_checks}] Checking web UI service...")
    if not check_webui_stopped():
        all_ok = False

    print(f"\n[2/{n_checks}] Checking Mixxx...")
    if not check_process_not_running("mixxx", "Mixxx"):
        all_ok = False

    print(f"\n[3/{n_checks}] Checking Reaper...")
    if not check_process_not_running("reaper", "Reaper"):
        all_ok = False

    print(f"\n[4/{n_checks}] Checking signal generator...")
    if not check_signal_gen_running():
        all_ok = False

    print(f"\n[5/{n_checks}] Checking GraphManager...")
    if not check_graph_manager_running():
        all_ok = False

    print(f"\n[6/{n_checks}] Checking PipeWire...")
    if not check_pipewire_running():
        all_ok = False

    print(f"\n[7/{n_checks}] Reading PipeWire xrun baseline...")
    xrun_count = get_pipewire_xrun_count()
    if xrun_count is not None:
        print(f"  Baseline xrun count: {xrun_count}")
    else:
        print("  WARN: Could not read xrun counter (pw-cli/pw-dump unavailable)")
        print("  Xrun detection during measurement will be skipped")

    if all_ok:
        print("\nAll pre-flight checks PASSED")
    else:
        print("\nPre-flight checks FAILED")

    return all_ok


# ---------------------------------------------------------------------------
# PipeWire convolver gain control via pw-cli (D-040, replaces CamillaDSP)
# ---------------------------------------------------------------------------

def _find_pw_node_id(node_name):
    """
    Find a PipeWire node ID by name using pw-cli.

    Parameters
    ----------
    node_name : str
        Node name to search for (e.g., 'gain_left_hp').

    Returns
    -------
    int or None
        PipeWire node ID, or None if not found.
    """
    try:
        result = subprocess.run(
            ["pw-dump"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        for obj in data:
            props = obj.get("info", {}).get("props", {})
            if props.get("node.name") == node_name:
                return obj.get("id")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def set_convolver_gain(channel, mult_value):
    """
    Set a convolver gain node's Mult value via pw-cli.

    Parameters
    ----------
    channel : int
        0-indexed output channel.
    mult_value : float
        Linear gain multiplier (0.0 = mute, 0.1 = -20dB, 1.0 = unity).

    Returns
    -------
    bool
        True if the gain was set successfully.
    """
    node_name = CONVOLVER_GAIN_NODES.get(channel)
    if node_name is None:
        print(f"  WARN: No convolver gain node for channel {channel}")
        return False

    node_id = _find_pw_node_id(node_name)
    if node_id is None:
        print(f"  WARN: Could not find PipeWire node '{node_name}'")
        return False

    try:
        result = subprocess.run(
            ["pw-cli", "s", str(node_id), "Props",
             f'{{ params = [ "Mult" {mult_value} ] }}'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            db_value = 20 * np.log10(max(mult_value, 1e-10))
            print(f"  Set {node_name} (node {node_id}): "
                  f"Mult={mult_value} ({db_value:.1f} dB)")
            return True
        else:
            print(f"  WARN: pw-cli failed for {node_name}: {result.stderr.strip()}")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  WARN: pw-cli error for {node_name}: {e}")
        return False


def set_measurement_gains(test_channel):
    """
    Set convolver gains for measurement: attenuate test channel, mute others.

    Parameters
    ----------
    test_channel : int
        0-indexed output channel under test.

    Returns
    -------
    dict
        Original gain values for restoration, keyed by channel number.
        Empty dict if reading original values failed.
    """
    original_gains = {}
    # Read current gain values before modifying (for restoration)
    for ch, node_name in CONVOLVER_GAIN_NODES.items():
        node_id = _find_pw_node_id(node_name)
        if node_id is not None:
            # Store the node_id so we can restore later without re-lookup
            original_gains[ch] = {"node_name": node_name, "node_id": node_id}

    # Set measurement gains
    all_ok = True
    for ch in CONVOLVER_GAIN_NODES:
        if ch == test_channel:
            if not set_convolver_gain(ch, MEASUREMENT_ATTENUATION_LINEAR):
                all_ok = False
        else:
            if not set_convolver_gain(ch, MEASUREMENT_MUTE_LINEAR):
                all_ok = False

    if not all_ok:
        print("  WARN: Not all convolver gains were set successfully")
        print("  The signal-gen hard cap (-20 dBFS) still provides safety")

    return original_gains


def restore_production_gains(original_gains):
    """
    Restore convolver gains to production values.

    Since we don't know the exact production Mult values (they are set in
    the PipeWire filter-chain config and applied at startup), the safest
    approach is to note that GraphManager mode switch back to 'monitoring'
    or 'dj' will re-apply the production gain values from the filter-chain
    config. This function is a fallback that sets unity gain (Mult=1.0)
    if explicit restoration is needed.

    Parameters
    ----------
    original_gains : dict
        Original gain info from set_measurement_gains(). Currently used
        only for the node IDs.

    Returns
    -------
    bool
        True if all gains were restored.
    """
    # NOTE: The primary restoration mechanism is GraphManager mode switch
    # back to monitoring/dj mode, which re-establishes the production
    # filter-chain config with correct gain values. This function is a
    # safety net that resets to unity gain in case GM mode switch fails.
    all_ok = True
    for ch, info in original_gains.items():
        if not set_convolver_gain(ch, 1.0):
            all_ok = False

    if not all_ok:
        print("\n  ** WARNING: Could not restore all convolver gains **")
        print("  ** PA OUTPUT may have incorrect gain levels **")
        print("  ** Restart PipeWire or GraphManager to restore production state **")
        print("  ** (WARNING: PipeWire restart produces USBStreamer transients — **")
        print("  **  turn off amplifiers first!) **")

    return all_ok


def get_mandatory_hpf_hz(test_channel, speaker_profile_name,
                         profiles_dir=None, identities_dir=None):
    """
    Look up the mandatory HPF frequency from the speaker identity profile.

    Parameters
    ----------
    test_channel : int
        0-indexed output channel under test.
    speaker_profile_name : str
        Speaker profile name (e.g., 'bose-home-chn50p').
    profiles_dir : str or Path, optional
        Override profiles directory.
    identities_dir : str or Path, optional
        Override identities directory.

    Returns
    -------
    int or None
        HPF frequency in Hz, or None if not found.

    Raises
    ------
    ValueError
        If the test channel is not found in the speaker profile.
    """
    profile, identities = load_profile_with_identities(
        speaker_profile_name,
        profiles_dir=profiles_dir,
        identities_dir=identities_dir,
    )

    for spk_key, spk_cfg in profile["speakers"].items():
        if spk_cfg["channel"] == test_channel:
            id_name = spk_cfg["identity"]
            identity = identities.get(id_name, {})
            return identity.get("mandatory_hpf_hz")

    raise ValueError(
        f"Channel {test_channel} not found in speaker profile "
        f"'{speaker_profile_name}'. Available channels: "
        + ", ".join(
            f"{k}={v['channel']}" for k, v in profile["speakers"].items()
        )
    )


def apply_hpf_to_signal(signal, hpf_hz, sr=SAMPLE_RATE, order=4):
    """
    Apply a Butterworth highpass filter to a signal (excursion protection).

    This is applied digitally to the sweep/noise signal before sending it
    to the signal generator. It replaces the CamillaDSP IIR HPF that was
    previously in the measurement config.

    NOTE (D-031): The signal-gen does NOT include a built-in subsonic HPF.
    This function provides secondary protection against driver excursion at
    very low frequencies. The primary safety net is the -20 dBFS hard cap.

    Parameters
    ----------
    signal : np.ndarray
        Input signal (1D, float64).
    hpf_hz : int
        Highpass frequency in Hz.
    sr : int
        Sample rate.
    order : int
        Filter order (default 4 = 24 dB/oct Butterworth).

    Returns
    -------
    np.ndarray
        Filtered signal.
    """
    from scipy.signal import butter, sosfilt
    sos = butter(order, hpf_hz, btype='high', fs=sr, output='sos')
    return sosfilt(sos, signal)


def generate_pink_noise(duration_s, sr=SAMPLE_RATE, level_dbfs=-40.0,
                        f_low=100.0, f_high=10000.0):
    """
    Generate band-limited pink noise (1/f spectrum) at a given dBFS level.

    Frequency-domain synthesis: white noise shaped with 1/sqrt(f) amplitude,
    band-limited to [f_low, f_high] with 4th-order Butterworth rolloff to
    avoid subsonic energy that could damage speakers and ultrasonic energy
    that is inaudible.

    The calibration noise is intentionally limited to 100Hz-10kHz (not the
    full 20Hz-20kHz audio band) because:
    - Below 100Hz: subsonic energy wastes power and risks over-excursion
      on small drivers during the calibration phase
    - Above 10kHz: adds minimal perceptual loudness information for
      level-setting purposes

    Parameters
    ----------
    duration_s : float
        Duration in seconds.
    sr : int
        Sample rate.
    level_dbfs : float
        Target RMS level in dBFS (default -20.0, safe with convolver
        gain providing -20dB attenuation on the test channel).
    f_low : float
        Lower band limit in Hz (default 100.0).
    f_high : float
        Upper band limit in Hz (default 10000.0).

    Returns
    -------
    np.ndarray
        Pink noise signal, float64.
    """
    from scipy.signal import butter, sosfilt

    n_samples = int(duration_s * sr)
    white = np.random.randn(n_samples).astype(np.float64)

    # Shape white noise to pink (1/f) in frequency domain
    n_fft = dsp_utils.next_power_of_2(n_samples)
    spectrum = np.fft.rfft(white, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    # 1/sqrt(f) amplitude scaling = 1/f power scaling = pink noise
    # Avoid division by zero at DC
    freqs_safe = freqs.copy()
    freqs_safe[0] = 1.0
    pink_filter = 1.0 / np.sqrt(freqs_safe)
    spectrum *= pink_filter

    pink = np.fft.irfft(spectrum, n=n_fft)[:n_samples]

    # Band-limit with 4th-order Butterworth bandpass (smooth rolloff,
    # no ringing artifacts that a brick-wall spectral filter would cause)
    nyquist = sr / 2.0
    low = f_low / nyquist
    high = min(f_high / nyquist, 0.999)  # Clamp below Nyquist
    sos = butter(4, [low, high], btype='bandpass', output='sos')
    pink = sosfilt(sos, pink)

    # Normalize to target RMS level
    rms = np.sqrt(np.mean(pink ** 2))
    if rms > 0:
        target_rms = dsp_utils.db_to_linear(level_dbfs)
        pink *= target_rms / rms

    # Hard-clip to prevent any sample from exceeding 0 dBFS
    pink = np.clip(pink, -1.0, 1.0)

    return pink


def play_and_record(output_signal, output_channel, output_device_idx,
                    input_device_idx, sr=SAMPLE_RATE, pre_roll_s=0.5,
                    post_roll_s=0.5):
    """
    Simultaneously play a signal on a specific output channel and record
    from the UMIK-1 input.

    The recording includes pre-roll (silence before playback starts) and
    post-roll (continued recording after playback ends) to capture the
    full impulse response including room decay.

    Parameters
    ----------
    output_signal : np.ndarray
        Mono signal to play (1D, float64).
    output_channel : int
        0-indexed output channel number.
    output_device_idx : int
        Sounddevice output device index.
    input_device_idx : int
        Sounddevice input device index (UMIK-1).
    sr : int
        Sample rate.
    pre_roll_s : float
        Seconds of silence before the signal.
    post_roll_s : float
        Seconds of continued recording after the signal.

    Returns
    -------
    tuple of (np.ndarray, np.ndarray)
        (trimmed_recording, pre_roll) where:
        - trimmed_recording: aligned so index 0 = start of output signal
        - pre_roll: the silent pre-roll portion (for noise floor estimation)
    """
    sd = _sd_override
    if sd is None:
        import sounddevice as sd

    out_info = sd.query_devices(output_device_idx)
    n_out_channels = out_info['max_output_channels']

    if output_channel >= n_out_channels:
        raise ValueError(
            f"Output channel {output_channel} exceeds device capacity "
            f"({n_out_channels} channels on '{out_info['name']}')"
        )

    pre_roll_samples = int(pre_roll_s * sr)
    post_roll_samples = int(post_roll_s * sr)

    # Build multi-channel output: silence on all channels except the target
    total_out_samples = pre_roll_samples + len(output_signal) + post_roll_samples
    output_buffer = np.zeros((total_out_samples, n_out_channels), dtype=np.float32)
    output_buffer[pre_roll_samples:pre_roll_samples + len(output_signal),
                  output_channel] = output_signal.astype(np.float32)

    # Record simultaneously
    # input_mapping: channel 1 of the UMIK-1 (1-indexed for sounddevice)
    # output_mapping: all channels (we built the full multi-channel buffer)
    print(f"  Playing on channel {output_channel} of '{out_info['name']}' "
          f"({n_out_channels}ch)")

    in_info = sd.query_devices(input_device_idx)
    print(f"  Recording from '{in_info['name']}'")

    recording = sd.playrec(
        output_buffer,
        samplerate=sr,
        input_mapping=[1],  # UMIK-1 channel 1 (mono mic)
        device=(input_device_idx, output_device_idx),
        dtype='float32',
    )
    sd.wait()

    # Extract mono recording and convert to float64
    rec = recording[:, 0].astype(np.float64)

    # Split into pre-roll (silence, for noise floor) and signal-aligned recording
    pre_roll = rec[:pre_roll_samples]
    trimmed = rec[pre_roll_samples:]

    return trimmed, pre_roll


def compute_frequency_response(ir, sr=SAMPLE_RATE, fade_out_ms=5.0):
    """
    Compute the frequency response (magnitude in dB) from an impulse response.

    Uses a half-Hann fade-out window: the direct sound onset (start of the
    IR) is preserved at full amplitude, and only the tail is faded out to
    reduce spectral leakage from truncation. This is correct for near-field
    measurements where the IR is dominated by the direct sound.

    A full Hann window would attenuate the direct sound at the start of the
    IR, biasing the frequency response measurement.

    Parameters
    ----------
    ir : np.ndarray
        Impulse response.
    sr : int
        Sample rate.
    fade_out_ms : float
        Duration of the half-Hann fade-out at the end of the IR, in ms.

    Returns
    -------
    freqs : np.ndarray
        Frequency array in Hz.
    magnitude_db : np.ndarray
        Magnitude in dB.
    """
    n_fft = dsp_utils.next_power_of_2(len(ir))

    # Half-Hann fade-out: preserve the onset, only taper the tail
    fade_samples = int(fade_out_ms / 1000.0 * sr)
    fade_samples = min(fade_samples, len(ir))
    window = np.ones(len(ir))
    if fade_samples > 0:
        # Half-Hann: cos^2 taper from 1 to 0
        fade = np.hanning(2 * fade_samples)[fade_samples:]
        window[-fade_samples:] = fade

    windowed_ir = ir * window

    spectrum = np.fft.rfft(windowed_ir, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    magnitude = np.abs(spectrum)
    magnitude_db = dsp_utils.linear_to_db(magnitude)

    return freqs, magnitude_db


def find_f3(freqs, magnitude_db):
    """
    Find the -3dB point (F3) relative to the passband average.

    Looks for the lowest frequency where the response is within 3dB of
    the average level in the 200Hz-2kHz band.

    Parameters
    ----------
    freqs : np.ndarray
        Frequency array.
    magnitude_db : np.ndarray
        Magnitude in dB.

    Returns
    -------
    float or None
        F3 frequency in Hz, or None if not determinable.
    """
    # Reference level: average in the 200Hz-2kHz band
    band = (freqs >= 200) & (freqs <= 2000)
    if not np.any(band):
        return None
    ref_level = np.mean(magnitude_db[band])

    # Find lowest frequency where level >= ref_level - 3dB
    threshold = ref_level - 3.0
    audio_band = (freqs >= 20) & (freqs <= 20000)
    indices = np.where(audio_band & (magnitude_db >= threshold))[0]
    if len(indices) == 0:
        return None

    return float(freqs[indices[0]])


def find_peak_frequency(freqs, magnitude_db):
    """
    Find the frequency of maximum response in the audio band.

    Parameters
    ----------
    freqs : np.ndarray
        Frequency array.
    magnitude_db : np.ndarray
        Magnitude in dB.

    Returns
    -------
    tuple of (float, float)
        (peak_frequency_hz, peak_level_db)
    """
    audio_band = (freqs >= 20) & (freqs <= 20000)
    band_freqs = freqs[audio_band]
    band_db = magnitude_db[audio_band]
    peak_idx = np.argmax(band_db)
    return float(band_freqs[peak_idx]), float(band_db[peak_idx])


def save_frequency_response(freqs, magnitude_db, output_path):
    """
    Save frequency response as a tab-separated text file.

    Format: freq_hz<tab>level_db, one line per frequency bin.
    Only includes bins in the 20Hz-20kHz audio band.

    Parameters
    ----------
    freqs : np.ndarray
        Frequency array.
    magnitude_db : np.ndarray
        Magnitude in dB.
    output_path : str
        Output file path.
    """
    audio_band = (freqs >= 20) & (freqs <= 20000)
    with open(output_path, 'w') as f:
        f.write("# Near-field frequency response measurement\n")
        f.write(f"# Date: {datetime.datetime.now().isoformat()}\n")
        f.write("# freq_hz\tlevel_db\n")
        for freq, db in zip(freqs[audio_band], magnitude_db[audio_band]):
            f.write(f"{freq:.2f}\t{db:.2f}\n")


def save_impulse_response(ir, output_path, sr=SAMPLE_RATE):
    """Save impulse response as a float32 WAV file."""
    sf.write(output_path, ir.astype(np.float32), sr, subtype='FLOAT')


def save_summary(output_path, metadata):
    """Save a measurement summary text file."""
    with open(output_path, 'w') as f:
        f.write("=" * 60 + "\n")
        f.write("NEAR-FIELD MEASUREMENT SUMMARY\n")
        f.write("=" * 60 + "\n\n")
        for key, value in metadata.items():
            f.write(f"{key}: {value}\n")


def plot_frequency_response(freqs, magnitude_db, output_path, title="",
                            smoothed_db=None):
    """
    Plot frequency response and save as PNG.

    Parameters
    ----------
    freqs : np.ndarray
        Frequency array.
    magnitude_db : np.ndarray
        Raw magnitude in dB.
    output_path : str
        Output PNG file path.
    title : str
        Plot title.
    smoothed_db : np.ndarray or None
        If provided, overlays a smoothed curve.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend (no display needed)
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib not available, skipping plot")
        return

    audio_band = (freqs >= 20) & (freqs <= 20000)
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.semilogx(freqs[audio_band], magnitude_db[audio_band],
                linewidth=0.5, alpha=0.5, color='gray', label='Raw')

    if smoothed_db is not None:
        ax.semilogx(freqs[audio_band], smoothed_db[audio_band],
                    linewidth=1.5, color='blue', label='1/6 oct smoothed')

    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel('Level (dB)')
    ax.set_title(title or 'Near-field Frequency Response')
    ax.set_xlim(20, 20000)
    ax.grid(True, which='both', alpha=0.3)
    ax.legend()

    # Set reasonable y-axis range
    valid = magnitude_db[audio_band]
    valid = valid[np.isfinite(valid)]
    if len(valid) > 0:
        y_max = np.max(valid) + 5
        y_min = max(np.min(valid), y_max - 60)
        ax.set_ylim(y_min, y_max)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  Plot saved to: {output_path}")


def phase1_calibration(output_channel, output_device_idx, input_device_idx,
                       level_dbfs=-40.0, duration_s=CAL_DEFAULT_DURATION_S,
                       sr=SAMPLE_RATE, ws_server=None, channel_name=None):
    """
    Phase 1: Play pink noise for level calibration (non-interactive).

    Plays pink noise for a fixed duration in blocks, reporting mic levels
    after each block. At the end, gives a pass/fail verdict based on whether
    the mic peak level falls within the target range. This works over
    non-TTY SSH (no Ctrl+C loop, no input() prompt).

    Returns True if calibration levels are acceptable (PASS), False otherwise.

    Parameters
    ----------
    output_channel : int
        0-indexed output channel.
    output_device_idx : int
        Sounddevice output device index.
    input_device_idx : int
        Sounddevice input device index (UMIK-1).
    level_dbfs : float
        Pink noise level in dBFS.
    duration_s : float
        Total calibration duration in seconds.
    sr : int
        Sample rate.

    Returns
    -------
    bool
        True if mic levels are within the target range (PASS).
    """
    sd = _sd_override
    if sd is None:
        import sounddevice as sd

    out_info = sd.query_devices(output_device_idx)
    n_out_channels = out_info['max_output_channels']

    n_blocks = max(1, int(round(duration_s / CAL_BLOCK_DURATION_S)))
    actual_duration = n_blocks * CAL_BLOCK_DURATION_S

    print("\n" + "=" * 60)
    print("PHASE 1: CALIBRATION")
    print("=" * 60)
    print(f"\nPlaying pink noise at {level_dbfs} dBFS on channel {output_channel}")
    print(f"Duration: {actual_duration:.0f}s ({n_blocks} blocks of "
          f"{CAL_BLOCK_DURATION_S:.0f}s)")
    print(f"Target mic peak: {CAL_TARGET_MIN_PEAK_DBFS:.0f} to "
          f"{CAL_TARGET_MAX_PEAK_DBFS:.0f} dBFS")
    print()

    overall_peak_dbfs = -200.0
    overall_rms_sum_sq = 0.0
    total_samples = 0

    for block_num in range(1, n_blocks + 1):
        noise = generate_pink_noise(
            CAL_BLOCK_DURATION_S, sr=sr, level_dbfs=level_dbfs)

        # Build multi-channel output
        output_buffer = np.zeros((len(noise), n_out_channels), dtype=np.float32)
        output_buffer[:, output_channel] = noise.astype(np.float32)

        # Play and record simultaneously to monitor mic levels
        recording = sd.playrec(
            output_buffer,
            samplerate=sr,
            input_mapping=[1],
            device=(input_device_idx, output_device_idx),
            dtype='float32',
        )
        sd.wait()

        # Compute block mic levels
        mic_signal = recording[:, 0]
        mic_rms = np.sqrt(np.mean(mic_signal ** 2))
        mic_peak = np.max(np.abs(mic_signal))
        mic_rms_dbfs = 20 * np.log10(max(mic_rms, 1e-10))
        mic_peak_dbfs = 20 * np.log10(max(mic_peak, 1e-10))

        # Track overall statistics
        overall_peak_dbfs = max(overall_peak_dbfs, mic_peak_dbfs)
        overall_rms_sum_sq += np.mean(mic_signal ** 2) * len(mic_signal)
        total_samples += len(mic_signal)

        # Report per-block levels
        status = ""
        if mic_peak_dbfs > CAL_CLIP_WARN_PEAK_DBFS:
            status = "  ** CLIPPING RISK **"
        elif mic_peak_dbfs > CAL_TARGET_MAX_PEAK_DBFS:
            status = "  (too loud)"
        elif mic_peak_dbfs < CAL_TARGET_MIN_PEAK_DBFS:
            status = "  (too quiet)"
        else:
            status = "  (OK)"
        print(f"  Block {block_num}/{n_blocks}: "
              f"RMS={mic_rms_dbfs:.1f} dBFS, Peak={mic_peak_dbfs:.1f} dBFS"
              f"{status}", flush=True)

    # Overall verdict
    overall_rms = np.sqrt(overall_rms_sum_sq / max(total_samples, 1))
    overall_rms_dbfs = 20 * np.log10(max(overall_rms, 1e-10))

    print(f"\n  Overall: RMS={overall_rms_dbfs:.1f} dBFS, "
          f"Peak={overall_peak_dbfs:.1f} dBFS")

    cal_pass = (CAL_TARGET_MIN_PEAK_DBFS <= overall_peak_dbfs
                <= CAL_TARGET_MAX_PEAK_DBFS)

    if cal_pass:
        print(f"\n  CALIBRATION PASS: mic peak {overall_peak_dbfs:.1f} dBFS "
              f"is within target range "
              f"[{CAL_TARGET_MIN_PEAK_DBFS:.0f}, "
              f"{CAL_TARGET_MAX_PEAK_DBFS:.0f}]")
    else:
        if overall_peak_dbfs < CAL_TARGET_MIN_PEAK_DBFS:
            print(f"\n  CALIBRATION FAIL: mic peak {overall_peak_dbfs:.1f} dBFS "
                  f"is below {CAL_TARGET_MIN_PEAK_DBFS:.0f} dBFS. "
                  f"Increase amp volume or raise --sweep-level.")
        else:
            print(f"\n  CALIBRATION FAIL: mic peak {overall_peak_dbfs:.1f} dBFS "
                  f"exceeds {CAL_TARGET_MAX_PEAK_DBFS:.0f} dBFS. "
                  f"Reduce amp volume.")

    # BACKLOG: AE recommends a programmatic safety gate here — verify that
    # the observed mic level matches the expected attenuation. If the mic
    # reads much louder than expected (e.g., convolver gain not applied),
    # abort before proceeding to the full sweep. This would catch
    # S-010-style bypass scenarios automatically.

    return cal_pass


def phase2_measurement(output_channel, output_device_idx, input_device_idx,
                       sweep_duration, sweep_level_dbfs, calibration_path,
                       output_dir, ir_length_s=0.05, speaker_name="",
                       sr=SAMPLE_RATE, ws_server=None):
    """
    Phase 2: Run the actual measurement.

    Generates a log sweep, plays it through the speaker, records the UMIK-1
    response, deconvolves, applies calibration, and saves all outputs.

    Includes xrun detection (queries PipeWire counters before and after each
    sweep) with automatic retry, and recording integrity validation.

    Parameters
    ----------
    output_channel : int
        0-indexed output channel.
    output_device_idx : int
        Sounddevice output device index.
    input_device_idx : int
        Sounddevice input device index.
    sweep_duration : float
        Sweep duration in seconds.
    sweep_level_dbfs : float
        Sweep level in dBFS.
    calibration_path : str or None
        Path to UMIK-1 calibration file.
    output_dir : str
        Output directory for all measurement files.
    ir_length_s : float
        Impulse response truncation length in seconds (default 0.05 = 50ms
        for near-field). Near-field IRs are compact; 50ms captures the
        full driver response without room reflections.
    speaker_name : str
        Speaker name for output identification.
    sr : int
        Sample rate.

    Returns
    -------
    bool
        True if measurement was successful.
    """
    print("\n" + "=" * 60)
    print("PHASE 2: MEASUREMENT")
    print("=" * 60)

    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Generate log sweep
    print("\n[1/6] Generating log sweep...")
    sweep_signal = generate_log_sweep(
        duration=sweep_duration,
        f_start=20.0,
        f_end=20000.0,
        sr=sr,
    )
    # Scale to requested level
    target_peak = dsp_utils.db_to_linear(sweep_level_dbfs)
    sweep_signal *= target_peak / np.max(np.abs(sweep_signal))

    sweep_path = os.path.join(output_dir, "sweep_reference.wav")
    sf.write(sweep_path, sweep_signal.astype(np.float32), sr, subtype='FLOAT')
    print(f"  Sweep: {len(sweep_signal)} samples ({sweep_duration:.1f}s), "
          f"peak={sweep_level_dbfs:.0f} dBFS")
    print(f"  Reference sweep saved to: {sweep_path}")

    # Step 2: Play sweep and record (with xrun detection and auto-retry)
    recording = None
    for attempt in range(1, MAX_XRUN_RETRIES + 1):
        if attempt > 1:
            print(f"\n  --- Retry {attempt}/{MAX_XRUN_RETRIES} ---")
            time.sleep(1.0)  # Brief pause between retries

        print(f"\n[2/6] Playing sweep and recording (attempt {attempt})...")

        # Read xrun counter before sweep
        xrun_before = get_pipewire_xrun_count()

        # Broadcast sweep start via WS
        if ws_server is not None:
            ws_server.broadcast({
                "type": "sweep_progress",
                "channel": output_channel,
                "channel_name": speaker_name or f"ch{output_channel}",
                "position": 1,
                "phase": "sweep",
                "progress_pct": 0.0,
                "mic_peak_dbfs": 0.0,
                "mic_rms_dbfs": 0.0,
                "xrun_count": 0,
                "elapsed_s": 0.0,
                "total_s": sweep_duration,
            })

        t0 = time.time()
        recording, pre_roll = play_and_record(
            sweep_signal,
            output_channel=output_channel,
            output_device_idx=output_device_idx,
            input_device_idx=input_device_idx,
            sr=sr,
            pre_roll_s=0.5,
            post_roll_s=1.0,
        )
        elapsed = time.time() - t0
        print(f"  Recording complete: {len(recording)} samples ({elapsed:.1f}s)")

        # Broadcast sweep completion progress via WS
        if ws_server is not None:
            rec_peak = float(np.max(np.abs(recording)))
            rec_rms = float(np.sqrt(np.mean(recording ** 2)))
            ws_server.broadcast({
                "type": "sweep_progress",
                "channel": output_channel,
                "channel_name": speaker_name or f"ch{output_channel}",
                "position": 1,
                "phase": "sweep",
                "progress_pct": 100.0,
                "mic_peak_dbfs": float(20 * np.log10(max(rec_peak, 1e-10))),
                "mic_rms_dbfs": float(20 * np.log10(max(rec_rms, 1e-10))),
                "xrun_count": 0,
                "elapsed_s": elapsed,
                "total_s": sweep_duration,
            })

        # Read xrun counter after sweep
        xrun_after = get_pipewire_xrun_count()

        # Check for xruns during measurement
        if xrun_before is not None and xrun_after is not None:
            xrun_delta = xrun_after - xrun_before
            if xrun_delta > 0:
                print(f"  ** XRUN DETECTED: {xrun_delta} xrun(s) during sweep! **")
                if attempt < MAX_XRUN_RETRIES:
                    print(f"  Discarding this recording and retrying...")
                    continue
                else:
                    print(f"  ** Max retries reached. Using last recording despite xruns. **")
            else:
                print(f"  Xrun check: clean (no xruns during sweep)")
        else:
            print("  Xrun check: skipped (counter unavailable)")

        # Recording integrity validation (uses pre-roll for noise floor)
        print("\n  Recording integrity check...")
        integrity_ok, integrity_details = check_recording_integrity(
            recording, pre_roll, sr=sr
        )
        print(f"    Peak:        {integrity_details['peak_dbfs']:.1f} dBFS")
        print(f"    RMS:         {integrity_details['rms_dbfs']:.1f} dBFS")
        print(f"    DC offset:   {integrity_details['dc_offset']:.5f}")
        print(f"    Noise floor: {integrity_details['noise_floor_dbfs']:.1f} dBFS "
              f"(from {len(pre_roll)/sr*1000:.0f}ms pre-roll)")
        print(f"    SNR:         {integrity_details['snr_db']:.1f} dB")

        if integrity_details['issues']:
            for issue in integrity_details['issues']:
                print(f"    ** {issue} **")
            if not integrity_ok:
                if attempt < MAX_XRUN_RETRIES:
                    print(f"  Recording integrity FAILED, retrying...")
                    continue
                else:
                    print(f"  Recording integrity FAILED after {MAX_XRUN_RETRIES} retries.")
                    print(f"  Cannot produce a reliable measurement. Aborting.")
                    print(f"  Check: environment noise, mic connection, device levels.")
                    return False
        else:
            print("    All integrity checks PASSED")

        # If we got here without continuing, the recording is acceptable

        # Broadcast sweep_complete via WS
        if ws_server is not None:
            snr = integrity_details.get('snr_db', 0.0)
            if integrity_details['peak_dbfs'] > REC_MAX_PEAK_DBFS:
                quality = "clipped"
            elif snr >= 35:
                quality = "good"
            elif snr >= 25:
                quality = "ok"
            else:
                quality = "poor"
            xrun_during = False
            if xrun_before is not None and xrun_after is not None:
                xrun_during = (xrun_after - xrun_before) > 0
            ws_server.broadcast({
                "type": "sweep_complete",
                "channel": output_channel,
                "channel_name": speaker_name or f"ch{output_channel}",
                "position": 1,
                "quality": quality,
                "snr_db": float(snr),
                "peak_dbfs": float(integrity_details['peak_dbfs']),
                "rms_dbfs": float(integrity_details['rms_dbfs']),
                "xrun_during_sweep": xrun_during,
                "wav_path": os.path.join(output_dir, "raw_recording.wav"),
            })

        break

    # Save raw recording
    raw_recording_path = os.path.join(output_dir, "raw_recording.wav")
    sf.write(raw_recording_path, recording.astype(np.float32), sr, subtype='FLOAT')
    print(f"  Raw recording saved to: {raw_recording_path}")

    # Step 3: Deconvolve to get impulse response
    print(f"\n[3/6] Deconvolving to extract impulse response (IR length: {ir_length_s}s)...")
    if ws_server is not None:
        ws_server.broadcast({
            "type": "pipeline_progress",
            "stage": "deconvolution",
            "channel": output_channel,
            "channel_name": speaker_name or f"ch{output_channel}",
            "progress_pct": 0.0,
            "d009_check": None,
        })
    t0 = time.time()
    ir = deconvolve(recording, sweep_signal, sr=sr, ir_duration_s=ir_length_s)
    elapsed = time.time() - t0
    print(f"  IR length: {len(ir)} samples ({len(ir)/sr*1000:.1f}ms)")
    print(f"  Deconvolution time: {elapsed:.2f}s")
    if ws_server is not None:
        ws_server.broadcast({
            "type": "pipeline_progress",
            "stage": "deconvolution",
            "channel": output_channel,
            "channel_name": speaker_name or f"ch{output_channel}",
            "progress_pct": 100.0,
            "d009_check": None,
        })

    # Save impulse response
    ir_path = os.path.join(output_dir, "impulse_response.wav")
    save_impulse_response(ir, ir_path, sr=sr)
    print(f"  IR saved to: {ir_path}")

    # Step 4: Apply UMIK-1 calibration
    if calibration_path:
        print(f"\n[4/6] Applying UMIK-1 calibration from {calibration_path}...")
        if ws_server is not None:
            ws_server.broadcast({
                "type": "pipeline_progress",
                "stage": "correction",
                "channel": output_channel,
                "channel_name": speaker_name or f"ch{output_channel}",
                "progress_pct": 0.0,
                "d009_check": None,
            })
        t0 = time.time()
        ir_calibrated = apply_umik1_calibration(ir, calibration_path, sr=sr)
        elapsed = time.time() - t0
        print(f"  Calibration applied ({elapsed:.2f}s)")
        if ws_server is not None:
            ws_server.broadcast({
                "type": "pipeline_progress",
                "stage": "correction",
                "channel": output_channel,
                "channel_name": speaker_name or f"ch{output_channel}",
                "progress_pct": 100.0,
                "d009_check": None,
            })

        ir_cal_path = os.path.join(output_dir, "impulse_response_calibrated.wav")
        save_impulse_response(ir_calibrated, ir_cal_path, sr=sr)
        print(f"  Calibrated IR saved to: {ir_cal_path}")
    else:
        print("\n[4/6] No calibration file provided, using raw IR")
        ir_calibrated = ir

    # Step 5: Compute frequency response
    print("\n[5/6] Computing frequency response...")
    freqs, magnitude_db = compute_frequency_response(ir_calibrated, sr=sr)

    # Save raw (unsmoothed) frequency response -- archival data
    fr_raw_path = os.path.join(output_dir, "frequency_response_raw.txt")
    save_frequency_response(freqs, magnitude_db, fr_raw_path)
    print(f"  Raw frequency response saved to: {fr_raw_path}")

    # Compute psychoacoustically smoothed version for display/analysis
    # (1/6 oct below 200Hz, 1/3 oct 200Hz-1kHz, 1/2 oct above 1kHz)
    magnitude_linear = dsp_utils.db_to_linear(magnitude_db)
    smoothed_linear = dsp_utils.psychoacoustic_smooth(magnitude_linear, freqs)
    smoothed_db = dsp_utils.linear_to_db(smoothed_linear)

    fr_smooth_path = os.path.join(output_dir, "frequency_response_smoothed.txt")
    save_frequency_response(freqs, smoothed_db, fr_smooth_path)
    print(f"  Smoothed frequency response saved to: {fr_smooth_path}")

    # Step 6: Compute summary metrics
    print("\n[6/6] Computing summary metrics...")
    peak_freq, peak_db = find_peak_frequency(freqs, smoothed_db)
    f3 = find_f3(freqs, smoothed_db)

    # Bandwidth: frequency range within 6dB of the passband average
    band_200_2k = (freqs >= 200) & (freqs <= 2000)
    if np.any(band_200_2k):
        passband_avg = np.mean(smoothed_db[band_200_2k])
    else:
        passband_avg = peak_db

    bw_mask = (freqs >= 20) & (freqs <= 20000) & (
        smoothed_db >= passband_avg - 6.0
    )
    bw_freqs = freqs[bw_mask]
    if len(bw_freqs) > 0:
        bw_low = float(bw_freqs[0])
        bw_high = float(bw_freqs[-1])
        bandwidth_str = f"{bw_low:.0f}Hz - {bw_high:.0f}Hz (-6dB)"
    else:
        bandwidth_str = "N/A"

    # Print 1/3-octave summary
    third_octave = [
        20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160,
        200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600,
        2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000,
    ]

    print("\n  1/3-octave frequency response:")
    print(f"  {'Freq (Hz)':>10}  {'Level (dB)':>10}")
    print(f"  {'----------':>10}  {'----------':>10}")
    for fc in third_octave:
        if fc > sr / 2:
            break
        idx = np.argmin(np.abs(freqs - fc))
        level = smoothed_db[idx]
        print(f"  {fc:>10.1f}  {level:>10.1f}")

    # Summary
    metadata = {
        "Date": datetime.datetime.now().isoformat(),
        "Speaker": speaker_name or f"channel {output_channel}",
        "Output channel": output_channel,
        "Sweep duration": f"{sweep_duration}s",
        "Sweep level": f"{sweep_level_dbfs} dBFS",
        "Sample rate": f"{sr} Hz",
        "IR truncation": f"{ir_length_s}s ({ir_length_s*1000:.0f}ms)",
        "Calibration file": calibration_path or "None",
        "Recording peak": f"{integrity_details['peak_dbfs']:.1f} dBFS",
        "Recording RMS": f"{integrity_details['rms_dbfs']:.1f} dBFS",
        "DC offset": f"{integrity_details['dc_offset']:.5f}",
        "Noise floor": f"{integrity_details['noise_floor_dbfs']:.1f} dBFS",
        "SNR": f"{integrity_details['snr_db']:.1f} dB",
        "Recording integrity": "PASS" if integrity_ok else "FAIL",
        "IR length": f"{len(ir)} samples ({len(ir)/sr*1000:.1f}ms)",
        "Peak frequency": f"{peak_freq:.0f} Hz ({peak_db:.1f} dB)",
        "F3 (-3dB)": f"{f3:.0f} Hz" if f3 else "N/A",
        "Passband average (200-2k)": f"{passband_avg:.1f} dB",
        "Bandwidth (-6dB)": bandwidth_str,
    }

    summary_path = os.path.join(output_dir, "measurement_summary.txt")
    save_summary(summary_path, metadata)
    print(f"\n  Summary saved to: {summary_path}")

    print("\n  Key metrics:")
    print(f"    Peak frequency:           {peak_freq:.0f} Hz ({peak_db:.1f} dB)")
    print(f"    F3 (-3dB point):          {f3:.0f} Hz" if f3 else
          "    F3 (-3dB point):          N/A")
    print(f"    Passband average (200-2k): {passband_avg:.1f} dB")
    print(f"    Bandwidth (-6dB):         {bandwidth_str}")

    # Plot
    plot_path = os.path.join(output_dir, "frequency_response.png")
    plot_frequency_response(
        freqs, magnitude_db, plot_path,
        title=f"Near-field measurement - {speaker_name or f'channel {output_channel}'}",
        smoothed_db=smoothed_db,
    )

    print("\n" + "=" * 60)
    print("MEASUREMENT COMPLETE")
    print("=" * 60)
    print(f"\nAll outputs saved to: {output_dir}")
    print("Files:")
    print(f"  {sweep_path}")
    print(f"  {raw_recording_path}")
    print(f"  {ir_path}")
    if calibration_path:
        print(f"  {ir_cal_path}")
    print(f"  {fr_raw_path}")
    print(f"  {fr_smooth_path}")
    print(f"  {summary_path}")
    print(f"  {plot_path}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Near-field speaker measurement using log sweep and UMIK-1.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--channel", type=int, default=0,
        help=(
            "Output channel to measure, 0-indexed (default: 0 = left satellite). "
            "Channel mapping: 0=left sat, 1=right sat, 2=sub1, 3=sub2"
        ),
    )
    parser.add_argument(
        "--speaker-name", type=str, default=None,
        help=(
            "Speaker name for output identification (e.g., 'chn50p-left'). "
            "Used in output filenames, plot titles, and summary. "
            "If not provided, defaults to 'ch{channel}'."
        ),
    )
    parser.add_argument(
        "--speaker-profile", type=str, default=None,
        help=(
            "Speaker profile name (without .yml) for loading speaker identity "
            "and mandatory HPF. Used to look up excursion protection parameters. "
            "Required for measurement (not needed with --list-devices). "
            "Example: 'bose-home-chn50p'."
        ),
    )
    parser.add_argument(
        "--mic-device", type=str, default="UMIK",
        help="UMIK-1 input device name substring (default: 'UMIK')",
    )
    parser.add_argument(
        "--output-device", type=str, default="pipewire",
        help=(
            "Output device name substring (default: 'pipewire'). Audio routing "
            "is managed by GraphManager: signal-gen -> convolver -> USBStreamer. "
            "This parameter is used for sounddevice device selection in non-"
            "signal-gen mode only."
        ),
    )
    parser.add_argument(
        "--calibration", type=str, default=None,
        help="Path to UMIK-1 calibration file (miniDSP .txt format)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="./measurements/nearfield/",
        help=(
            "Base output directory. A timestamped subdirectory is created "
            "automatically to prevent overwriting previous measurements "
            "(default: ./measurements/nearfield/)"
        ),
    )
    parser.add_argument(
        "--sweep-duration", type=float, default=5.0,
        help="Sweep duration in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--sweep-level", type=float, default=-20.0,
        help=(
            "Sweep peak level in dBFS (default: -20.0). Hard cap at -20 dBFS "
            "(defense-in-depth). The signal generator enforces this immutably "
            "in its RT callback. At -20 dBFS: ~4.5W into 4 ohm (survivable). "
            "With convolver attenuation (-20dB): ~0.045W. See S-010 incident."
        ),
    )
    parser.add_argument(
        "--ir-length", type=float, default=0.05,
        help=(
            "Impulse response truncation length in seconds (default: 0.05 = "
            "50ms for near-field). Near-field measurements have minimal room "
            "contribution; 50ms captures the full driver response. Use longer "
            "values (e.g., 1.0-2.0) for far-field room measurements."
        ),
    )
    parser.add_argument(
        "--skip-calibration-phase", action="store_true",
        help="Skip Phase 1 (pink noise calibration) and go directly to measurement",
    )
    parser.add_argument(
        "--calibration-duration", type=float, default=CAL_DEFAULT_DURATION_S,
        help=(
            f"Phase 1 calibration duration in seconds "
            f"(default: {CAL_DEFAULT_DURATION_S:.0f}). Pink noise plays for this "
            f"duration in {CAL_BLOCK_DURATION_S:.0f}s blocks with mic level "
            f"reporting after each block."
        ),
    )
    parser.add_argument(
        "--skip-preflight", action="store_true",
        help="Skip pre-flight checks (web UI service, xrun baseline)",
    )
    parser.add_argument(
        "--list-devices", action="store_true",
        help="List available audio devices and exit",
    )
    parser.add_argument(
        "--sample-rate", type=int, default=SAMPLE_RATE,
        help=f"Sample rate in Hz (default: {SAMPLE_RATE})",
    )
    parser.add_argument(
        "--signal-gen-host", type=str, default=SIGNAL_GEN_DEFAULT_HOST,
        help=f"Signal generator RPC host (default: {SIGNAL_GEN_DEFAULT_HOST})",
    )
    parser.add_argument(
        "--signal-gen-port", type=int, default=SIGNAL_GEN_DEFAULT_PORT,
        help=f"Signal generator RPC port (default: {SIGNAL_GEN_DEFAULT_PORT})",
    )
    parser.add_argument(
        "--gm-host", type=str, default=GRAPH_MANAGER_DEFAULT_HOST,
        help=f"GraphManager RPC host (default: {GRAPH_MANAGER_DEFAULT_HOST})",
    )
    parser.add_argument(
        "--gm-port", type=int, default=GRAPH_MANAGER_DEFAULT_PORT,
        help=f"GraphManager RPC port (default: {GRAPH_MANAGER_DEFAULT_PORT})",
    )
    parser.add_argument(
        "--mock", action="store_true",
        help=(
            "Run in mock mode: replace sounddevice and signal-gen with mock "
            "backends that simulate audio I/O using a synthetic room model. "
            "Enables testing the full pipeline on macOS without audio hardware."
        ),
    )
    parser.add_argument(
        "--mock-room-config", type=str, default=None,
        help=(
            "Path to a mock room configuration YAML file (only used with "
            "--mock). Defaults to src/room-correction/mock/room_config.yml."
        ),
    )
    parser.add_argument(
        "--ws", action="store_true",
        help=(
            "Enable the embedded WebSocket server for real-time progress "
            "reporting. The measurement script publishes progress messages "
            "to connected clients (e.g., the web UI). When not set, "
            "measurement works exactly as before (CLI output only)."
        ),
    )
    parser.add_argument(
        "--ws-port", type=int, default=8081,
        help="WebSocket server listen port (default: 8081). Only used with --ws.",
    )

    args = parser.parse_args()
    sr = args.sample_rate

    # Check dependencies (mock mode substitutes real modules)
    global _sd_override
    if args.mock:
        from mock.mock_audio import MockSoundDevice
        _sd_override = MockSoundDevice(room_config_path=args.mock_room_config)
        sd = _sd_override
        print("MOCK MODE: using MockSoundDevice (no real audio I/O)")
    else:
        try:
            import sounddevice as sd
        except ImportError:
            print("ERROR: sounddevice not installed.")
            print("Install with: pip3 install sounddevice")
            sys.exit(1)

    if not args.mock:
        try:
            from signal_gen_client import SignalGenClient  # noqa: F401
        except ImportError:
            print("ERROR: signal_gen_client not found.")
            print("Ensure src/measurement/ is in PYTHONPATH.")
            sys.exit(1)
        try:
            from graph_manager_client import GraphManagerClient  # noqa: F401
        except ImportError:
            print("ERROR: graph_manager_client not found.")
            print("Ensure src/measurement/ is in PYTHONPATH.")
            sys.exit(1)

    if args.list_devices:
        list_audio_devices()
        sys.exit(0)

    # --speaker-profile is required for measurement (but not for --list-devices)
    if args.speaker_profile is None:
        parser.error("--speaker-profile is required for measurement")

    # SAFETY: enforce hard cap on sweep level (defense-in-depth, S-010 incident)
    # The signal-gen also enforces this immutably in its RT callback, but we
    # check here too for early error reporting.
    if args.sweep_level > SWEEP_LEVEL_HARD_CAP_DBFS:
        print(f"ERROR: Sweep level {args.sweep_level} dBFS exceeds safety cap "
              f"of {SWEEP_LEVEL_HARD_CAP_DBFS} dBFS.")
        print(f"Defense-in-depth: the signal generator enforces -20 dBFS "
              f"immutably. At -20 dBFS: ~4.5W into 4 ohm. "
              f"See S-010 incident.")
        print(f"Maximum allowed: {SWEEP_LEVEL_HARD_CAP_DBFS} dBFS.")
        sys.exit(1)

    # Validate calibration file exists
    if args.calibration and not os.path.isfile(args.calibration):
        print(f"ERROR: Calibration file not found: {args.calibration}")
        sys.exit(1)

    # Find devices
    print("Looking for audio devices...")
    mic_idx = find_device(args.mic_device, kind='input')
    out_idx = find_device(args.output_device, kind='output')

    if mic_idx is None:
        print(f"ERROR: Microphone device '{args.mic_device}' not found.")
        list_audio_devices()
        sys.exit(1)

    if out_idx is None:
        print(f"ERROR: Output device '{args.output_device}' not found.")
        list_audio_devices()
        sys.exit(1)

    # Resolve speaker name
    speaker_name = args.speaker_name or f"ch{args.channel}"

    # Create timestamped output directory to prevent overwriting
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = os.path.join(args.output_dir, f"{speaker_name}_{timestamp}")

    mic_info = sd.query_devices(mic_idx)
    out_info = sd.query_devices(out_idx)
    print(f"  Speaker:     {speaker_name}")
    print(f"  Profile:     {args.speaker_profile}")
    print(f"  Microphone:  [{mic_idx}] {mic_info['name']}")
    print(f"  Output:      [{out_idx}] {out_info['name']}")
    print(f"  Channel:     {args.channel}")
    print(f"  Sample rate: {sr} Hz")
    print(f"  Sweep:       {args.sweep_duration}s at {args.sweep_level} dBFS")
    print(f"  IR length:   {args.ir_length}s")
    print(f"  Output dir:  {output_dir}")
    if args.calibration:
        print(f"  Calibration: {args.calibration}")
    else:
        print("  Calibration: NONE (raw UMIK-1 response)")

    # Pre-flight checks (skipped in mock mode — no real services to check)
    if args.mock:
        print("\nMOCK MODE: skipping pre-flight checks")
    elif not args.skip_preflight:
        preflight_ok = run_preflight_checks()
        if not preflight_ok:
            print("\nAborting: pre-flight checks failed.")
            print("Fix the issues above, or use --skip-preflight to override.")
            sys.exit(1)

    # Look up HPF and set up measurement routing (D-040)
    print("\n" + "=" * 60)
    print("MEASUREMENT SETUP")
    print("=" * 60)

    print(f"\nLooking up speaker profile '{args.speaker_profile}' "
          f"for channel {args.channel}...")
    try:
        mandatory_hpf_hz = get_mandatory_hpf_hz(
            test_channel=args.channel,
            speaker_profile_name=args.speaker_profile,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Operator warning about HPF protection
    if mandatory_hpf_hz is not None:
        print(f"\n  Digital HPF at {mandatory_hpf_hz}Hz will be applied to sweep "
              f"signal (excursion protection).")
        print(f"  Content below {mandatory_hpf_hz}Hz will be attenuated "
              f"(4th-order Butterworth, 24dB/oct).")
        print(f"  The sweep starts at 20Hz; the HPF will shape the output "
              f"below {mandatory_hpf_hz}Hz.")
        print(f"  NOTE (D-031): HPF is applied in numpy, not in the RT signal "
              f"path. Primary safety is the signal-gen -20 dBFS hard cap.")
    else:
        print("\n  ** WARNING: No mandatory HPF found in speaker identity! **")
        print("  ** Excursion protection is NOT active. Proceed with caution. **")
        print("  ** Primary safety: signal-gen -20 dBFS hard cap. **")

    print(f"\n  Convolver attenuation: {MEASUREMENT_ATTENUATION_DB}dB "
          f"on channel {args.channel}")
    print(f"  All other channels muted (Mult=0.0)")

    gm_client = None
    original_gains = {}
    success = False
    ws_server = None
    previous_mode = None

    # Start WebSocket server if --ws is set
    if args.ws:
        from room_correction.ws_server import MeasurementWSServer
        ws_server = MeasurementWSServer(port=args.ws_port)
        try:
            ws_server.start()
            print(f"\nWebSocket server started on ws://127.0.0.1:{args.ws_port}")
        except Exception as e:
            print(f"\nWARNING: Failed to start WebSocket server: {e}")
            print("Continuing without WS progress reporting.")
            ws_server = None

    if args.mock:
        from graph_manager_client import MockGraphManagerClient
        gm_client = MockGraphManagerClient()
        gm_client.connect()
        print("MOCK MODE: using MockGraphManagerClient (no real signal-gen/GM)")
    else:
        print("\nSetting up measurement routing...")

    try:
        if not args.mock:
            # Connect to GraphManager and switch to measurement mode
            from graph_manager_client import GraphManagerClient
            gm_client = GraphManagerClient(
                host=args.gm_host, port=args.gm_port)
            gm_client.connect()

            # Save current mode for restoration
            previous_mode = gm_client.get_mode()
            print(f"  Current GraphManager mode: {previous_mode}")

            # Switch to measurement mode
            gm_client.enter_measurement_mode()
            gm_client.verify_measurement_mode()
            print("  GraphManager switched to measurement mode")

            # Set convolver gains for measurement
            print("\nSetting convolver gains...")
            original_gains = set_measurement_gains(args.channel)

        # Phase 1: Calibration (non-interactive, fixed duration)
        cal_pass = True
        if not args.skip_calibration_phase:
            cal_pass = phase1_calibration(
                output_channel=args.channel,
                output_device_idx=out_idx,
                input_device_idx=mic_idx,
                level_dbfs=args.sweep_level,
                duration_s=args.calibration_duration,
                sr=sr,
                ws_server=ws_server,
                channel_name=speaker_name,
            )
            if not cal_pass:
                print("\nCalibration FAILED. Adjust levels and re-run.")
                print("Skipping Phase 2 (measurement).")

        # Phase 2: Measurement (only if calibration passed)
        if cal_pass:
            success = phase2_measurement(
                output_channel=args.channel,
                output_device_idx=out_idx,
                input_device_idx=mic_idx,
                sweep_duration=args.sweep_duration,
                sweep_level_dbfs=args.sweep_level,
                calibration_path=args.calibration,
                output_dir=output_dir,
                ir_length_s=args.ir_length,
                speaker_name=speaker_name,
                sr=sr,
                ws_server=ws_server,
            )
    except KeyboardInterrupt:
        print("\n\nMeasurement interrupted by user.")
    except Exception as e:
        print(f"\nERROR: {e}")
        if gm_client is None and not args.mock:
            print("Is pi4audio-graph-manager running? "
                  f"Check: ss -tlnp | grep {args.gm_port}")
            print("Is pi4audio-signal-gen running? "
                  f"Check: ss -tlnp | grep {args.signal_gen_port}")
    finally:
        # Stop WebSocket server
        if ws_server is not None:
            try:
                ws_server.stop()
            except Exception:
                pass

        restore_ok = True
        if args.mock:
            pass  # Nothing to restore in mock mode
        elif gm_client is not None:
            # Restore production routing
            print("\nRestoring production routing...")
            try:
                # Restore convolver gains (safety net — GM mode switch
                # re-applies production config, but we reset explicitly too)
                if original_gains:
                    restore_production_gains(original_gains)

                # Switch GraphManager back to previous mode
                restore_mode = previous_mode or "monitoring"
                gm_client.set_mode(restore_mode)
                print(f"  GraphManager restored to mode: {restore_mode}")
            except Exception as e:
                print(f"\n  ** WARNING: Failed to restore production routing: {e} **")
                print("  ** PA OUTPUT may be in measurement mode **")
                print("  ** Manual restore: restart GraphManager or use RPC **")
                print("  ** (GraphManager mode switch is transient-free) **")
                restore_ok = False
            finally:
                try:
                    gm_client.close()
                except Exception:
                    pass

            # Amp level warning
            print("\n  ** CHECK AMP LEVELS **")
            print("  GraphManager has been restored to production routing.")
            print("  If you adjusted amp volume during the measurement,")
            print("  verify levels are appropriate for normal listening.")

    # Exit codes: 0 = success, 1 = measurement failed, 2 = restore failed
    # (system may be in measurement mode — non-production routing)
    if not restore_ok:
        sys.exit(2)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
