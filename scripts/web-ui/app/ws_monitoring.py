"""WebSocket handler for the Monitor view.

Pushes combined level-meter + CamillaDSP status data at ~10 Hz.
Each connected client gets its own MockDataGenerator instance
(will be replaced by real telemetry collectors in a later stage).
"""

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect, Query

from .mock.mock_data import MockDataGenerator

log = logging.getLogger(__name__)


async def ws_monitoring(
    ws: WebSocket,
    scenario: str = Query("A"),
    freeze_time: str = Query("false"),
):
    """Push monitoring data (levels + CamillaDSP health) at ~10 Hz."""
    await ws.accept()
    gen = MockDataGenerator(scenario=scenario, freeze_time=freeze_time.lower() == "true")
    log.info("Monitoring WS connected (scenario=%s, freeze_time=%s)", scenario, freeze_time)
    try:
        while True:
            data = gen.monitoring()
            await ws.send_text(json.dumps(data))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        log.info("Monitoring WS disconnected")
    except Exception:
        log.exception("Monitoring WS error")
