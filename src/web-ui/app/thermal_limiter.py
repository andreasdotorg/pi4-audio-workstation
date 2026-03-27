"""Thermal gain enforcement via PW filter-chain gain nodes (T-092-3, US-092).

When the ThermalMonitor (T-092-2) detects a channel approaching or exceeding
its thermal ceiling, this module reduces the PW gain node Mult value via
pw-cli to protect voice coils.

Gain reduction strategy (soft knee):
    - headroom > 3 dB:  no reduction (status "ok")
    - 3 dB >= headroom > 0 dB:  graduated linear reduction in dB
      (soft knee from 0 to -3 dB reduction as headroom decreases)
    - headroom <= 0 dB:  hard limit — reduce gain to keep power at ceiling

The limiter runs as an async loop alongside the thermal monitor, reading
its state and applying gain corrections.  Gain changes are session-only
via pw-cli (C-009: revert on PW restart).

Operator override: temporary ceiling increase with acknowledgment, logged
and time-limited (default 5 minutes), resets on mode/profile switch.

All limit engagements and overrides are logged to an audit trail.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# How often to evaluate and apply gain limits (Hz).
ENFORCE_RATE_HZ = 5.0

# Soft knee starts at this headroom threshold (dB above ceiling).
SOFT_KNEE_THRESHOLD_DB = 3.0

# Maximum gain reduction applied by the soft knee (dB).
# At exactly 0 dB headroom the limiter applies this much reduction.
SOFT_KNEE_MAX_REDUCTION_DB = 3.0

# Default operator override duration (seconds).
DEFAULT_OVERRIDE_DURATION_S = 300.0  # 5 minutes

# Minimum time between pw-cli calls for the same channel (seconds).
# Prevents flooding PipeWire with rapid Mult changes.
MIN_UPDATE_INTERVAL_S = 0.5

# Minimum Mult change to trigger a pw-cli update (avoids tiny corrections).
MULT_CHANGE_THRESHOLD = 0.0001


def _db_to_linear(db: float) -> float:
    """Convert dB to linear gain factor."""
    if db <= -120.0:
        return 0.0
    return 10.0 ** (db / 20.0)


def _linear_to_db(linear: float) -> float:
    """Convert linear gain factor to dB."""
    if linear <= 0.0:
        return -120.0
    return 20.0 * math.log10(linear)


@dataclass
class ChannelLimitState:
    """Per-channel limiter tracking state."""
    name: str
    channel_index: int
    gain_node_name: str

    # The "base" Mult from the .conf file (profile default).
    base_mult: float = 1.0

    # Current effective Mult applied via pw-cli (base * reduction).
    current_mult: float = 1.0

    # Current reduction factor (1.0 = no reduction, <1.0 = reduced).
    reduction_factor: float = 1.0

    # Last time we sent a pw-cli update for this channel.
    last_update_time: float = 0.0

    # Whether limiter is currently engaged for this channel.
    is_limiting: bool = False


@dataclass
class OverrideEntry:
    """Operator override: temporarily increases thermal ceiling."""
    channel_name: str
    ceiling_multiplier: float  # e.g. 1.5 = 50% ceiling increase
    expires_at: float  # monotonic time
    acknowledged_by: str = "operator"
    created_at: float = 0.0

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at


@dataclass
class AuditEntry:
    """Audit log entry for limiter actions."""
    timestamp: float
    channel: str
    action: str  # "engage", "disengage", "override_set", "override_expired", "reconfigure"
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "channel": self.channel,
            "action": self.action,
            "detail": self.detail,
        }


class ThermalGainLimiter:
    """Enforces thermal gain limits on PW filter-chain gain nodes.

    Reads thermal state from ThermalMonitor, computes required gain
    reductions, and applies them via pw-cli set_mult.
    """

    def __init__(
        self,
        thermal_monitor: Any,
        is_mock: bool = False,
    ) -> None:
        self._monitor = thermal_monitor
        self._is_mock = is_mock
        self._channels: Dict[str, ChannelLimitState] = {}
        self._overrides: Dict[str, OverrideEntry] = {}
        self._audit_log: List[AuditEntry] = []
        self._max_audit_entries = 500
        self._task: Optional[asyncio.Task] = None
        self._convolver_node_id: Optional[int] = None

    def configure_channels(
        self,
        channel_configs: List[Dict[str, Any]],
    ) -> None:
        """Configure channels from profile activation data.

        Parameters
        ----------
        channel_configs : list of dict
            Each dict has: name, channel_index, gain_node_name, base_mult.
            Example::
                [
                    {"name": "sat_left", "channel_index": 0,
                     "gain_node_name": "gain_left_hp", "base_mult": 0.001},
                    ...
                ]
        """
        old_channels = set(self._channels.keys())
        self._channels.clear()
        self._overrides.clear()  # Reset overrides on profile switch
        self._convolver_node_id = None  # Force re-discovery

        for cfg in channel_configs:
            name = cfg["name"]
            self._channels[name] = ChannelLimitState(
                name=name,
                channel_index=cfg["channel_index"],
                gain_node_name=cfg["gain_node_name"],
                base_mult=cfg["base_mult"],
                current_mult=cfg["base_mult"],
                reduction_factor=1.0,
            )

        now = time.monotonic()
        self._audit(now, "*", "reconfigure",
                    f"channels={list(self._channels.keys())}")
        log.info("ThermalGainLimiter reconfigured: %d channels", len(self._channels))

    async def start(self) -> None:
        """Start the enforcement loop."""
        self._task = asyncio.create_task(
            self._enforce_loop(), name="thermal-limiter")
        log.info("ThermalGainLimiter started (%d channels)", len(self._channels))

    async def stop(self) -> None:
        """Stop the enforcement loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("ThermalGainLimiter stopped")

    def set_override(
        self,
        channel_name: str,
        ceiling_multiplier: float = 1.5,
        duration_s: float = DEFAULT_OVERRIDE_DURATION_S,
        acknowledged_by: str = "operator",
    ) -> dict:
        """Set a temporary ceiling override for a channel.

        Returns a status dict for the API response.
        """
        if channel_name not in self._channels:
            return {"ok": False, "error": f"unknown channel: {channel_name}"}

        if ceiling_multiplier < 1.0 or ceiling_multiplier > 3.0:
            return {"ok": False, "error": "ceiling_multiplier must be 1.0-3.0"}

        if duration_s < 10.0 or duration_s > 1800.0:
            return {"ok": False, "error": "duration must be 10-1800 seconds"}

        now = time.monotonic()
        entry = OverrideEntry(
            channel_name=channel_name,
            ceiling_multiplier=ceiling_multiplier,
            expires_at=now + duration_s,
            acknowledged_by=acknowledged_by,
            created_at=now,
        )
        self._overrides[channel_name] = entry

        self._audit(now, channel_name, "override_set",
                    f"multiplier={ceiling_multiplier:.2f} "
                    f"duration={duration_s:.0f}s by={acknowledged_by}")
        log.warning("Thermal override SET: channel=%s multiplier=%.2f duration=%.0fs by=%s",
                    channel_name, ceiling_multiplier, duration_s, acknowledged_by)

        return {
            "ok": True,
            "channel": channel_name,
            "ceiling_multiplier": ceiling_multiplier,
            "expires_in_seconds": duration_s,
        }

    def clear_override(self, channel_name: str) -> dict:
        """Clear a ceiling override for a channel."""
        if channel_name not in self._channels:
            return {"ok": False, "error": f"unknown channel: {channel_name}"}

        removed = self._overrides.pop(channel_name, None)
        if removed is None:
            return {"ok": True, "detail": "no override active"}

        now = time.monotonic()
        self._audit(now, channel_name, "override_cleared", "manual")
        log.info("Thermal override CLEARED: channel=%s", channel_name)
        return {"ok": True, "channel": channel_name}

    def snapshot(self) -> dict:
        """Return current limiter state for API consumption."""
        channels = []
        now = time.monotonic()
        for name, ch in sorted(self._channels.items(),
                                key=lambda x: x[1].channel_index):
            override = self._overrides.get(name)
            override_info = None
            if override and not override.is_expired(now):
                override_info = {
                    "ceiling_multiplier": override.ceiling_multiplier,
                    "expires_in_seconds": round(override.expires_at - now, 0),
                    "acknowledged_by": override.acknowledged_by,
                }
            channels.append({
                "name": name,
                "channel": ch.channel_index,
                "gain_node": ch.gain_node_name,
                "base_mult": ch.base_mult,
                "current_mult": round(ch.current_mult, 6),
                "reduction_factor": round(ch.reduction_factor, 4),
                "reduction_db": round(_linear_to_db(ch.reduction_factor), 1),
                "is_limiting": ch.is_limiting,
                "override": override_info,
            })
        return {
            "channels": channels,
            "any_limiting": any(ch.is_limiting for ch in self._channels.values()),
        }

    def audit_log(self, limit: int = 50) -> List[dict]:
        """Return recent audit log entries."""
        return [e.to_dict() for e in self._audit_log[-limit:]]

    def compute_reduction(
        self,
        headroom_db: Optional[float],
        pct_of_ceiling: float,
        channel_name: str,
    ) -> float:
        """Compute the gain reduction factor for a channel.

        Returns a linear factor (0.0 to 1.0) to multiply with base_mult.
        1.0 = no reduction, <1.0 = gain reduced.
        """
        if headroom_db is None:
            return 1.0  # No ceiling data, no reduction

        # Check for active (non-expired) override
        now = time.monotonic()
        override = self._overrides.get(channel_name)
        effective_headroom = headroom_db
        if override and not override.is_expired(now):
            # Override increases the effective ceiling, which increases headroom
            override_db = 10.0 * math.log10(override.ceiling_multiplier)
            effective_headroom = headroom_db + override_db

        if effective_headroom > SOFT_KNEE_THRESHOLD_DB:
            return 1.0  # Plenty of headroom, no reduction

        if effective_headroom <= 0.0:
            # Hard limit: reduce gain to bring power back to ceiling.
            # If at 110% of ceiling (pct=110), need to reduce by 10%.
            # reduction_db = -10*log10(pct/100)
            if pct_of_ceiling <= 0:
                return 1.0
            power_reduction_db = -10.0 * math.log10(pct_of_ceiling / 100.0)
            # Apply override adjustment
            if override and not override.is_expired(now):
                override_db = 10.0 * math.log10(override.ceiling_multiplier)
                power_reduction_db += override_db
            # Ensure continuity with soft knee: at the boundary (headroom=0),
            # the soft knee would apply -SOFT_KNEE_MAX_REDUCTION_DB. The hard
            # limit must be at least that much reduction.
            reduction_db = min(power_reduction_db, -SOFT_KNEE_MAX_REDUCTION_DB)
            # Clamp: don't reduce below -20 dB
            reduction_db = max(reduction_db, -20.0)
            return _db_to_linear(reduction_db)

        # Soft knee: graduated linear interpolation in dB domain.
        # At threshold (3 dB): 0 dB reduction
        # At 0 dB headroom: -SOFT_KNEE_MAX_REDUCTION_DB reduction
        t = 1.0 - (effective_headroom / SOFT_KNEE_THRESHOLD_DB)
        reduction_db = -SOFT_KNEE_MAX_REDUCTION_DB * t
        return _db_to_linear(reduction_db)

    async def _enforce_loop(self) -> None:
        """Main enforcement loop: read thermal state, apply gain corrections."""
        interval = 1.0 / ENFORCE_RATE_HZ

        while True:
            try:
                now = time.monotonic()
                await self._enforce_tick(now)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ThermalGainLimiter error")
                await asyncio.sleep(1.0)

    async def _enforce_tick(self, now: float) -> None:
        """Single enforcement tick: compute and apply gain reductions."""
        # Expire overrides
        expired = [name for name, ov in self._overrides.items()
                   if ov.is_expired(now)]
        for name in expired:
            self._overrides.pop(name, None)
            self._audit(now, name, "override_expired", "")
            log.info("Thermal override EXPIRED: channel=%s", name)

        # Get thermal state from monitor
        thermal_snap = self._monitor.snapshot()
        thermal_by_name = {ch["name"]: ch for ch in thermal_snap}

        for name, ch_limit in self._channels.items():
            thermal = thermal_by_name.get(name)
            if thermal is None:
                continue

            headroom = thermal.get("headroom_db")
            pct = thermal.get("pct_of_ceiling", 0.0)

            # Compute required reduction
            new_factor = self.compute_reduction(headroom, pct, name)

            # Track engage/disengage transitions
            was_limiting = ch_limit.is_limiting
            is_now_limiting = new_factor < 1.0

            if is_now_limiting and not was_limiting:
                self._audit(now, name, "engage",
                            f"headroom={headroom:.1f}dB pct={pct:.1f}%")
                log.warning("Thermal limiter ENGAGED: %s headroom=%.1fdB pct=%.1f%%",
                            name, headroom or 0, pct)

            if not is_now_limiting and was_limiting:
                self._audit(now, name, "disengage",
                            f"headroom={headroom:.1f}dB")
                log.info("Thermal limiter DISENGAGED: %s", name)

            ch_limit.is_limiting = is_now_limiting
            ch_limit.reduction_factor = new_factor

            # Compute target Mult
            target_mult = ch_limit.base_mult * new_factor

            # Only send pw-cli if the change is significant and enough
            # time has passed since last update.
            mult_diff = abs(target_mult - ch_limit.current_mult)
            time_since_update = now - ch_limit.last_update_time

            if mult_diff < MULT_CHANGE_THRESHOLD:
                continue
            if time_since_update < MIN_UPDATE_INTERVAL_S:
                continue

            # Apply gain change
            ok = await self._apply_mult(ch_limit.gain_node_name, target_mult)
            if ok:
                ch_limit.current_mult = target_mult
                ch_limit.last_update_time = now

    async def _apply_mult(self, gain_node_name: str, mult: float) -> bool:
        """Apply a Mult value to a gain node via pw-cli."""
        if self._is_mock:
            return True

        from .pw_helpers import pw_dump, find_convolver_node, set_mult

        # Cache convolver node ID (it doesn't change during a session).
        if self._convolver_node_id is None:
            pw_data = await pw_dump()
            if pw_data is None:
                log.warning("ThermalGainLimiter: pw-dump failed")
                return False
            node_id, _ = find_convolver_node(pw_data)
            if node_id is None:
                log.warning("ThermalGainLimiter: convolver node not found")
                return False
            self._convolver_node_id = node_id

        return await set_mult(self._convolver_node_id, gain_node_name, mult)

    def _audit(self, timestamp: float, channel: str,
               action: str, detail: str) -> None:
        """Add an audit log entry."""
        entry = AuditEntry(
            timestamp=timestamp,
            channel=channel,
            action=action,
            detail=detail,
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries:]
