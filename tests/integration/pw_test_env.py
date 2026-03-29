"""Reusable PipeWire integration test environment (US-075 AC 6).

Wraps the local-demo PipeWire test infrastructure as a parameterizable
Python library. Downstream test suites import this module to get a running
PipeWire environment with the full production-replica audio pipeline.

Usage::

    from pw_test_env import PwTestEnv, PwTestEnvConfig

    config = PwTestEnvConfig(quantum=1024, sample_rate=48000)
    with PwTestEnv(config) as env:
        # env.gm_rpc("get_links") -> dict
        # env.siggen_play(freq=1000, level_dbfs=-20)
        # env.read_levels(port=env.config.level_sw_port) -> dict
        ...

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
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).parent.parent.parent


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

    # Ports (0 = use defaults)
    gm_port: int = 4002
    siggen_port: int = 4001
    level_sw_port: int = 9100
    level_hw_out_port: int = 9101
    level_hw_in_port: int = 9102
    pcm_port: int = 9090

    # Binary paths (None = resolve from env or nix)
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
        # Resolve binary paths from LOCAL_DEMO_* env vars if not set
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


class PwTestEnv:
    """Manages a headless PipeWire test environment with production services.

    Use as a context manager::

        with PwTestEnv(config) as env:
            result = env.gm_rpc({"cmd": "get_links"})
            ...

    Or manually::

        env = PwTestEnv(config)
        env.start()
        try:
            ...
        finally:
            env.stop()
    """

    def __init__(self, config: Optional[PwTestEnvConfig] = None):
        self.config = config or PwTestEnvConfig()
        self._processes: list[subprocess.Popen] = []
        self._pw_started = False
        self._pw_env: dict = {}

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def start(self):
        """Start the PipeWire environment and all configured services."""
        cfg = self.config

        # 1. Generate coefficients if coeff_dir has no WAVs
        coeff_dir = Path(cfg.coeff_dir)
        if not any(coeff_dir.glob("*.wav")):
            self._generate_coeffs(coeff_dir)

        # 2. Install convolver config
        pw_conf_dir = Path("/tmp/pw-test-xdg-config/pipewire/pipewire.conf.d")
        pw_conf_dir.mkdir(parents=True, exist_ok=True)

        convolver_template = Path(cfg.repo_dir) / "configs/local-demo/convolver.conf"
        convolver_conf = convolver_template.read_text().replace(
            "COEFFS_DIR", str(coeff_dir)
        )
        (pw_conf_dir / "30-convolver.conf").write_text(convolver_conf)
        (pw_conf_dir / "30-filter-chain-convolver.conf").unlink(missing_ok=True)

        # Install UMIK-1 loopback config
        umik_src = Path(cfg.repo_dir) / "configs/local-demo/umik1-loopback.conf"
        if umik_src.exists():
            (pw_conf_dir / "35-umik1-loopback.conf").write_text(umik_src.read_text())

        # Install room-sim config if generator exists
        room_sim_gen = Path(cfg.repo_dir) / "scripts/generate-room-sim-ir.py"
        if room_sim_gen.exists() and cfg.python_bin:
            subprocess.run(
                [cfg.python_bin, str(room_sim_gen), str(coeff_dir)],
                capture_output=True,
            )
            room_sim_template = (
                Path(cfg.repo_dir) / "configs/local-demo/room-sim-convolver.conf"
            )
            if room_sim_template.exists():
                room_sim_conf = room_sim_template.read_text().replace(
                    "COEFFS_DIR", str(coeff_dir)
                )
                (pw_conf_dir / "36-room-sim-convolver.conf").write_text(room_sim_conf)

        # 3. Start PipeWire
        subprocess.run(
            [cfg.pw_test_env_script, "stop"],
            capture_output=True,
        )
        subprocess.run(
            [cfg.pw_test_env_script, "start"],
            capture_output=True,
            check=True,
        )
        self._pw_started = True

        # Capture PW environment
        result = subprocess.run(
            [cfg.pw_test_env_script, "env"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("export "):
                parts = line[7:].split("=", 1)
                if len(parts) == 2:
                    key = parts[0]
                    val = parts[1].strip('"')
                    os.environ[key] = val
                    self._pw_env[key] = val
            elif line.startswith("unset "):
                key = line.split()[1].rstrip(";").strip()
                os.environ.pop(key, None)

        # Wait for PipeWire socket
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/tmp/pw-runtime-" + str(os.getuid()))
        for _ in range(20):
            if os.path.exists(os.path.join(runtime_dir, "pipewire-0")):
                break
            time.sleep(0.25)

        # 4. Start services
        if cfg.start_gm and cfg.gm_bin:
            self._start_process(
                [cfg.gm_bin, "--listen", f"tcp:127.0.0.1:{cfg.gm_port}",
                 "--mode", "monitoring", "--log-level", "warn"],
                "graph-manager",
            )
            time.sleep(1)

        if cfg.start_signal_gen and cfg.siggen_bin:
            self._start_process(
                [cfg.siggen_bin, "--managed", "--channels", "1",
                 "--rate", str(cfg.sample_rate),
                 "--listen", f"tcp:127.0.0.1:{cfg.siggen_port}",
                 "--max-level-dbfs", "-20"],
                "signal-gen",
            )
            time.sleep(1)

        if cfg.start_level_bridge and cfg.level_bridge_bin:
            self._start_process(
                [cfg.level_bridge_bin, "--managed",
                 "--node-name", "pi4audio-level-bridge-sw",
                 "--mode", "capture", "--target", "unused-managed-mode",
                 "--levels-listen", f"tcp:0.0.0.0:{cfg.level_sw_port}",
                 "--channels", "8", "--rate", str(cfg.sample_rate)],
                "level-bridge-sw",
            )
            self._start_process(
                [cfg.level_bridge_bin, "--managed",
                 "--node-name", "pi4audio-level-bridge-hw-out",
                 "--mode", "monitor",
                 "--target", "alsa_output.usb-MiniDSP_USBStreamer",
                 "--levels-listen", f"tcp:0.0.0.0:{cfg.level_hw_out_port}",
                 "--channels", "8", "--rate", str(cfg.sample_rate)],
                "level-bridge-hw-out",
            )
            self._start_process(
                [cfg.level_bridge_bin, "--managed",
                 "--node-name", "pi4audio-level-bridge-hw-in",
                 "--mode", "capture",
                 "--target", "alsa_input.usb-MiniDSP_USBStreamer",
                 "--levels-listen", f"tcp:0.0.0.0:{cfg.level_hw_in_port}",
                 "--channels", "8", "--rate", str(cfg.sample_rate)],
                "level-bridge-hw-in",
            )
            time.sleep(0.5)

        if cfg.start_pcm_bridge and cfg.pcm_bridge_bin:
            self._start_process(
                [cfg.pcm_bridge_bin, "--managed", "--mode", "monitor",
                 "--listen", f"tcp:0.0.0.0:{cfg.pcm_port}",
                 "--channels", "4", "--rate", str(cfg.sample_rate)],
                "pcm-bridge",
            )
            time.sleep(1)

        # Allow GM reconciliation
        time.sleep(2)

    def stop(self):
        """Stop all services and PipeWire."""
        for proc in reversed(self._processes):
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
        time.sleep(0.3)
        for proc in reversed(self._processes):
            if proc.poll() is None:
                proc.kill()
        for proc in self._processes:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        self._processes.clear()

        if self._pw_started:
            subprocess.run(
                [self.config.pw_test_env_script, "stop"],
                capture_output=True,
            )
            self._pw_started = False

    def gm_rpc(self, cmd: dict) -> dict:
        """Send an RPC command to GraphManager and return the response."""
        return _rpc_call("127.0.0.1", self.config.gm_port, cmd)

    def siggen_rpc(self, cmd: dict) -> dict:
        """Send an RPC command to signal-gen and return the response."""
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

    def _start_process(self, args: list[str], name: str):
        """Start a subprocess and track it."""
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.1)
        if proc.poll() is not None:
            raise RuntimeError(f"{name} exited immediately (code {proc.returncode})")
        self._processes.append(proc)

    def _generate_coeffs(self, coeff_dir: Path):
        """Generate Dirac impulse coefficient WAVs."""
        gen_script = Path(self.config.repo_dir) / "scripts/generate-dirac-coeffs.py"
        if gen_script.exists() and self.config.python_bin:
            subprocess.run(
                [self.config.python_bin, str(gen_script), str(coeff_dir)],
                capture_output=True,
                check=True,
            )
