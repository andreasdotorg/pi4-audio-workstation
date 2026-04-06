"""E2E test fixtures — browser-driven tests against the real stack.

Tests in this directory run against the real local-demo stack via a
Playwright browser.  Only physical audio hardware (USBStreamer, speakers)
is absent — replaced by a null ALSA sink.

Backend fixtures (API helpers, TCP readers, GM mode switching) are shared
with tests/service-integration/ via tests/fixtures/backend.py.

The stack is started by scripts/test-e2e.sh BEFORE pytest is invoked.
"""

import os
import platform
import sys
from pathlib import Path

import pytest

# Add the tests/ directory to sys.path so shared fixtures are importable.
_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from fixtures.backend import (  # noqa: F401, E402
    apply_backend_skips,
    register_markers,
    add_backend_options,
    backend_type,
    base_url,
    local_demo_url,
    gm_port,
    siggen_port,
    level_sw_port,
    level_hw_out_port,
    pcm_port,
    api_get,
    api_post,
    rpc_call,
    read_levels,
    read_pcm_header,
    ensure_dj_mode,
)


# ---------------------------------------------------------------------------
# Chromium headless_shell crash workaround (F-120)
# ---------------------------------------------------------------------------

def _find_full_chrome() -> str | None:
    """Return the full chrome binary path from PLAYWRIGHT_BROWSERS_PATH."""
    browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if not browsers:
        return None
    browsers_path = Path(browsers)
    if not browsers_path.is_dir():
        return None
    for entry in sorted(browsers_path.iterdir()):
        if entry.name.startswith("chromium-") and "headless" not in entry.name:
            chrome = entry / "chrome-linux" / "chrome"
            if chrome.exists():
                return str(chrome)
    return None


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Use full chrome on aarch64 + sandbox/shm flags for Nix containers."""
    args = dict(browser_type_launch_args)
    if platform.machine() == "aarch64":
        chrome = _find_full_chrome()
        if chrome:
            args["executable_path"] = chrome
    extra = ["--no-sandbox", "--disable-dev-shm-usage"]
    existing = list(args.get("args", []))
    for flag in extra:
        if flag not in existing:
            existing.append(flag)
    args["args"] = existing
    return args


# ---------------------------------------------------------------------------
# Hooks — delegate to shared backend
# ---------------------------------------------------------------------------

def pytest_configure(config):
    register_markers(config)


def pytest_addoption(parser):
    add_backend_options(parser)


def pytest_collection_modifyitems(config, items):
    apply_backend_skips(config, items)
