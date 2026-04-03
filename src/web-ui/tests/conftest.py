"""Root conftest — shared marker registration and path setup.

Mock mode env vars, SessionConfig patch, and the ``client`` fixture live
in ``tests/unit/conftest.py``.  Browser fixtures live in
``tests/integration/conftest.py``.  Real-stack E2E fixtures live in
``tests/e2e/conftest.py``.
"""

import os
import sys

import pytest

# Add room-correction scripts to sys.path (shared across all test tiers).
_RC_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "room-correction"))
if _RC_DIR not in sys.path:
    sys.path.insert(0, _RC_DIR)

_MOCK_DIR = os.path.join(_RC_DIR, "mock")
if _MOCK_DIR not in sys.path:
    sys.path.insert(0, _MOCK_DIR)

_MEAS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "measurement"))
if _MEAS_DIR not in sys.path:
    sys.path.insert(0, _MEAS_DIR)


# ---------------------------------------------------------------------------
# Marker registration (all tiers)
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "needs_pw: requires running PipeWire")
    config.addinivalue_line("markers", "needs_usb_audio: requires USB audio hardware")
    config.addinivalue_line("markers", "needs_acoustic: requires acoustic environment")
    config.addinivalue_line("markers", "audio_producing: test produces audible output")
