"""Production-replica PipeWire test environment (US-075 AC 6).

Provides a context manager that starts a headless PipeWire instance with the
full production-replica audio pipeline: GraphManager, signal-gen, level-bridge
(3 instances), and pcm-bridge. Uses ``local-pw-test-env.sh`` for PipeWire
isolation and ``ManagedProcess`` from the e2e-harness for subprocess lifecycle.

Usage::

    from tests.e2e_harness.pw_test_environment import pw_test_environment

    with pw_test_environment(quantum=1024, coeff_dir="tests/fixtures/coeffs") as env:
        env.set_mode("measurement")
        env.siggen_play(freq=1000, level_dbfs=-20)
        levels = env.read_levels()
        links = env.get_links()

Configuration is parameterizable:
- quantum: PipeWire graph quantum (default 1024)
- sample_rate: audio sample rate (default 48000)
- coeff_dir: path to FIR coefficient WAVs (default: tests/fixtures/coeffs)
- services: which services to start (default: all)
- ports: RPC/TCP ports (default: standard local-demo ports)

The room correction pipeline can swap coefficient files by passing a custom
coeff_dir containing replacement WAV files (e.g., simulated room IRs from
US-067) without any code changes.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .process_manager import ManagedProcess, _check_graphmgr_rpc

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _rpc_call(host: str, port: int, cmd: dict, timeout: float = 5.0) -> dict:
    """Send a JSON RPC command and return the parsed response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.sendall((json.dumps(cmd) + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        if data:
            return json.loads(data.split(b"\n")[0])
        return {}
    finally:
        sock.close()


def _read_level_snapshot(host: str, port: int, timeout: float = 5.0) -> dict:
    """Read one JSON level snapshot from a level-bridge TCP port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        if data:
            return json.loads(data.split(b"\n")[0])
        return {}
    finally:
        sock.close()


@dataclass
class PwTestEnvConfig:
    """Configuration for the PipeWire test environment."""

    quantum: int = 1024
    sample_rate: int = 48000
    coeff_dir: Optional[str] = None
    repo_dir: Optional[str] = None

    # Service subset control
    start_gm: bool = True
    start_signal_gen: bool = True
    start_level_bridge: bool = True
    start_pcm_bridge: bool = True

    # Ports
    gm_port: int = 4002
    siggen_port: int = 4001
    level_sw_port: int = 9100
    level_hw_out_port: int = 9101
    level_hw_in_port: int = 9102
    pcm_port: int = 9090

    # Binary paths (None = resolve from LOCAL_DEMO_* env vars)
    gm_bin: Optional[str] = None
    siggen_bin: Optional[str] = None
    level_bridge_bin: Optional[str] = None
    pcm_bridge_bin: Optional[str] = None
    python_bin: Optional[str] = None
    pw_test_env_script: Optional[str] = None

    def __post_init__(self):
        if self.repo_dir is None:
            self.repo_dir = str(_PROJECT_ROOT)
        if self.coeff_dir is None:
            self.coeff_dir = str(_PROJECT_ROOT / "tests" / "fixtures" / "coeffs")
        if self.pw_test_env_script is None:
            self.pw_test_env_script = str(
                _PROJECT_ROOT / "scripts" / "local-pw-test-env.sh"
            )
        if self.gm_bin is None:
            self.gm_bin = os.environ.get("LOCAL_DEMO_GM_BIN")
        if self.siggen_bin is None:
            self.siggen_bin = os.environ.get("LOCAL_DEMO_SG_BIN")
        if self.level_bridge_bin is None:
            self.level_bridge_bin = os.environ.get("LOCAL_DEMO_LB_BIN")
        if self.pcm_bridge_bin is None:
            self.pcm_bridge_bin = os.environ.get("LOCAL_DEMO_PCM_BIN")
        if self.python_bin is None:
            self.python_bin = os.environ.get("LOCAL_DEMO_PYTHON", "python")


class PwTestEnv:
    """Running production-replica PipeWire environment with RPC helpers.

    Returned by ``pw_test_environment()``. Do not instantiate directly.
    """

    def __init__(self, config: PwTestEnvConfig, processes: list):
        self.config = config
        self._processes = processes

    def gm_rpc(self, cmd: dict) -> dict:
        """Send an RPC command to GraphManager."""
        return _rpc_call("127.0.0.1", self.config.gm_port, cmd)

    def siggen_rpc(self, cmd: dict) -> dict:
        """Send an RPC command to signal-gen."""
        return _rpc_call("127.0.0.1", self.config.siggen_port, cmd)

    def siggen_play(
        self,
        freq: float = 1000.0,
        level_dbfs: float = -20.0,
        channels: Optional[list[int]] = None,
    ) -> dict:
        """Command signal-gen to play a sine tone."""
        if channels is None:
            channels = [1]
        return self.siggen_rpc({
            "cmd": "play",
            "signal": "sine",
            "freq": freq,
            "level_dbfs": level_dbfs,
            "channels": channels,
        })

    def siggen_stop(self) -> dict:
        """Command signal-gen to stop playing."""
        return self.siggen_rpc({"cmd": "stop"})

    def set_mode(self, mode: str) -> dict:
        """Switch GM operating mode."""
        return self.gm_rpc({"cmd": "set_mode", "mode": mode})

    def get_links(self) -> dict:
        """Query GM link topology."""
        return self.gm_rpc({"cmd": "get_links"})

    def get_graph_info(self) -> dict:
        """Query GM graph metadata (quantum, sample_rate, xruns)."""
        return self.gm_rpc({"cmd": "get_graph_info"})

    def read_levels(self, port: Optional[int] = None) -> dict:
        """Read one level snapshot from a level-bridge TCP port."""
        if port is None:
            port = self.config.level_sw_port
        return _read_level_snapshot("127.0.0.1", port)


def _check_tcp_connectable(host, port):
    """Health check: TCP port is accepting connections."""
    def check():
        try:
            sock = socket.create_connection((host, port), timeout=2.0)
            sock.close()
            return True
        except OSError:
            return False
    return check


@contextmanager
def pw_test_environment(
    quantum: int = 1024,
    sample_rate: int = 48000,
    coeff_dir: Optional[str] = None,
    start_gm: bool = True,
    start_signal_gen: bool = True,
    start_level_bridge: bool = True,
    start_pcm_bridge: bool = True,
    gm_port: int = 4002,
    siggen_port: int = 4001,
    level_sw_port: int = 9100,
    level_hw_out_port: int = 9101,
    level_hw_in_port: int = 9102,
    pcm_port: int = 9090,
):
    """Start a production-replica PipeWire environment and yield a PwTestEnv.

    Uses ``local-pw-test-env.sh`` for headless PipeWire isolation, then starts
    services using ManagedProcess for proper health checks and shutdown.

    Example::

        with pw_test_environment(quantum=1024) as env:
            env.set_mode("measurement")
            env.siggen_play(freq=1000)
            levels = env.read_levels()
    """
    cfg = PwTestEnvConfig(
        quantum=quantum,
        sample_rate=sample_rate,
        coeff_dir=coeff_dir,
        start_gm=start_gm,
        start_signal_gen=start_signal_gen,
        start_level_bridge=start_level_bridge,
        start_pcm_bridge=start_pcm_bridge,
        gm_port=gm_port,
        siggen_port=siggen_port,
        level_sw_port=level_sw_port,
        level_hw_out_port=level_hw_out_port,
        level_hw_in_port=level_hw_in_port,
        pcm_port=pcm_port,
    )

    # 1. Generate coefficients if coeff_dir has no WAVs
    coeff_path = Path(cfg.coeff_dir)
    if not any(coeff_path.glob("*.wav")):
        gen_script = Path(cfg.repo_dir) / "scripts/generate-dirac-coeffs.py"
        if gen_script.exists() and cfg.python_bin:
            subprocess.run(
                [cfg.python_bin, str(gen_script), str(coeff_path)],
                capture_output=True, check=True,
            )

    # 2. Install convolver and loopback configs
    pw_conf_dir = Path("/tmp/pw-test-xdg-config/pipewire/pipewire.conf.d")
    pw_conf_dir.mkdir(parents=True, exist_ok=True)

    convolver_template = Path(cfg.repo_dir) / "configs/local-demo/convolver.conf"
    (pw_conf_dir / "30-convolver.conf").write_text(
        convolver_template.read_text().replace("COEFFS_DIR", str(coeff_path))
    )
    (pw_conf_dir / "30-filter-chain-convolver.conf").unlink(missing_ok=True)

    umik_src = Path(cfg.repo_dir) / "configs/local-demo/umik1-loopback.conf"
    if umik_src.exists():
        (pw_conf_dir / "35-umik1-loopback.conf").write_text(umik_src.read_text())

    room_sim_gen = Path(cfg.repo_dir) / "scripts/generate-room-sim-ir.py"
    if room_sim_gen.exists() and cfg.python_bin:
        subprocess.run(
            [cfg.python_bin, str(room_sim_gen), str(coeff_path)],
            capture_output=True,
        )
        room_sim_template = (
            Path(cfg.repo_dir) / "configs/local-demo/room-sim-convolver.conf"
        )
        if room_sim_template.exists():
            (pw_conf_dir / "36-room-sim-convolver.conf").write_text(
                room_sim_template.read_text().replace("COEFFS_DIR", str(coeff_path))
            )

    # 3. Start PipeWire via local-pw-test-env.sh
    subprocess.run([cfg.pw_test_env_script, "stop"], capture_output=True)
    subprocess.run(
        [cfg.pw_test_env_script, "start"], capture_output=True, check=True,
    )
    pw_started = True

    # Capture PW environment variables
    result = subprocess.run(
        [cfg.pw_test_env_script, "env"], capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("export "):
            parts = line[7:].split("=", 1)
            if len(parts) == 2:
                os.environ[parts[0]] = parts[1].strip('"')
        elif line.startswith("unset "):
            os.environ.pop(line.split()[1].rstrip(";").strip(), None)

    # Wait for PipeWire socket
    runtime_dir = os.environ.get(
        "XDG_RUNTIME_DIR", "/tmp/pw-runtime-" + str(os.getuid())
    )
    for _ in range(20):
        if os.path.exists(os.path.join(runtime_dir, "pipewire-0")):
            break
        time.sleep(0.25)

    # 4. Build and start service processes using ManagedProcess
    processes = []
    started = []
    try:
        if cfg.start_gm and cfg.gm_bin:
            gm = ManagedProcess(
                name="graph-manager",
                args=[
                    cfg.gm_bin, "--listen", f"tcp:127.0.0.1:{cfg.gm_port}",
                    "--mode", "monitoring", "--log-level", "warn",
                ],
                health_check=_check_graphmgr_rpc("127.0.0.1", cfg.gm_port),
                startup_timeout=5.0,
            )
            processes.append(gm)

        if cfg.start_signal_gen and cfg.siggen_bin:
            sg = ManagedProcess(
                name="signal-gen",
                args=[
                    cfg.siggen_bin, "--managed", "--channels", "1",
                    "--rate", str(cfg.sample_rate),
                    "--listen", f"tcp:127.0.0.1:{cfg.siggen_port}",
                    "--max-level-dbfs", "-20",
                ],
                startup_timeout=5.0,
            )
            processes.append(sg)

        if cfg.start_level_bridge and cfg.level_bridge_bin:
            for name, node_name, mode, target, port in [
                ("level-bridge-sw", "pi4audio-level-bridge-sw",
                 "capture", "unused-managed-mode", cfg.level_sw_port),
                ("level-bridge-hw-out", "pi4audio-level-bridge-hw-out",
                 "monitor", "alsa_output.usb-MiniDSP_USBStreamer",
                 cfg.level_hw_out_port),
                ("level-bridge-hw-in", "pi4audio-level-bridge-hw-in",
                 "capture", "alsa_input.usb-MiniDSP_USBStreamer",
                 cfg.level_hw_in_port),
            ]:
                lb = ManagedProcess(
                    name=name,
                    args=[
                        cfg.level_bridge_bin, "--managed",
                        "--node-name", node_name,
                        "--mode", mode, "--target", target,
                        "--levels-listen", f"tcp:0.0.0.0:{port}",
                        "--channels", "8", "--rate", str(cfg.sample_rate),
                    ],
                    startup_timeout=3.0,
                )
                processes.append(lb)

        if cfg.start_pcm_bridge and cfg.pcm_bridge_bin:
            pcm = ManagedProcess(
                name="pcm-bridge",
                args=[
                    cfg.pcm_bridge_bin, "--managed", "--mode", "monitor",
                    "--listen", f"tcp:0.0.0.0:{cfg.pcm_port}",
                    "--channels", "4", "--rate", str(cfg.sample_rate),
                ],
                startup_timeout=5.0,
            )
            processes.append(pcm)

        # Start all in order with rollback on failure
        for proc in processes:
            proc.start()
            started.append(proc)

        # Allow GM reconciliation
        time.sleep(2)

        yield PwTestEnv(cfg, processes)

    except Exception:
        # Rollback: stop everything started so far
        for p in reversed(started):
            try:
                p.stop()
            except Exception:
                pass
        raise
    finally:
        # Teardown: stop services in reverse order
        for proc in reversed(processes):
            try:
                proc.stop()
            except Exception:
                pass

        if pw_started:
            subprocess.run(
                [cfg.pw_test_env_script, "stop"], capture_output=True,
            )
