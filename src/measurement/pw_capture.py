"""PipeWire capture utility — record from a PW source node via pw-record.

Wraps the ``pw-record`` subprocess to capture audio from any PipeWire
source node (e.g. the UMIK-1).  Used by the measurement session to
replace the old ``playrec`` pattern with separated play + capture.

Signal flow (production):
    real UMIK-1 hardware -> pw-record -> WAV file -> numpy array

Signal flow (local-demo):
    speaker convolver -> room-sim convolver -> UMIK-1 loopback
    -> pw-record -> WAV file -> numpy array

The measurement code is identical in both cases — the only difference
is what PipeWire node backs the target name.

F-235 fix: In local-demo, WP policy.standard is disabled (D-039/F-210),
so pw-record's Stream/Input/Audio node never auto-activates via --target.
The fix uses --target 0 (no auto-link) with explicit node activation
properties, then manually creates the link via pw-link.  On production
(WP policy active), --target works normally and the manual pw-link is
a harmless no-op (link already exists).

Usage::

    capture = start_capture("alsa_input.usb-miniDSP_UMIK-1", "/tmp/cap.wav")
    # ... play sweep via signal-gen ...
    stop_capture(capture)
    recording = load_wav("/tmp/cap.wav")
"""

import logging
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Default PipeWire source node for the UMIK-1 microphone.
DEFAULT_TARGET = "alsa_input.usb-miniDSP_Umik-1"
SAMPLE_RATE = 48000


def _set_default_source(target: str) -> None:
    """Set the PipeWire default audio source via pw-metadata.

    Best-effort hint for environments where WP's linking policy is active
    (production).  In local-demo, policy.standard is disabled (F-210) and
    pw-record uses ``--target`` directly instead.
    """
    cmd = [
        "pw-metadata", "-n", "default", "0",
        "default.audio.source",
        f'{{"name":"{target}"}}',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        logger.warning("pw-metadata set default source failed: %s", result.stderr)
    else:
        logger.info("Set default audio source to %s", target)


def _get_pw_record_input_ports() -> list[str]:
    """Discover pw-record's input port names via ``pw-link -i``."""
    try:
        result = subprocess.run(
            ["pw-link", "-i"], capture_output=True, text=True, timeout=3,
        )
        ports = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("pw-record:") or stripped.startswith("pw-cat:"):
                ports.append(stripped)
        return ports
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _get_source_output_port(target: str) -> Optional[str]:
    """Find the first output port of *target* via ``pw-link -o``."""
    try:
        result = subprocess.run(
            ["pw-link", "-o"], capture_output=True, text=True, timeout=3,
        )
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{target}:"):
                return stripped
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _ensure_link(target: str, channels: int) -> None:
    """Create a PipeWire link from *target* source to pw-record.

    F-235: When WP policy.standard is disabled (local-demo), pw-record
    with ``--target 0`` creates ports but no links.  This function
    discovers the port names and links them manually via ``pw-link``.
    On production (WP policy active), the link may already exist — we
    ignore "already linked" errors.
    """
    record_ports = _get_pw_record_input_ports()
    if not record_ports:
        logger.warning("pw-record has no input ports — link skipped")
        return

    source_port = _get_source_output_port(target)
    if source_port is None:
        logger.warning("Source %s has no output ports — link skipped", target)
        return

    # For mono capture, link the source to the first pw-record input port.
    # For multi-channel, link each source output to the corresponding input.
    record_input = record_ports[0]
    try:
        result = subprocess.run(
            ["pw-link", source_port, record_input],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            logger.info("Linked %s -> %s", source_port, record_input)
        else:
            stderr = result.stderr.strip()
            # "File exists" means link already exists — not an error.
            if "exists" in stderr.lower():
                logger.info("Link already exists: %s -> %s",
                            source_port, record_input)
            else:
                logger.warning("pw-link failed: %s", stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("pw-link unavailable: %s", exc)


def start_capture(
    output_path: str,
    target: str = DEFAULT_TARGET,
    sample_rate: int = SAMPLE_RATE,
    channels: int = 1,
    pw_record_bin: Optional[str] = None,
) -> subprocess.Popen:
    """Start a pw-record subprocess capturing from *target*.

    Parameters
    ----------
    output_path : str
        Path for the output WAV file.
    target : str
        PipeWire node name to capture from.
    sample_rate : int
        Sample rate (default 48000).
    channels : int
        Number of channels (default 1 for UMIK-1 mono).
    pw_record_bin : str or None
        Path to pw-record binary.  If None, uses PATH lookup.

    Returns
    -------
    subprocess.Popen
        The running pw-record process.  Call ``stop_capture()`` to
        terminate it cleanly.
    """
    # Set default source as best-effort hint (works with WP policy.standard).
    _set_default_source(target)

    # Ensure output directory exists.
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    bin_path = pw_record_bin or "pw-record"
    # F-235: Use --target 0 (no auto-link) with explicit activation
    # properties.  This forces pw-record's stream node to create ports
    # even when WP policy.standard is disabled (local-demo, D-039/F-210).
    # On production (WP policy active), --target 0 still works — we
    # create the link manually via pw-link afterwards.
    cmd = [
        bin_path,
        "--target", "0",
        "-P", "node.always-process=true,node.passive=true,node.want-driver=true",
        "--rate", str(sample_rate),
        "--channels", str(channels),
        "--format", "f32",
        output_path,
    ]
    logger.info("Starting capture: %s", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    # Settle time for pw-record to create ports.
    time.sleep(1.0)

    if proc.poll() is not None:
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        raise RuntimeError(
            f"pw-record exited immediately (rc={proc.returncode}): {stderr}"
        )

    # F-235: Manually link the target source to pw-record.
    # pw-record with --target 0 creates ports but no links.
    # The port name is "input_MONO" for mono capture, "input_FL" for
    # stereo left, etc.  We discover the actual port name via pw-link -i.
    _ensure_link(target, channels)

    logger.info("Capture started (pid=%d, target=%s, path=%s)",
                proc.pid, target, output_path)
    return proc


def stop_capture(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    """Stop a pw-record subprocess with SIGINT (clean WAV finalization).

    Parameters
    ----------
    proc : subprocess.Popen
        The pw-record process returned by ``start_capture()``.
    timeout : float
        Seconds to wait for graceful exit before SIGKILL.
    """
    if proc.poll() is not None:
        logger.info("Capture already exited (rc=%d)", proc.returncode)
        return

    # SIGINT triggers pw-record's clean shutdown — it finalizes the
    # WAV header with the correct sample count.
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=timeout)
        logger.info("Capture stopped cleanly (rc=%d)", proc.returncode)
    except subprocess.TimeoutExpired:
        logger.warning("Capture did not exit after SIGINT, sending SIGKILL")
        proc.kill()
        proc.wait(timeout=2.0)


def load_wav(path: str, dtype: str = "float64") -> np.ndarray:
    """Load a WAV file recorded by pw-record.

    Parameters
    ----------
    path : str
        Path to the WAV file.
    dtype : str
        Output numpy dtype (default float64 to match gain_calibration).

    Returns
    -------
    np.ndarray
        Audio data, shape (n_frames, n_channels).
    """
    data, sr = sf.read(path, dtype=dtype)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    logger.info("Loaded capture: %d frames, %d ch, %d Hz from %s",
                data.shape[0], data.shape[1], sr, path)
    return data
