"""Real data collectors for the Pi Audio Workstation monitoring UI.

Five singleton collectors poll actual system sources on the Pi:
    - CamillaDSPCollector: DSP levels and status via pycamilladsp (legacy)
    - FilterChainCollector: filter-chain health via GraphManager RPC (D-040)
    - PcmStreamCollector: JACK ring buffer for binary PCM streaming
    - SystemCollector: CPU, memory, temperature from /proc and /sys
    - PipeWireCollector: PipeWire graph state from pw-top

On macOS (development), collectors return fallback/mock data.
"""

from .camilladsp_collector import CamillaDSPCollector
from .filterchain_collector import FilterChainCollector
from .pcm_collector import PcmStreamCollector
from .pipewire_collector import PipeWireCollector
from .system_collector import SystemCollector

__all__ = [
    "CamillaDSPCollector",
    "FilterChainCollector",
    "PcmStreamCollector",
    "PipeWireCollector",
    "SystemCollector",
]
