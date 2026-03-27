"""Real-time per-channel thermal power monitor (T-092-2, US-092).

Reads per-channel RMS levels from LevelsCollector (pcm-bridge at 10 Hz)
and tracks voice coil thermal state using an exponential decay model.

The thermal model approximates voice coil heating as a first-order system:

    T(n) = T(n-1) * decay + P_inst * (1 - decay)

where:
    T     = smoothed power estimate (watts)
    P_inst = instantaneous power from latest RMS sample
    decay = exp(-dt / tau)
    tau   = thermal time constant (seconds)

Thermal state per channel:
    - power_watts: smoothed power estimate
    - ceiling_watts: thermal power rating (pe_max_watts)
    - headroom_db: dB below thermal ceiling
    - pct_of_ceiling: percentage of thermal ceiling used
    - status: "ok" | "warning" | "limit"

Warning threshold: within 3 dB of ceiling (per AC review).
Limit threshold: at or above ceiling.

The monitor runs as an asyncio task alongside the existing collectors.
It does NOT enforce gain limits (that's T-092-3).
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Thermal time constant: models voice coil thermal mass.
# 10s is conservative for small drivers (CHN-50P), longer for large subs.
DEFAULT_TAU_SECONDS = 10.0

# Warning when within this many dB of thermal ceiling.
WARNING_HEADROOM_DB = 3.0

# Update rate (Hz). Matches pcm-bridge push rate.
UPDATE_RATE_HZ = 10.0

# Default hardware parameters (duplicated from thermal_ceiling to avoid
# import path gymnastics — the canonical values live in thermal_ceiling.py).
_DEFAULT_AMP_VOLTAGE_GAIN = 42.4
_DEFAULT_ADA8200_0DBFS_VRMS = 4.9


@dataclass
class ChannelThermalState:
    """Per-channel thermal tracking state."""
    name: str
    channel_index: int
    identity: str = ""

    # Driver parameters
    pe_max_watts: Optional[float] = None
    impedance_ohm: float = 8.0
    sensitivity_db_spl: float = 87.0

    # PW filter-chain gain (linear Mult value)
    pw_gain_mult: float = 1.0

    # Hardware chain
    amp_voltage_gain: float = _DEFAULT_AMP_VOLTAGE_GAIN
    ada8200_0dbfs_vrms: float = _DEFAULT_ADA8200_0DBFS_VRMS

    # Thermal time constant
    tau_seconds: float = DEFAULT_TAU_SECONDS

    # Runtime state
    smoothed_power_watts: float = 0.0
    last_update_time: float = 0.0

    def update(self, rms_dbfs: float, now: float) -> None:
        """Update thermal state from a new RMS reading.

        Parameters
        ----------
        rms_dbfs : float
            RMS level in dBFS from pcm-bridge (post-convolver, post-gain).
            This is the signal level at the DAC input.
        now : float
            Current monotonic time (seconds).
        """
        if self.last_update_time == 0.0:
            self.last_update_time = now
            # First sample: initialize directly
            self.smoothed_power_watts = self._rms_to_power(rms_dbfs)
            return

        dt = now - self.last_update_time
        self.last_update_time = now

        if dt <= 0:
            return

        # Instantaneous power from RMS level
        p_inst = self._rms_to_power(rms_dbfs)

        # Exponential decay smoothing
        if self.tau_seconds > 0:
            decay = math.exp(-dt / self.tau_seconds)
        else:
            decay = 0.0  # No smoothing
        self.smoothed_power_watts = (
            self.smoothed_power_watts * decay + p_inst * (1.0 - decay))

    def _rms_to_power(self, rms_dbfs: float) -> float:
        """Convert RMS dBFS to estimated power at the speaker (watts).

        The pcm-bridge tap point is post-convolver, post-gain-node.
        The signal path from tap to speaker:

            pcm-bridge level (dBFS) -> DAC (Vrms) -> amp (V*gain) -> speaker

        Note: The PW gain node Mult is already applied before the
        pcm-bridge tap point (pcm-bridge taps the convolver output,
        which includes the gain node). So we do NOT apply Mult here.
        """
        if rms_dbfs <= -120.0:
            return 0.0

        # Voltage at DAC output
        v_dac = self.ada8200_0dbfs_vrms * (10.0 ** (rms_dbfs / 20.0))

        # Voltage at speaker terminals
        v_speaker = v_dac * self.amp_voltage_gain

        # Power: P = V^2 / Z
        if self.impedance_ohm > 0:
            return (v_speaker ** 2) / self.impedance_ohm
        return 0.0

    def headroom_db(self) -> Optional[float]:
        """Return dB below thermal ceiling, or None if no ceiling."""
        if self.pe_max_watts is None or self.pe_max_watts <= 0:
            return None
        if self.smoothed_power_watts <= 0:
            return None  # Infinite headroom, return None
        ratio = self.pe_max_watts / self.smoothed_power_watts
        if ratio <= 0:
            return 0.0
        return 10.0 * math.log10(ratio)

    def pct_of_ceiling(self) -> float:
        """Return percentage of thermal ceiling used (0-100+)."""
        if self.pe_max_watts is None or self.pe_max_watts <= 0:
            return 0.0
        return (self.smoothed_power_watts / self.pe_max_watts) * 100.0

    def status(self) -> str:
        """Return thermal status: 'ok', 'warning', or 'limit'."""
        if self.pe_max_watts is None or self.pe_max_watts <= 0:
            return "ok"  # No ceiling data, can't determine status
        pct = self.pct_of_ceiling()
        if pct >= 100.0:
            return "limit"
        hr = self.headroom_db()
        if hr is not None and hr <= WARNING_HEADROOM_DB:
            return "warning"
        return "ok"

    def to_dict(self) -> dict:
        """Serialize thermal state for API/WebSocket consumption."""
        hr = self.headroom_db()
        return {
            "name": self.name,
            "channel": self.channel_index,
            "identity": self.identity,
            "power_watts": round(self.smoothed_power_watts, 4),
            "ceiling_watts": self.pe_max_watts,
            "headroom_db": round(hr, 1) if hr is not None else None,
            "pct_of_ceiling": round(self.pct_of_ceiling(), 1),
            "status": self.status(),
            "impedance_ohm": self.impedance_ohm,
            "sensitivity_db_spl": self.sensitivity_db_spl,
        }


class ThermalMonitor:
    """Async service that tracks per-channel thermal state.

    Reads RMS levels from a LevelsCollector and updates thermal state
    for each configured speaker channel.
    """

    def __init__(
        self,
        levels_collector: Any,
        channels: Optional[List[ChannelThermalState]] = None,
        tau_seconds: float = DEFAULT_TAU_SECONDS,
    ) -> None:
        self._levels = levels_collector
        self._channels: Dict[int, ChannelThermalState] = {}
        self._tau = tau_seconds
        self._task: Optional[asyncio.Task] = None

        if channels:
            for ch in channels:
                ch.tau_seconds = tau_seconds
                self._channels[ch.channel_index] = ch

    def configure_channels(self, channels: List[ChannelThermalState]) -> None:
        """Replace the channel configuration (e.g. after profile change)."""
        self._channels.clear()
        for ch in channels:
            if ch.tau_seconds == DEFAULT_TAU_SECONDS:
                ch.tau_seconds = self._tau
            self._channels[ch.channel_index] = ch

    def configure_from_ceilings(self, ceilings: dict) -> None:
        """Configure channels from thermal_ceiling.load_channel_ceilings() output.

        Parameters
        ----------
        ceilings : dict
            Output of ``thermal_ceiling.load_channel_ceilings()``.
            Keys are speaker names, values have: channel, pe_max_watts,
            impedance_ohm, sensitivity_db_spl, identity, pw_gain_mult.
        """
        self._channels.clear()
        for spk_name, info in ceilings.items():
            ch = ChannelThermalState(
                name=spk_name,
                channel_index=info["channel"],
                identity=info.get("identity", ""),
                pe_max_watts=info.get("pe_max_watts"),
                impedance_ohm=info.get("impedance_ohm", 8.0),
                sensitivity_db_spl=info.get("sensitivity_db_spl", 87.0),
                pw_gain_mult=info.get("pw_gain_mult", 1.0),
                tau_seconds=self._tau,
            )
            self._channels[ch.channel_index] = ch

    async def start(self) -> None:
        """Start the thermal monitoring loop."""
        self._task = asyncio.create_task(
            self._monitor_loop(), name="thermal-monitor")
        log.info("ThermalMonitor started (%d channels, tau=%.1fs)",
                 len(self._channels), self._tau)

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("ThermalMonitor stopped")

    def snapshot(self) -> List[dict]:
        """Return current thermal state for all channels."""
        return [ch.to_dict()
                for ch in sorted(self._channels.values(),
                                  key=lambda c: c.channel_index)]

    def channel_state(self, channel_index: int) -> Optional[dict]:
        """Return thermal state for a single channel."""
        ch = self._channels.get(channel_index)
        if ch is None:
            return None
        return ch.to_dict()

    def any_warning(self) -> bool:
        """Return True if any channel is in warning or limit state."""
        return any(ch.status() in ("warning", "limit")
                   for ch in self._channels.values())

    def any_limit(self) -> bool:
        """Return True if any channel is at or above thermal limit."""
        return any(ch.status() == "limit"
                   for ch in self._channels.values())

    async def _monitor_loop(self) -> None:
        """Read RMS from levels collector and update thermal state."""
        interval = 1.0 / UPDATE_RATE_HZ
        while True:
            try:
                now = time.monotonic()
                rms_values = self._levels.rms()

                for ch_idx, ch_state in self._channels.items():
                    if ch_idx < len(rms_values):
                        rms_dbfs = rms_values[ch_idx]
                    else:
                        rms_dbfs = -120.0
                    ch_state.update(rms_dbfs, now)

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ThermalMonitor error")
                await asyncio.sleep(1.0)
