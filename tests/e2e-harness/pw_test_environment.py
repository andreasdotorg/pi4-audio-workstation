"""Production-replica PipeWire test environment (US-075 AC 6).

Provides a context manager that starts the full local-demo stack (PipeWire,
WirePlumber, GraphManager, signal-gen, level-bridge x3, pcm-bridge, web-ui)
using ``local-demo.sh start`` and tears it down with ``local-demo.sh stop``.

Usage::

    from tests.e2e_harness.pw_test_environment import pw_test_environment

    with pw_test_environment() as env:
        env.set_mode("measurement")
        env.siggen_play(freq=1000, level_dbfs=-20)
        levels = env.read_levels()
        links = env.get_links()

The room correction pipeline can swap coefficient files by setting coeff_dir
to a directory containing replacement WAV files (e.g., simulated room IRs
from US-067) without any code changes.
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

    # Ports (match local-demo.sh defaults)
    gm_port: int = 4002
    siggen_port: int = 4001
    level_sw_port: int = 9100
    level_hw_out_port: int = 9101
    level_hw_in_port: int = 9102
    pcm_port: int = 9090

    # Path to local-demo.sh
    local_demo_script: Optional[str] = None

    def __post_init__(self):
        if self.local_demo_script is None:
            self.local_demo_script = str(
                _PROJECT_ROOT / "scripts" / "local-demo.sh"
            )


class PwTestEnv:
    """Running production-replica PipeWire environment with RPC helpers.

    Returned by ``pw_test_environment()``. Do not instantiate directly.
    """

    def __init__(self, config: PwTestEnvConfig):
        self.config = config

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


@contextmanager
def pw_test_environment(
    gm_port: int = 4002,
    siggen_port: int = 4001,
    level_sw_port: int = 9100,
    level_hw_out_port: int = 9101,
    level_hw_in_port: int = 9102,
    pcm_port: int = 9090,
):
    """Start the full local-demo stack and yield a PwTestEnv.

    Uses ``local-demo.sh start`` for startup and ``local-demo.sh stop``
    for teardown. Always brings up the complete production-replica stack.

    Example::

        with pw_test_environment() as env:
            env.set_mode("measurement")
            env.siggen_play(freq=1000)
            levels = env.read_levels()
    """
    cfg = PwTestEnvConfig(
        gm_port=gm_port,
        siggen_port=siggen_port,
        level_sw_port=level_sw_port,
        level_hw_out_port=level_hw_out_port,
        level_hw_in_port=level_hw_in_port,
        pcm_port=pcm_port,
    )

    script = cfg.local_demo_script

    # Stop any previous instance
    subprocess.run([script, "stop"], capture_output=True)

    # Start the full stack
    result = subprocess.run(
        [script, "start"], capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"local-demo.sh start failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    # Capture PW environment variables for this process
    env_result = subprocess.run(
        [script, "env"], capture_output=True, text=True,
    )
    for line in env_result.stdout.splitlines():
        line = line.strip()
        if line.startswith("export "):
            parts = line[7:].split("=", 1)
            if len(parts) == 2:
                os.environ[parts[0]] = parts[1].strip('"')
        elif line.startswith("unset "):
            os.environ.pop(line.split()[1].rstrip(";").strip(), None)

    try:
        yield PwTestEnv(cfg)
    finally:
        subprocess.run([script, "stop"], capture_output=True)
