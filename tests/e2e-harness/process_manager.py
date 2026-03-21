"""E2E harness process manager — subprocess lifecycle for integration tests.

Manages PipeWire, PW filter-chain convolver, GraphManager, pw-filter-chain
(room simulator), and the RT signal generator as subprocesses.  Starts in
dependency order, tears down in reverse.  Uses SIGTERM with a timeout,
falling back to SIGKILL.

D-040 adaptation: CamillaDSP replaced by PW filter-chain convolver +
GraphManager.  The convolver is a PipeWire module loaded by pw-filter-chain.
GraphManager manages link topology and mode state via TCP RPC.

Designed for the US-050 E2E test harness.  All processes run in a private
PipeWire instance (not the user session) so tests are isolated.

Usage::

    pm = ProcessManager(
        convolver_config="tests/e2e-harness/e2e-convolver.conf",
        graphmgr_bin="pi4audio-graph-manager",
        room_sim_script="tests/e2e-harness/start-room-sim.sh",
        siggen_bin="pi4audio-signal-gen",
    )
    pm.start_all()
    try:
        ...  # run tests
    finally:
        pm.stop_all()
"""

import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import time

log = logging.getLogger(__name__)

# Startup timeouts (seconds)
PIPEWIRE_STARTUP_TIMEOUT = 5.0
CONVOLVER_STARTUP_TIMEOUT = 5.0
GRAPHMGR_STARTUP_TIMEOUT = 5.0
ROOM_SIM_STARTUP_TIMEOUT = 3.0
SIGGEN_STARTUP_TIMEOUT = 5.0

# Shutdown
SIGTERM_TIMEOUT = 3.0
SIGKILL_TIMEOUT = 2.0

# GraphManager default RPC port for E2E harness (distinct from production 4002)
GRAPHMGR_E2E_PORT = 14002
GRAPHMGR_E2E_HOST = "127.0.0.1"


class ProcessError(Exception):
    """Raised when a managed process fails to start or dies unexpectedly."""


class ManagedProcess:
    """Wrapper around a subprocess with health-check and graceful shutdown."""

    def __init__(self, name, args, env=None, health_check=None,
                 startup_timeout=5.0):
        self.name = name
        self.args = args
        self.env = env
        self.health_check = health_check
        self.startup_timeout = startup_timeout
        self._proc = None

    @property
    def pid(self):
        return self._proc.pid if self._proc else None

    @property
    def running(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        """Start the subprocess and wait for it to become healthy."""
        log.info("Starting %s: %s", self.name, " ".join(self.args))
        self._proc = subprocess.Popen(
            self.args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
        )

        # Check it didn't exit immediately
        time.sleep(0.1)
        if self._proc.poll() is not None:
            _, stderr = self._proc.communicate(timeout=2)
            stderr_text = stderr.decode("utf-8", errors="replace")[:500]
            raise ProcessError(
                f"{self.name} exited immediately (code {self._proc.returncode}). "
                f"stderr: {stderr_text}"
            )

        # Run health check if provided
        if self.health_check is not None:
            deadline = time.monotonic() + self.startup_timeout
            last_err = None
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    _, stderr = self._proc.communicate(timeout=2)
                    stderr_text = stderr.decode("utf-8", errors="replace")[:500]
                    raise ProcessError(
                        f"{self.name} died during startup "
                        f"(code {self._proc.returncode}). stderr: {stderr_text}"
                    )
                try:
                    if self.health_check():
                        log.info("%s healthy (pid %d)", self.name, self._proc.pid)
                        return
                except Exception as e:
                    last_err = e
                time.sleep(0.1)
            raise ProcessError(
                f"{self.name} failed health check within "
                f"{self.startup_timeout}s: {last_err}"
            )

        log.info("%s started (pid %d)", self.name, self._proc.pid)

    def stop(self):
        """Stop the subprocess: SIGTERM, then SIGKILL if needed."""
        if self._proc is None or self._proc.poll() is not None:
            return

        log.info("Stopping %s (pid %d) with SIGTERM", self.name, self._proc.pid)
        self._proc.send_signal(signal.SIGTERM)
        try:
            self._proc.wait(timeout=SIGTERM_TIMEOUT)
            log.info("%s terminated (code %d)", self.name, self._proc.returncode)
            return
        except subprocess.TimeoutExpired:
            pass

        log.warning(
            "%s did not exit after SIGTERM (%.1fs), sending SIGKILL",
            self.name, SIGTERM_TIMEOUT,
        )
        self._proc.kill()
        try:
            self._proc.wait(timeout=SIGKILL_TIMEOUT)
        except subprocess.TimeoutExpired:
            log.error("%s did not exit after SIGKILL", self.name)

    def collect_output(self):
        """Collect stdout/stderr from the process (non-blocking)."""
        if self._proc is None:
            return "", ""
        try:
            stdout, stderr = self._proc.communicate(timeout=1)
            return (
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except (subprocess.TimeoutExpired, ValueError):
            return "", ""


def _check_pw_node_exists(node_name):
    """Health check: a PipeWire node with the given name is registered."""
    def check():
        result = subprocess.run(
            ["pw-cli", "ls", "Node"],
            capture_output=True, text=True, timeout=5,
        )
        return node_name in result.stdout
    return check


def _check_graphmgr_rpc(host, port):
    """Health check: GraphManager TCP RPC responds to ping."""
    def check():
        sock = socket.create_connection((host, port), timeout=2.0)
        try:
            sock.settimeout(2.0)
            sock.sendall(b'{"cmd":"ping"}\n')
            data = b""
            while b"\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    return False
                data += chunk
            resp = json.loads(data.split(b"\n")[0])
            return resp.get("ok", False)
        finally:
            sock.close()
    return check


def _check_process_alive(proc_ref):
    """Health check: process is still running (no immediate crash)."""
    def check():
        return proc_ref.running
    return check


class ProcessManager:
    """Manages E2E harness subprocesses in dependency order.

    Start order: PipeWire -> PW convolver -> GraphManager -> room sim -> signal gen.
    Stop order:  signal gen -> room sim -> GraphManager -> PW convolver -> PipeWire.

    Parameters
    ----------
    pipewire_bin : str or None
        Path to ``pipewire`` binary.  If None, PipeWire management is
        skipped (assumes an external PipeWire instance is running).
    convolver_config : str
        Path to the PW filter-chain convolver config file (e2e-convolver.conf).
    graphmgr_bin : str or None
        Path to the ``pi4audio-graph-manager`` binary.  If None, GraphManager
        management is skipped.
    graphmgr_port : int
        TCP RPC port for GraphManager.
    room_sim_script : str or None
        Path to the room simulator start script (EH-2).  If None,
        room simulator management is skipped.
    room_sim_ir_dir : str or None
        Directory containing exported room IR WAV files (EH-1).
        Passed to the room simulator script.
    siggen_bin : str or None
        Path to the signal generator binary.  If None, signal gen
        management is skipped.
    siggen_port : int
        RPC port for the signal generator.
    env_overrides : dict or None
        Extra environment variables merged into each subprocess env.
        Use for ``PIPEWIRE_RUNTIME_DIR``, ``XDG_RUNTIME_DIR``, etc.
    """

    def __init__(
        self,
        pipewire_bin=None,
        convolver_config="tests/e2e-harness/e2e-convolver.conf",
        graphmgr_bin=None,
        graphmgr_port=GRAPHMGR_E2E_PORT,
        room_sim_script=None,
        room_sim_ir_dir=None,
        siggen_bin=None,
        siggen_port=9877,
        env_overrides=None,
    ):
        self._env = {**os.environ, **(env_overrides or {})}
        self._processes = []  # ordered list for teardown
        self._graphmgr_port = graphmgr_port

        # 1. PipeWire (optional -- skip if using external instance)
        if pipewire_bin:
            pw = ManagedProcess(
                name="pipewire",
                args=[pipewire_bin],
                env=self._env,
                startup_timeout=PIPEWIRE_STARTUP_TIMEOUT,
            )
            self._processes.append(pw)

        # 2. PW filter-chain convolver
        pw_filter_chain_bin = shutil.which("pw-filter-chain") or "pw-filter-chain"
        if os.path.isfile(convolver_config):
            convolver = ManagedProcess(
                name="convolver",
                args=[
                    pw_filter_chain_bin,
                    "--properties={ log.level = 2 }",
                    convolver_config,
                ],
                env=self._env,
                health_check=_check_pw_node_exists("pi4audio-e2e-convolver"),
                startup_timeout=CONVOLVER_STARTUP_TIMEOUT,
            )
            self._processes.append(convolver)

        # 3. GraphManager (optional)
        if graphmgr_bin:
            gm = ManagedProcess(
                name="graph-manager",
                args=[
                    graphmgr_bin,
                    "--mode", "monitoring",
                    "--listen", f"tcp:{GRAPHMGR_E2E_HOST}:{graphmgr_port}",
                    "--log-level", "debug",
                ],
                env=self._env,
                health_check=_check_graphmgr_rpc(
                    GRAPHMGR_E2E_HOST, graphmgr_port,
                ),
                startup_timeout=GRAPHMGR_STARTUP_TIMEOUT,
            )
            self._processes.append(gm)

        # 4. Room simulator (optional -- EH-2)
        if room_sim_script:
            room_args = [room_sim_script]
            if room_sim_ir_dir:
                room_args.append(room_sim_ir_dir)
            room = ManagedProcess(
                name="room-simulator",
                args=room_args,
                env=self._env,
                startup_timeout=ROOM_SIM_STARTUP_TIMEOUT,
            )
            self._processes.append(room)

        # 5. Signal generator (optional)
        if siggen_bin:
            sg = ManagedProcess(
                name="signal-gen",
                args=[
                    siggen_bin,
                    "--port", str(siggen_port),
                ],
                env=self._env,
                startup_timeout=SIGGEN_STARTUP_TIMEOUT,
            )
            self._processes.append(sg)

    @property
    def graphmgr_port(self):
        return self._graphmgr_port

    def start_all(self):
        """Start all managed processes in dependency order.

        If any process fails to start, all previously started processes
        are torn down before re-raising the error.
        """
        started = []
        try:
            for proc in self._processes:
                proc.start()
                started.append(proc)
        except Exception:
            log.error("Startup failed at %s, tearing down", proc.name)
            for p in reversed(started):
                try:
                    p.stop()
                except Exception as e:
                    log.warning("Error stopping %s during rollback: %s",
                                p.name, e)
            raise

    def stop_all(self):
        """Stop all managed processes in reverse dependency order."""
        for proc in reversed(self._processes):
            try:
                proc.stop()
            except Exception as e:
                log.warning("Error stopping %s: %s", proc.name, e)

    def check_health(self):
        """Check that all managed processes are still running.

        Returns a dict mapping process name to running status.
        """
        return {proc.name: proc.running for proc in self._processes}

    def get_process(self, name):
        """Get a ManagedProcess by name, or None."""
        for proc in self._processes:
            if proc.name == name:
                return proc
        return None

    def collect_all_output(self):
        """Collect stdout/stderr from all stopped processes.

        Returns a dict mapping process name to (stdout, stderr) tuples.
        Useful for diagnostics after test failure.
        """
        return {
            proc.name: proc.collect_output()
            for proc in self._processes
            if not proc.running
        }
