"""E2E test fixtures — real stack, no mocks.

Tests in this directory run against the real local-demo stack:
PipeWire + GraphManager + signal-gen + pcm-bridge + level-bridge + web UI.
Only physical audio hardware (USBStreamer, speakers) is absent — replaced
by a null ALSA sink.

The stack is started by the test-e2e shell wrapper (scripts/test-e2e.sh)
BEFORE pytest is invoked.  The conftest does NOT start the stack itself;
it waits for it to be reachable and provides fixtures pointing at the
live server.

Environment variable:
    LOCAL_DEMO_URL  — base URL of the running web UI (default: http://localhost:8080)

If the web UI is not reachable within the timeout, all tests are skipped
with a clear message.
"""

import json
import os
import socket
import urllib.request
import urllib.error

import pytest


LOCAL_DEMO_URL = os.environ.get("LOCAL_DEMO_URL", "http://localhost:8080")
STACK_TIMEOUT = int(os.environ.get("E2E_STACK_TIMEOUT", "30"))


def _is_reachable(url: str, timeout: float = 2.0) -> bool:
    """Check if the web UI responds to a simple GET."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except (urllib.error.URLError, OSError):
        return False


def _wait_for_stack(url: str, timeout: int) -> bool:
    """Wait until the web UI is reachable or timeout expires."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_reachable(url):
            return True
        time.sleep(1)
    return False


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: real-stack end-to-end test")


def pytest_collection_modifyitems(config, items):
    """Skip all E2E tests if the local-demo stack is not reachable."""
    if not _is_reachable(LOCAL_DEMO_URL):
        if not _wait_for_stack(LOCAL_DEMO_URL, STACK_TIMEOUT):
            skip = pytest.mark.skip(
                reason=f"local-demo stack not reachable at {LOCAL_DEMO_URL}"
            )
            for item in items:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL of the running local-demo web UI."""
    return LOCAL_DEMO_URL


@pytest.fixture(scope="session")
def gm_port() -> int:
    """GraphManager RPC port."""
    return int(os.environ.get("GM_PORT", "4002"))


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
