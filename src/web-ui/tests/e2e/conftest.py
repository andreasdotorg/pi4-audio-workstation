"""E2E test fixtures — real stack, no mocks.

Tests in this directory run against the real local-demo stack:
PipeWire + GraphManager + signal-gen + pcm-bridge + level-bridge + web UI.
Only physical audio hardware (USBStreamer, speakers) is absent — replaced
by a null ALSA sink.

The stack is started by the test-e2e shell wrapper (scripts/test-e2e.sh)
BEFORE pytest is invoked.  The conftest does NOT start the stack itself;
it waits for it to be reachable and provides fixtures pointing at the
live server.

Environment variables:
    LOCAL_DEMO_URL   — base URL of the running web UI (default: http://localhost:8080)
    PI_AUDIO_BACKEND — backend tier: mock | local-demo | pi-loopback | pi-full
                       (default: local-demo)
    GM_PORT          — GraphManager RPC port (default: 4002)
    SIGGEN_PORT      — signal-gen RPC port (default: 4001)
"""

import json
import os
import socket
import struct
import time
import urllib.request
import urllib.error

import pytest


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOCAL_DEMO_URL = os.environ.get("LOCAL_DEMO_URL", "http://localhost:8080")
STACK_TIMEOUT = int(os.environ.get("E2E_STACK_TIMEOUT", "30"))
BACKEND_TYPE = os.environ.get("PI_AUDIO_BACKEND", "local-demo")

GM_PORT = int(os.environ.get("GM_PORT", "4002"))
SIGGEN_PORT = int(os.environ.get("SIGGEN_PORT", "4001"))
LEVEL_SW_PORT = int(os.environ.get("LEVEL_SW_PORT", "9100"))
LEVEL_HW_OUT_PORT = int(os.environ.get("LEVEL_HW_OUT_PORT", "9101"))
PCM_PORT = int(os.environ.get("PCM_PORT", "9090"))


# ---------------------------------------------------------------------------
# Stack reachability
# ---------------------------------------------------------------------------

def _is_reachable(url: str, timeout: float = 2.0) -> bool:
    """Check if the web UI responds to a simple GET."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except (urllib.error.URLError, OSError):
        return False


def _wait_for_stack(url: str, timeout: int) -> bool:
    """Wait until the web UI is reachable or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_reachable(url):
            return True
        time.sleep(1)
    return False


def _check_pw_available() -> bool:
    """Check if PipeWire is running (pw-cli info succeeds)."""
    import subprocess
    try:
        result = subprocess.run(
            ["pw-cli", "info", "0"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Marker registration and collection hooks
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: real-stack end-to-end test")
    config.addinivalue_line("markers", "destructive: tests that modify Pi state")
    config.addinivalue_line("markers", "slow: tests exceeding 10 s")


def pytest_addoption(parser):
    parser.addoption(
        "--destructive",
        action="store_true",
        default=False,
        help="Allow tests marked @pytest.mark.destructive",
    )
    parser.addoption(
        "--loopback-confirmed",
        action="store_true",
        default=False,
        help="Attest that physical loopback cables are connected (pi-loopback tier)",
    )
    parser.addoption(
        "--owner-confirmed",
        action="store_true",
        default=False,
        help="Attest that speakers are safe (pi-full tier)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests based on available infrastructure and CLI flags."""
    pw_available = _check_pw_available()
    owner_confirmed = config.getoption("--owner-confirmed", default=False)

    # Skip all E2E tests if the local-demo stack is not reachable
    if not _is_reachable(LOCAL_DEMO_URL):
        if not _wait_for_stack(LOCAL_DEMO_URL, STACK_TIMEOUT):
            skip = pytest.mark.skip(
                reason=f"local-demo stack not reachable at {LOCAL_DEMO_URL}"
            )
            for item in items:
                item.add_marker(skip)
            return

    # Skip destructive tests unless --destructive is passed
    if not config.getoption("--destructive", default=False):
        skip_destructive = pytest.mark.skip(reason="requires --destructive flag")
        for item in items:
            if "destructive" in item.keywords:
                item.add_marker(skip_destructive)

    # Tier-based skipping
    for item in items:
        if "needs_pw" in item.keywords and not pw_available:
            item.add_marker(pytest.mark.skip(reason="No PipeWire available"))
        if "needs_usb_audio" in item.keywords:
            # USB audio detection would go here; for now always skip
            if BACKEND_TYPE not in ("pi-loopback", "pi-full"):
                item.add_marker(pytest.mark.skip(reason="No USB audio device"))
        if "needs_acoustic" in item.keywords and not owner_confirmed:
            item.add_marker(pytest.mark.skip(reason="Requires --owner-confirmed"))
        if "audio_producing" in item.keywords and not owner_confirmed:
            item.add_marker(pytest.mark.skip(reason="audio_producing requires --owner-confirmed"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def backend_type() -> str:
    """Return the current backend tier."""
    return BACKEND_TYPE


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL of the running local-demo web UI."""
    return LOCAL_DEMO_URL


@pytest.fixture(scope="session")
def gm_port() -> int:
    """GraphManager RPC port."""
    return GM_PORT


@pytest.fixture(scope="session")
def siggen_port() -> int:
    """signal-gen RPC port."""
    return SIGGEN_PORT


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _api_get(base_url: str, path: str, timeout: float = 10.0):
    """GET a JSON endpoint and return (status_code, parsed_body)."""
    try:
        resp = urllib.request.urlopen(f"{base_url}{path}", timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read()) if exc.read() else {}


def _api_post(base_url: str, path: str, body: dict | None = None, timeout: float = 10.0):
    """POST to a JSON endpoint, return (status_code, parsed_body)."""
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read()) if exc.read() else {}


@pytest.fixture(scope="session")
def api_get(base_url):
    """Fixture returning a GET helper bound to the live server."""
    def _get(path: str, timeout: float = 10.0):
        return _api_get(base_url, path, timeout)
    return _get


@pytest.fixture(scope="session")
def api_post(base_url):
    """Fixture returning a POST helper bound to the live server."""
    def _post(path: str, body: dict | None = None, timeout: float = 10.0):
        return _api_post(base_url, path, body, timeout)
    return _post


# ---------------------------------------------------------------------------
# TCP RPC helper (GraphManager, signal-gen)
# ---------------------------------------------------------------------------

def _rpc_call(host: str, port: int, cmd: dict, timeout: float = 5.0) -> dict:
    """Send a JSON RPC command over TCP and return the parsed response."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.settimeout(timeout)
        s.sendall((json.dumps(cmd) + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        return json.loads(data.decode().strip())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


@pytest.fixture(scope="session")
def rpc_call():
    """Fixture returning a TCP RPC helper."""
    return _rpc_call


# ---------------------------------------------------------------------------
# Level-bridge TCP helper
# ---------------------------------------------------------------------------

def _read_levels(port: int, count: int = 1, timeout: float = 5.0) -> list[dict]:
    """Read JSON lines from a level-bridge TCP port."""
    results = []
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        s.settimeout(timeout)
        buf = b""
        while len(results) < count:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    results.append(json.loads(line.decode()))
        s.close()
    except (OSError, json.JSONDecodeError):
        pass
    return results


@pytest.fixture(scope="session")
def read_levels():
    """Fixture returning a level-bridge TCP reader."""
    return _read_levels


# ---------------------------------------------------------------------------
# pcm-bridge binary reader
# ---------------------------------------------------------------------------

def _read_pcm_header(port: int, timeout: float = 5.0) -> dict | None:
    """Read one v2 binary frame header from pcm-bridge."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        s.settimeout(timeout)
    except OSError:
        return None

    for _ in range(10):
        buf = b""
        while len(buf) < 24:
            try:
                chunk = s.recv(24 - len(buf))
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk

        if len(buf) < 24:
            continue

        version = buf[0]
        frame_count = struct.unpack_from("<I", buf, 4)[0]
        graph_pos = struct.unpack_from("<Q", buf, 8)[0]
        graph_nsec = struct.unpack_from("<Q", buf, 16)[0]

        # Drain the payload
        if frame_count > 0:
            payload_size = frame_count * 4 * 4  # 4 channels, float32
            remaining = payload_size
            while remaining > 0:
                try:
                    chunk = s.recv(min(remaining, 4096))
                except socket.timeout:
                    break
                if not chunk:
                    break
                remaining -= len(chunk)

        if frame_count > 0:
            s.close()
            return {
                "version": version,
                "frame_count": frame_count,
                "graph_pos": graph_pos,
                "graph_nsec": graph_nsec,
            }

    s.close()
    return None


@pytest.fixture(scope="session")
def read_pcm_header():
    """Fixture returning a pcm-bridge binary header reader."""
    return _read_pcm_header
