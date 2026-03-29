"""Phase 1 DoD validation tests for TK-128 and TK-132.

TK-128: Mock processing_load values should be percentages (1.0-100.0),
        not fractions (0.01-1.0).
TK-132: /ws/pcm should stream mock PCM data instead of closing immediately.
"""

import asyncio
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _run(coro):
    """Run async coroutine in sync test context (works with pytest-playwright's loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


# ---------------------------------------------------------------------------
# TK-128: processing_load wire-format tests
# ---------------------------------------------------------------------------

class TestTK128ProcessingLoadPercentage:
    """Verify MockDataGenerator.monitoring() returns processing_load as a
    percentage (1.0-100.0) for all five scenarios (A-E)."""

    @pytest.fixture(autouse=True)
    def _setup_path(self):
        """Ensure app package is importable."""
        web_ui_dir = str(Path(__file__).resolve().parent.parent)
        if web_ui_dir not in sys.path:
            sys.path.insert(0, web_ui_dir)

    @pytest.mark.parametrize("scenario", ["A", "B", "C", "D", "E"])
    def test_processing_load_is_percentage(self, scenario):
        """processing_load must be in [1.0, 100.0] -- a percentage, not a
        fraction."""
        from app.mock.mock_data import MockDataGenerator

        gen = MockDataGenerator(scenario=scenario, freeze_time=True)
        data = gen.monitoring()

        load = data["camilladsp"]["processing_load"]
        assert isinstance(load, float), (
            f"Scenario {scenario}: processing_load should be float, "
            f"got {type(load).__name__}"
        )
        assert 1.0 <= load <= 100.0, (
            f"Scenario {scenario}: processing_load={load} is outside the "
            f"percentage range [1.0, 100.0]. If < 1.0, it's likely a "
            f"fraction (pre-TK-128 bug)."
        )

    @pytest.mark.parametrize("scenario", ["A", "B", "C", "D", "E"])
    def test_processing_load_not_fraction(self, scenario):
        """Guard: detect the pre-TK-128 bug where load was 0.01-1.0."""
        from app.mock.mock_data import MockDataGenerator, SCENARIOS

        base_load = SCENARIOS[scenario]["processing_load"]
        # The base load value in the scenario dict must itself be >= 1.0
        assert base_load >= 1.0, (
            f"Scenario {scenario}: base processing_load={base_load} in "
            f"SCENARIOS dict looks like a fraction, not a percentage."
        )


# ---------------------------------------------------------------------------
# TK-132: mock PCM stream tests — REMOVED (F-202)
# ---------------------------------------------------------------------------
# The mock_pcm.py module and mock PCM WebSocket path were removed per F-202
# (owner directive: eliminate `nix run .#serve`, local-demo only).
# PCM streaming is now exclusively via real pcm-bridge TCP relay.
# Tests for the TCP relay path are in test_pcm_mode2.py (production path).
