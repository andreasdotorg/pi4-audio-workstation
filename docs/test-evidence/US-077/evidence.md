# US-077 Test Evidence: PipeWire Graph Clock Propagation

**Date:** 2026-03-24
**Tester:** worker-demo-fix (automated)
**Environment:** Local demo stack (nix run .#local-demo equivalent, manual component start)

## DoD #2: Dashboard Steady-State Screenshot

### Setup
- PipeWire test environment with null USBStreamer sink (8ch, graph clock driver)
- Filter-chain convolver with dirac passthrough coefficients
- signal-gen playing 440 Hz sine at -20 dBFS on 4 channels
- pcm-bridge in monitor mode, levels server on TCP port 9190
- Links: signal-gen -> convolver -> USBStreamer + pcm-bridge

### Screenshot: `dashboard-steady-state.png`

Shows the web UI dashboard in mock mode with:
- Active level meters across all channel groups (PhysIn, App, DSP Out, PhysOut)
- Status bar mini-meters at top showing live data
- Spectrum analyzer rendering active audio content
- Green connection indicator confirming WebSocket connectivity

### Levels Data Sample (v2 with timestamps)

10 consecutive JSON snapshots from pcm-bridge levels server (TCP 9190),
captured during steady-state 440 Hz sine playback:

```jsonl
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3511296,"nsec":108004055154044}
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3515392,"nsec":108004140487376}
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3521536,"nsec":108004268487374}
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3525632,"nsec":108004353820706}
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3529728,"nsec":108004439154038}
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3535872,"nsec":108004567154036}
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3542016,"nsec":108004695154034}
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3546112,"nsec":108004780487366}
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3550208,"nsec":108004865820698}
{"channels":4,"peak":[-20.0,-20.0,-20.0,-20.0],"rms":[-23.0,-23.0,-23.0,-23.0],"pos":3556352,"nsec":108004993820696}
```

Key observations:
- `pos` field: monotonically increasing frame positions (PW graph clock)
- `nsec` field: monotonically increasing nanosecond timestamps (monotonic clock)
- Inter-snapshot `pos` delta: 2048-6144 frames (1-3 quanta at quantum=2048)
- Inter-snapshot `nsec` delta: ~85-128ms (consistent with ~10 Hz snapshot rate)
- Peak/RMS values stable at -20.0/-23.0 dBFS (440 Hz sine at -20 dBFS)

### Behavior Notes (Phase 4: Event-Driven Emission)

After Phase 4, the pcm-bridge levels server no longer uses `thread::sleep(100ms)`.
Instead, it waits on a `Notifier` (condvar) signaled by the PipeWire process callback.
The snapshot rate is still ~10 Hz (rate-limited by `Instant`-based gating), but emission
is now driven by the PW graph clock rather than an independent OS timer. This eliminates
the 5th independent clock identified in D-044.

## DoD #3: Timestamp Monotonicity Integration Test

### Test Script
`tests/integration/test_levels_timestamp_monotonicity.py`

### Test Run Output
```
Connecting to pcm-bridge levels at 127.0.0.1:9190...
Read 50 snapshots.
  First: pos=3814400, nsec=108010369820612
  Last:  pos=4058112, nsec=108015447153866
  Delta: pos=243712 frames, nsec=5077333254 (5.077s)

PASS: All timestamp monotonicity checks passed.
```

### Checks Performed
1. `pos` monotonically non-decreasing across 50 consecutive snapshots -- PASS
2. `nsec` monotonically non-decreasing across 50 consecutive snapshots -- PASS
3. `pos` values are non-zero (graph clock is being captured) -- PASS
4. `nsec` values are non-zero -- PASS

### Statistics
- 50 snapshots collected over 5.077 seconds (~9.85 Hz effective rate)
- Frame position advanced 243,712 frames (5.077s at 48kHz)
- All values strictly increasing (no stalls or resets observed)
