"""E2E test fixtures and configuration for the D-020 Web UI.

Provides:
    - mock_server: session-scoped FastAPI server on a free port
    - page: overrides pytest-playwright's page with console error capture
            and auto-navigation to mock_server
    - frozen_page: deterministic page for visual regression tests
    - pi_url: reads PI_AUDIO_URL env var (skips if unset)

Custom CLI flags:
    --destructive: allow tests marked @pytest.mark.destructive

Note: --headed is provided by pytest-playwright (do not re-declare).
"""

import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


# ── Chromium headless_shell crash workaround (F-120) ─────────────
# Chromium 141's headless_shell crashes on aarch64-linux when rendering
# <select> elements.  The full chrome binary does not have this bug.
# Detect aarch64 and override the executable so pytest-playwright uses
# the full chrome instead of headless_shell.

def _find_full_chrome() -> str | None:
    """Return the full chrome binary path from PLAYWRIGHT_BROWSERS_PATH."""
    browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if not browsers:
        return None
    # playwright-browsers dir contains symlinks like chromium-NNNN -> /nix/store/...
    for entry in sorted(Path(browsers).iterdir()):
        if entry.name.startswith("chromium-") and "headless" not in entry.name:
            chrome = entry / "chrome-linux" / "chrome"
            if chrome.exists():
                return str(chrome)
    return None


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Use full chrome on aarch64 to avoid headless_shell <select> crash (F-120)."""
    if platform.machine() == "aarch64":
        chrome = _find_full_chrome()
        if chrome:
            browser_type_launch_args = {**browser_type_launch_args, "executable_path": chrome}
    return browser_type_launch_args


# ── Marker registration ────────────────────────────────────────────


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: Playwright browser tests")
    config.addinivalue_line("markers", "e2e: end-to-end tests against a real Pi")
    config.addinivalue_line("markers", "destructive: tests that modify Pi state")
    config.addinivalue_line("markers", "slow: tests exceeding 10 s")


# ── CLI options ─────────────────────────────────────────────────────


def pytest_addoption(parser):
    parser.addoption(
        "--destructive",
        action="store_true",
        default=False,
        help="Allow tests marked @pytest.mark.destructive",
    )
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Update visual-regression reference screenshots instead of comparing",
    )


def pytest_collection_modifyitems(config, items):
    """Skip destructive tests unless --destructive is passed."""
    if config.getoption("--destructive"):
        return
    skip_destructive = pytest.mark.skip(reason="requires --destructive flag")
    for item in items:
        if "destructive" in item.keywords:
            item.add_marker(skip_destructive)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def mock_server(request):
    """Start the FastAPI app on a free port and yield its base URL.

    Captures stderr so crash diagnostics are available in test output.
    Stores the subprocess on the pytest session so the ``page`` fixture
    can check liveness before navigating (F-041).
    """
    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    web_ui_dir = Path(__file__).resolve().parent.parent.parent  # src/web-ui/

    # Write server output to temp files instead of pipes to avoid the
    # classic subprocess.PIPE deadlock: if nobody reads the pipe and the
    # OS buffer fills (~64 KB), the server blocks on write and freezes.
    # This was the root cause of F-041 — the server appeared alive
    # (proc.poll() == None) but couldn't serve requests.
    stderr_file = tempfile.NamedTemporaryFile(
        mode="w+", prefix="mock_server_stderr_", suffix=".log", delete=False)
    stdout_file = tempfile.NamedTemporaryFile(
        mode="w+", prefix="mock_server_stdout_", suffix=".log", delete=False)

    # Create a mock UMIK-1 calibration file so the /api/v1/test-tool/calibration
    # endpoint returns 200 instead of 404 in the Nix sandbox where
    # /home/ela/7161942.txt does not exist.
    mock_cal_dir = tempfile.mkdtemp(prefix="mock_cal_")
    mock_cal_file = os.path.join(mock_cal_dir, "mock-umik1.txt")
    with open(mock_cal_file, "w") as f:
        f.write('"Sens Factor =-1.378dB, SERNO: 0000000"\n')
        f.write("20.000\t-0.13\n100.000\t0.15\n1000.000\t0.00\n"
                "10000.000\t-0.22\n20000.000\t-1.05\n")

    # Set env vars for the mock server subprocess:
    # - PI4AUDIO_UMIK1_CAL: path to mock calibration file
    # - PI4AUDIO_MEAS_DIR: path to src/measurement/ for graph_manager_client import
    env = os.environ.copy()
    env["PI4AUDIO_UMIK1_CAL"] = mock_cal_file
    env["PI4AUDIO_MEAS_DIR"] = str(
        web_ui_dir.parent / "measurement")

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
        ],
        cwd=str(web_ui_dir),
        env=env,
        stdout=stdout_file,
        stderr=stderr_file,
    )

    def _read_stderr() -> str:
        """Read captured stderr from the temp file."""
        try:
            stderr_file.seek(0)
            return stderr_file.read()
        except Exception:
            return "<could not read stderr>"

    # Wait for the server to accept connections (10 s timeout)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            if proc.poll() is not None:
                # Server exited during startup — dump stderr immediately.
                pytest.fail(
                    f"mock_server exited during startup (rc={proc.returncode})"
                    f"\n--- stderr ---\n{_read_stderr()}"
                )
            time.sleep(0.1)
    else:
        proc.terminate()
        proc.wait(timeout=5)
        pytest.fail(
            f"mock_server did not start within 10 s on port {port}"
            f"\n--- stderr ---\n{_read_stderr()}"
        )

    # Stash proc and stderr reader on the session so the page fixture
    # can check liveness and dump diagnostics.
    request.config._mock_server_proc = proc
    request.config._mock_server_read_stderr = _read_stderr

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)

    # Dump stderr if the server crashed during the session.
    if proc.returncode not in (0, -15, None):
        # -15 = SIGTERM (normal teardown); anything else is a crash.
        print(
            f"\n=== mock_server crashed (rc={proc.returncode}) ===\n"
            f"{_read_stderr()}",
            file=sys.stderr,
        )

    # Clean up temp files.
    for f in (stderr_file, stdout_file):
        try:
            f.close()
            os.unlink(f.name)
        except OSError:
            pass

    # Clean up mock calibration file.
    import shutil
    shutil.rmtree(mock_cal_dir, ignore_errors=True)


def _assert_server_alive(config):
    """Fail fast if the mock server process has died (F-041)."""
    proc = getattr(config, "_mock_server_proc", None)
    if proc is not None and proc.poll() is not None:
        read_stderr = getattr(config, "_mock_server_read_stderr", lambda: "")
        pytest.fail(
            f"mock_server crashed before this test (rc={proc.returncode})"
            f"\n--- stderr ---\n{read_stderr()}"
        )


@pytest.fixture()
def page(browser, mock_server, request):
    """Create a fresh browser context and page, navigated to the mock server.

    Overrides pytest-playwright's page fixture to add console error capture
    and auto-navigate to the mock server.  Resets measurement state before
    each test so the wizard always starts from IDLE.

    Checks server liveness before navigating to avoid 30 s timeout cascades
    when the server has crashed (F-041).
    """
    _assert_server_alive(request.config)

    import json
    import urllib.request

    # Reset measurement state so each test starts from clean IDLE.
    # The session-scoped mock server retains _last_completed_session across
    # tests; this endpoint clears it (mock mode only).
    # The reset may need to cancel a running background task (F-049), so
    # allow a generous timeout.
    try:
        req = urllib.request.Request(
            f"{mock_server}/api/v1/measurement/reset", method="POST",
            headers={"Content-Length": "0"})
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass  # Server may not have the endpoint yet; non-fatal

    # Verify the server is actually in idle/monitoring state after reset.
    # Zombie lifecycle tasks (F-049) may still be running and can flip the
    # mode back to measurement if we proceed too quickly.
    for _attempt in range(10):
        try:
            resp = urllib.request.urlopen(
                f"{mock_server}/api/v1/measurement/status", timeout=5)
            status = json.loads(resp.read())
            if status.get("state") == "idle" and status.get("mode") == "monitoring":
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        # Log but don't fail — the test itself will catch any issues.
        pass

    context = browser.new_context()
    pg = context.new_page()
    console_errors = []
    pg.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    pg.goto(mock_server)
    yield pg
    context.close()
    # Filter out known-benign errors: siggen WS returns 403 when
    # PI4AUDIO_SIGGEN is not set (always the case in mock/test mode).
    # PCM WS endpoints also return 403 in mock mode (no real pcm-bridge).
    real_errors = [e for e in console_errors
                   if "/ws/siggen" not in e and "/ws/pcm" not in e]
    assert not real_errors, f"JS console errors: {real_errors}"


@pytest.fixture()
def frozen_page(browser, mock_server, request):
    """Page with freeze_time=true for deterministic visual regression tests.

    Navigates to scenario A with frozen mock data so screenshots are
    identical across runs. Waits for WebSocket data to populate the UI
    before yielding.
    """
    _assert_server_alive(request.config)
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    pg = context.new_page()
    console_errors = []
    pg.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    pg.goto(f"{mock_server}?scenario=A&freeze_time=true")
    # Wait for WebSocket data to arrive and populate the UI.
    # Note: sb-dsp-state is a text-only span with zero dimensions in headless
    # Chromium without fonts (Nix sandbox), so we use "attached" not "visible".
    pg.locator("#sb-dsp-state").wait_for(state="attached")
    pg.wait_for_function(
        "document.getElementById('sb-dsp-state').textContent !== '--'",
        timeout=5000,
    )
    yield pg
    context.close()
    real_errors = [e for e in console_errors
                   if "/ws/siggen" not in e and "/ws/pcm" not in e]
    assert not real_errors, f"JS console errors: {real_errors}"


@pytest.fixture()
def pi_url():
    """Yield the PI_AUDIO_URL env var, or skip if not set."""
    url = os.environ.get("PI_AUDIO_URL")
    if not url:
        pytest.skip("PI_AUDIO_URL not set")
    yield url
