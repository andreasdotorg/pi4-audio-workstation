# CHANGE Session S-003: PipeWire Quantum Switch to 1024 (DJ Mode)

**Evidence basis: CONTEMPORANEOUS**

TW received command-level CC from CM in real time during session execution.

---

**Date:** 2026-03-12, ~22:15 CET
**Operator:** worker-dj-mode (via CM CHANGE session S-003)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Safety precondition:** Owner confirmed PA is OFF prior to session grant.
**Scope:** PipeWire quantum switch to 1024 for DJ mode. Runtime-only change,
no config file modifications, reversible on reboot.

---

## Trigger

Mixxx xruns observed at quantum 256 (production default). Per CLAUDE.md:
DJ mode uses quantum 1024 (set at runtime via `pw-metadata`), live mode uses
quantum 256 (static config). The quantum 256 setting is optimized for live
vocal latency, not for Mixxx CPU headroom.

## Procedure

### Step 1: Set Quantum

```bash
$ pw-metadata -n settings 0 clock.force-quantum 1024
Found "settings" metadata 34
set property: id:0 key:clock.force-quantum value:1024 type:(null)
```

### Step 2: Verify

```bash
$ pw-metadata -n settings
Found "settings" metadata 34
update: id:0 key:'clock.force-quantum' value:'1024' type:''
```

Full metadata dump confirms:
- `clock.force-quantum`: 1024 (active override)
- `clock.quantum`: 256 (static config default, overridden by force-quantum)
- `clock.min-quantum`: 256
- `clock.max-quantum`: 1024
- `clock.rate`: 48000

## Validation Summary

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| clock.force-quantum | 1024 | 1024 | PASS |
| clock.rate | 48000 | 48000 | PASS |
| Config files modified | None | None | PASS |
| Services restarted | None | None | PASS |

## Deviations from Plan

None.

## Notes

- This is a runtime-only change via PipeWire metadata. It will revert to the
  static config default (quantum 256) on reboot. This is the expected behavior
  per the project's dual-quantum design (D-011).
- The quantum switch from 256 to 1024 increases audio buffer latency from
  ~5.3ms to ~21.3ms per PipeWire hop. This is acceptable for DJ mode (no
  live vocalist monitoring concern) and reduces CPU load, giving Mixxx more
  headroom.
- No service restart was required. PipeWire applies the force-quantum change
  immediately to the running audio graph.
