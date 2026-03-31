"""PipeWire capture utility — record from a PW source node via pw-record.

Wraps the ``pw-record`` subprocess to capture audio from any PipeWire
source node (e.g. the UMIK-1).  Used by the measurement session to
replace the old ``playrec`` pattern with separated play + capture.

Signal flow (production):
    real UMIK-1 hardware -> pw-record -> WAV file -> numpy array

Signal flow (local-demo, pcm-bridge fallback — F-235):
    speaker convolver -> room-sim convolver -> UMIK-1 source
    -> pcm-bridge (ch3) -> TCP -> WAV file -> numpy array

On production, WirePlumber's linking policy auto-links pw-record to
its target node.  In local-demo, policy.standard is disabled (F-210:
GM is sole link manager), so pw-record's stream never activates —
its ports are never created and it captures zero audio.

F-235 fix: when pw-record fails (no ports after settle time), fall
back to capturing from pcm-bridge's TCP stream.  pcm-bridge already
taps the UMIK-1 on channel 3 and streams gapless PCM data.

Usage::

    capture = start_capture("alsa_input.usb-miniDSP_UMIK-1", "/tmp/cap.wav")
    # ... play sweep via signal-gen ...
    stop_capture(capture)
    recording = load_wav("/tmp/cap.wav")
"""

import logging
import os
import signal
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Union

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Default PipeWire source node for the UMIK-1 microphone.
DEFAULT_TARGET = "alsa_input.usb-miniDSP_Umik-1"
SAMPLE_RATE = 48000

# pcm-bridge TCP defaults (local-demo).
_PCM_BRIDGE_HOST = os.environ.get("PI4AUDIO_PCM_BRIDGE_HOST", "127.0.0.1")
_PCM_BRIDGE_PORT = int(os.environ.get("PI4AUDIO_PCM_BRIDGE_PORT", "9090"))
_PCM_BRIDGE_CHANNELS = int(os.environ.get("PI4AUDIO_PCM_CHANNELS", "4"))
# UMIK-1 is channel 3 (zero-indexed = 2) in the pcm-bridge interleaved stream.
_PCM_BRIDGE_UMIK_CHANNEL = int(os.environ.get("PI4AUDIO_PCM_BRIDGE_UMIK_CH", "2"))

# Wire format v2 header size (bytes).
_V2_HEADER_SIZE = 24


class PcmBridgeCapture:
    """Capture audio from pcm-bridge TCP stream (F-235 fallback).

    Reads interleaved PCM from pcm-bridge, extracts a single channel,
    and writes to a WAV file.  Duck-types with subprocess.Popen for
    compatibility with stop_capture().
    """

    def __init__(self, output_path: str, sample_rate: int, channel_index: int,
                 host: str, port: int, total_channels: int):
        self._output_path = output_path
        self._sample_rate = sample_rate
        self._channel_index = channel_index
        self._host = host
        self._port = port
        self._total_channels = total_channels
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._error: Optional[str] = None
        self.returncode: Optional[int] = None
        self.pid = -1

    def start(self) -> None:
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def poll(self) -> Optional[int]:
        if self._thread is not None and not self._thread.is_alive():
            return self.returncode
        return None

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._error:
            logger.warning("pcm-bridge capture error: %s", self._error)

    def _capture_loop(self) -> None:
        samples = []
        sock = None
        try:
            sock = socket.create_connection((self._host, self._port), timeout=5.0)
            sock.settimeout(2.0)
            logger.info("pcm-bridge capture connected to %s:%d (ch=%d)",
                        self._host, self._port, self._channel_index)

            buf = bytearray()
            while not self._stop_event.is_set():
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    break
                buf.extend(data)

                # Parse v2 frames.
                while len(buf) >= _V2_HEADER_SIZE:
                    version = buf[0]
                    if version != 2:
                        del buf[:1]
                        continue
                    frame_count = struct.unpack_from("<I", buf, 4)[0]
                    if frame_count > 8192:
                        del buf[:1]
                        continue
                    msg_size = _V2_HEADER_SIZE + frame_count * self._total_channels * 4
                    if len(buf) < msg_size:
                        break
                    # Extract the target channel from interleaved float32 PCM.
                    pcm_offset = _V2_HEADER_SIZE
                    for f in range(frame_count):
                        sample_offset = pcm_offset + (f * self._total_channels + self._channel_index) * 4
                        val = struct.unpack_from("<f", buf, sample_offset)[0]
                        samples.append(val)
                    del buf[:msg_size]

            # Write captured samples to WAV.
            arr = np.array(samples, dtype=np.float32)
            sf.write(self._output_path, arr, self._sample_rate, format="WAV",
                     subtype="FLOAT")
            logger.info("pcm-bridge capture wrote %d frames to %s",
                        len(arr), self._output_path)
            self.returncode = 0
        except Exception as exc:
            self._error = str(exc)
            logger.error("pcm-bridge capture failed: %s", exc)
            self.returncode = 1
        finally:
            if sock is not None:
                sock.close()


def _pw_record_has_ports() -> bool:
    """Check if pw-record has created input ports (i.e., stream is active)."""
    try:
        result = subprocess.run(
            ["pw-link", "-i"],
            capture_output=True, text=True, timeout=3,
        )
        for line in result.stdout.splitlines():
            if "pw-record" in line or "pw-cat" in line:
                return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False


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


def start_capture(
    output_path: str,
    target: str = DEFAULT_TARGET,
    sample_rate: int = SAMPLE_RATE,
    channels: int = 1,
    pw_record_bin: Optional[str] = None,
) -> Union[subprocess.Popen, PcmBridgeCapture]:
    """Start audio capture from *target*.

    Tries pw-record first (production path).  If pw-record's stream
    fails to activate (no ports after settle time — F-235: WP linking
    policy disabled in local-demo), falls back to capturing from
    pcm-bridge's TCP stream.

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
    subprocess.Popen or PcmBridgeCapture
        The running capture handle.  Call ``stop_capture()`` to stop.
    """
    # Ensure output directory exists.
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Set default source as best-effort hint (works with WP policy.standard).
    _set_default_source(target)

    bin_path = pw_record_bin or "pw-record"
    cmd = [
        bin_path,
        "--target", target,
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
    # Settle time for pw-record to connect to the target node.
    time.sleep(1.0)

    if proc.poll() is not None:
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        raise RuntimeError(
            f"pw-record exited immediately (rc={proc.returncode}): {stderr}"
        )

    # F-235: Check if pw-record actually activated (has ports).
    # In local-demo, WP policy.standard is disabled so pw-record's stream
    # stays suspended with zero ports — it will capture nothing.
    if not _pw_record_has_ports():
        logger.warning(
            "pw-record has no ports (WP linking policy likely disabled). "
            "Falling back to pcm-bridge TCP capture (F-235)."
        )
        # Kill the useless pw-record process.
        proc.kill()
        proc.wait(timeout=2.0)

        # Start pcm-bridge TCP capture instead.
        pcm_cap = PcmBridgeCapture(
            output_path=output_path,
            sample_rate=sample_rate,
            channel_index=_PCM_BRIDGE_UMIK_CHANNEL,
            host=_PCM_BRIDGE_HOST,
            port=_PCM_BRIDGE_PORT,
            total_channels=_PCM_BRIDGE_CHANNELS,
        )
        pcm_cap.start()
        # Brief settle time for TCP connection.
        time.sleep(0.5)
        if pcm_cap.poll() is not None:
            raise RuntimeError(
                f"pcm-bridge capture failed immediately: {pcm_cap._error}"
            )
        logger.info("pcm-bridge capture started (target ch=%d, path=%s)",
                     _PCM_BRIDGE_UMIK_CHANNEL, output_path)
        return pcm_cap

    logger.info("Capture started (pid=%d, target=%s, path=%s)",
                proc.pid, target, output_path)
    return proc


def stop_capture(proc: Union[subprocess.Popen, PcmBridgeCapture],
                 timeout: float = 5.0) -> None:
    """Stop a capture handle (pw-record or pcm-bridge fallback).

    Parameters
    ----------
    proc : subprocess.Popen or PcmBridgeCapture
        The capture handle returned by ``start_capture()``.
    timeout : float
        Seconds to wait for graceful exit before SIGKILL.
    """
    if isinstance(proc, PcmBridgeCapture):
        proc.stop(timeout=timeout)
        return

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
