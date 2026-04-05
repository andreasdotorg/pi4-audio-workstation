"""Real data collectors for the Pi Audio Workstation monitoring UI.

Four singleton collectors poll actual system sources on the Pi:
    - FilterChainCollector: filter-chain health via GraphManager RPC (D-040)
    - LevelsCollector: peak/RMS metering from pcm-bridge levels server
    - SystemCollector: CPU, memory, temperature, scheduling from /proc and /sys
    - PipeWireCollector: quantum/rate/xruns via GraphManager RPC (Phase 2a)

PCM streaming is handled by pcm-bridge (Rust, node.passive=true).
F-030: Legacy JACK PcmStreamCollector removed — it caused xruns under DJ load.

On macOS (development), collectors return fallback/mock data.
"""

from .filterchain_collector import FilterChainCollector
from .levels_collector import LevelsCollector
from .pcm_reader import PcmStreamReader
from .pipewire_collector import PipeWireCollector
from .system_collector import SystemCollector

__all__ = [
    "FilterChainCollector",
    "LevelsCollector",
    "PcmStreamReader",
    "PipeWireCollector",
    "SystemCollector",
]
