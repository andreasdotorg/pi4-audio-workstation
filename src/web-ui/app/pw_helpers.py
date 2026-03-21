"""Shared PipeWire pw-dump / pw-cli helpers.

Extracted from ``audio_mute.py`` so that both the mute manager and the
config routes can read/write gain nodes and query PipeWire state without
duplicating subprocess logic.

Functions:
    pw_dump()         — Run ``pw-dump`` and return parsed JSON.
    find_gain_node()  — Find a gain node's ID and current Mult value.
    set_mult()        — Set a gain node's Mult value via ``pw-cli``.
    find_quantum()    — Read the current clock.force-quantum from pw-dump.
    find_filter_info() — Read filter-chain node metadata (coefficients, taps).
"""

import asyncio
import json
import logging

log = logging.getLogger(__name__)


async def pw_dump() -> list | None:
    """Run ``pw-dump`` and return parsed JSON, or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pw-dump",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode != 0:
            log.error("pw-dump failed: %s", stderr.decode().strip())
            return None
        return json.loads(stdout)
    except asyncio.TimeoutError:
        log.error("pw-dump timed out")
        return None
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        log.error("pw-dump error: %s", exc)
        return None


def find_gain_node(pw_data: list, node_name: str) -> tuple[int | None, float]:
    """Find a gain node's ID and current Mult value from pw-dump output.

    Returns (node_id, current_mult).  If not found, returns (None, 0.0).
    The Mult value is read from the node's ``params`` property if present,
    defaulting to 1.0 (unity) if the Mult param is not exposed.
    """
    for obj in pw_data:
        props = obj.get("info", {}).get("props", {})
        if props.get("node.name") == node_name:
            node_id = obj.get("id")
            # Try to read current Mult from params.
            # pw-dump exposes params under info.params.Props[].Mult
            mult = 1.0
            params_list = obj.get("info", {}).get("params", {})
            if isinstance(params_list, dict):
                for props_entry in params_list.get("Props", []):
                    if isinstance(props_entry, dict) and "Mult" in props_entry:
                        try:
                            mult = float(props_entry["Mult"])
                        except (TypeError, ValueError):
                            pass
            return node_id, mult
    return None, 0.0


async def set_mult(node_id: int, node_name: str, mult: float) -> bool:
    """Set a gain node's Mult value via ``pw-cli``."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pw-cli", "s", str(node_id), "Props",
            f'{{ params = [ "Mult" {mult} ] }}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode == 0:
            log.debug("Set %s (node %d): Mult=%s", node_name, node_id, mult)
            return True
        log.warning("pw-cli failed for %s: %s", node_name, stderr.decode().strip())
        return False
    except asyncio.TimeoutError:
        log.warning("pw-cli timed out for %s", node_name)
        return False
    except FileNotFoundError:
        log.error("pw-cli not found")
        return False


def find_quantum(pw_data: list) -> int | None:
    """Read the current PipeWire quantum from pw-dump metadata.

    Looks for the ``settings`` metadata object and extracts
    ``clock.force-quantum`` (or ``clock.quantum`` as fallback).
    Returns None if not found.
    """
    for obj in pw_data:
        if obj.get("type") == "PipeWire:Interface:Metadata":
            props = obj.get("info", {}).get("props", {})
            if props.get("metadata.name") == "settings":
                # Metadata entries are in info.metadata[]
                for entry in obj.get("info", {}).get("metadata", []):
                    key = entry.get("key")
                    if key == "clock.force-quantum":
                        try:
                            val = entry.get("value", {})
                            if isinstance(val, dict):
                                return int(val.get("value", 0)) or None
                            return int(val) or None
                        except (TypeError, ValueError):
                            pass
                    if key == "clock.quantum":
                        try:
                            val = entry.get("value", {})
                            if isinstance(val, dict):
                                return int(val.get("value", 0)) or None
                            return int(val) or None
                        except (TypeError, ValueError):
                            pass
    return None


def find_filter_info(pw_data: list) -> dict:
    """Extract filter-chain convolver metadata from pw-dump.

    Returns a dict with filter file paths and tap counts if available,
    or an empty dict if the filter-chain node is not found.
    """
    for obj in pw_data:
        props = obj.get("info", {}).get("props", {})
        # The filter-chain convolver node is named "filter-chain-convolver"
        # or has factory.name = "filter-chain"
        if props.get("factory.name") == "filter-chain":
            return {
                "node_name": props.get("node.name", "filter-chain"),
                "node_id": obj.get("id"),
                "description": props.get("node.description", ""),
            }
    return {}
