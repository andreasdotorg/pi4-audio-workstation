"""Service-integration test fixtures — real stack, no browser.

Tests in this directory run against the real local-demo stack via direct
HTTP API calls, TCP sockets, and subprocess commands.  They do NOT use a
browser — Playwright is not a dependency.

Backend fixtures are shared with tests/e2e/ via tests/fixtures/backend.py.

The stack is started by scripts/test-e2e.sh BEFORE pytest is invoked.
"""

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
# Hooks — delegate to shared backend
# ---------------------------------------------------------------------------

def pytest_configure(config):
    register_markers(config)


def pytest_addoption(parser):
    add_backend_options(parser)


def pytest_collection_modifyitems(config, items):
    apply_backend_skips(config, items)
