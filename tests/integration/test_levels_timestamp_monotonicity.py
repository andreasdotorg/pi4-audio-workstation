#!/usr/bin/env python3
"""Integration test: pcm-bridge levels timestamp monotonicity (US-077 DoD #3).

Connects to the pcm-bridge levels TCP server (default 127.0.0.1:9100),
reads N consecutive JSON snapshots, and verifies:

1. ``pos`` field is monotonically non-decreasing
2. ``nsec`` field is monotonically non-decreasing
3. ``pos`` values are non-zero (graph clock is being captured)
4. ``nsec`` values are non-zero

Requires a running pcm-bridge with an active PipeWire graph (e.g.,
``nix run .#local-demo``).

Usage:
    python tests/integration/test_levels_timestamp_monotonicity.py
    python tests/integration/test_levels_timestamp_monotonicity.py --host 127.0.0.1 --port 9100 --samples 50
"""

from __future__ import annotations

import argparse
import json
import socket
import sys


def read_snapshots(host: str, port: int, count: int, timeout: float = 10.0) -> list[dict]:
    """Connect to pcm-bridge levels server and read ``count`` JSON snapshots."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((host, port))

    buf = b""
    snapshots: list[dict] = []
    try:
        while len(snapshots) < count:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    snapshots.append(json.loads(line))
    finally:
        sock.close()
    return snapshots


def run_checks(snapshots: list[dict]) -> list[str]:
    """Run monotonicity and non-zero checks. Returns list of failure messages."""
    failures: list[str] = []

    if len(snapshots) < 2:
        failures.append(f"Not enough snapshots: got {len(snapshots)}, need at least 2")
        return failures

    # Check all snapshots have pos and nsec fields
    for i, snap in enumerate(snapshots):
        if "pos" not in snap:
            failures.append(f"Snapshot {i}: missing 'pos' field")
        if "nsec" not in snap:
            failures.append(f"Snapshot {i}: missing 'nsec' field")

    if failures:
        return failures

    pos_values = [s["pos"] for s in snapshots]
    nsec_values = [s["nsec"] for s in snapshots]

    # Check 1: pos monotonically non-decreasing
    for i in range(1, len(pos_values)):
        if pos_values[i] < pos_values[i - 1]:
            failures.append(
                f"pos not monotonic at index {i}: {pos_values[i - 1]} -> {pos_values[i]}"
            )

    # Check 2: nsec monotonically non-decreasing
    for i in range(1, len(nsec_values)):
        if nsec_values[i] < nsec_values[i - 1]:
            failures.append(
                f"nsec not monotonic at index {i}: {nsec_values[i - 1]} -> {nsec_values[i]}"
            )

    # Check 3: pos values are non-zero (graph clock captured)
    zero_pos = [i for i, v in enumerate(pos_values) if v == 0]
    if len(zero_pos) == len(pos_values):
        failures.append("All pos values are zero — graph clock not being captured")
    elif zero_pos:
        # Some zeros at the start are acceptable (startup transient)
        if len(zero_pos) > 3:
            failures.append(
                f"{len(zero_pos)}/{len(pos_values)} pos values are zero"
            )

    # Check 4: nsec values are non-zero
    zero_nsec = [i for i, v in enumerate(nsec_values) if v == 0]
    if len(zero_nsec) == len(nsec_values):
        failures.append("All nsec values are zero — graph clock not being captured")
    elif zero_nsec:
        if len(zero_nsec) > 3:
            failures.append(
                f"{len(zero_nsec)}/{len(nsec_values)} nsec values are zero"
            )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test pcm-bridge levels timestamp monotonicity (US-077)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Levels server host")
    parser.add_argument("--port", type=int, default=9100, help="Levels server port")
    parser.add_argument("--samples", type=int, default=50, help="Number of snapshots to read")
    parser.add_argument("--timeout", type=float, default=15.0, help="Socket read timeout (seconds)")
    args = parser.parse_args()

    print(f"Connecting to pcm-bridge levels at {args.host}:{args.port}...")
    try:
        snapshots = read_snapshots(args.host, args.port, args.samples, args.timeout)
    except ConnectionRefusedError:
        print("FAIL: Connection refused. Is pcm-bridge running? (nix run .#local-demo)")
        return 1
    except socket.timeout:
        print("FAIL: Socket timeout. Is pcm-bridge producing data?")
        return 1

    print(f"Read {len(snapshots)} snapshots.")

    if snapshots:
        first = snapshots[0]
        last = snapshots[-1]
        print(f"  First: pos={first.get('pos')}, nsec={first.get('nsec')}")
        print(f"  Last:  pos={last.get('pos')}, nsec={last.get('nsec')}")
        pos_delta = last.get("pos", 0) - first.get("pos", 0)
        nsec_delta = last.get("nsec", 0) - first.get("nsec", 0)
        print(f"  Delta: pos={pos_delta} frames, nsec={nsec_delta} ({nsec_delta / 1e9:.3f}s)")

    failures = run_checks(snapshots)

    if failures:
        print(f"\nFAIL: {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nPASS: All timestamp monotonicity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
