# CHANGE Session S-005: Stop Web UI Service (Xrun Mitigation)

**Evidence basis: CONTEMPORANEOUS**

TW received command-level CC from CM in real time during session execution.

---

**Date:** 2026-03-12, ~22:25-22:26 CET
**Operator:** worker-stop-webui (via CM CHANGE session S-005)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Safety precondition:** Owner confirmed PA is OFF prior to session grant.
**Scope:** Stop web UI service to eliminate xrun source. Runtime-only (service
remains enabled, will restart on next reboot).

---

## Trigger

OBSERVE session S-004 diagnosed Mixxx xruns at quantum 1024. The web UI
monitoring backend (`webui-monitor`) was identified as a significant
contributor, accumulating 1327 errors. Stopping the web UI service removes
this source from the PipeWire graph.

## Procedure

### Step 1: Identify Service

```bash
$ systemctl --user list-units --type=service | grep -i web
pi4-audio-webui.service        loaded active running Pi4 Audio Workstation monitoring web UI (D-020)
```

### Step 2: Stop Service

```bash
$ systemctl --user stop pi4-audio-webui.service
```

Service stopped successfully.

### Step 3: Verification

**No uvicorn processes:**

```bash
$ pgrep -a uvicorn
```

No output. All uvicorn processes terminated. PASS.

**Web UI monitor removed from PipeWire graph:**

```bash
$ pw-cli list-objects | grep -i webui
```

No output. `webui-monitor` no longer present in the PipeWire graph. PASS.

**Service status:**

```bash
$ systemctl --user status pi4-audio-webui.service
Active: inactive (dead) since Thu 2026-03-12 22:26:04 CET
Process: 1368 (code=killed, signal=TERM)
CPU: 2min 22.754s
```

Cleanly terminated via SIGTERM. Total CPU time consumed during uptime: 2min
22.754s.

## Validation Summary

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| uvicorn processes | None | None | PASS |
| webui-monitor in PipeWire graph | Absent | Absent | PASS |
| Service status | inactive (dead) | inactive (dead) | PASS |
| Termination signal | SIGTERM (clean) | SIGTERM (clean) | PASS |
| Service unit enabled | Yes (restart on reboot) | Yes (stop only, not disable) | PASS |

## Deviations from Plan

None.

## Notes

- The service was stopped but not disabled. It will restart on next reboot.
  This is intentional -- the web UI is a valuable monitoring tool and should
  be available by default. The xrun contribution needs to be fixed in the
  application (D-020 optimization), not by permanently disabling the service.
- The S-005 stop was clean (SIGTERM, immediate shutdown). Contrast with S-001
  where the web UI restart hung for ~50s during deactivation. The difference
  may be that S-001 was a restart (stop + start) while S-005 was a stop only,
  or that the JACK client state differed between the two sessions.
- The 2min 22.754s CPU time over the service's uptime (since reboot at
  ~22:12, so ~14 minutes) suggests moderate CPU consumption by the web UI
  backend. This is consistent with continuous JACK audio monitoring and
  PipeWire metadata polling.
- The finding that webui-monitor contributed to xruns is significant for
  D-020 development. The web UI's PipeWire client may need optimization
  (P8 from the PoC validation -- JACK callback target <500us) or may need
  to be redesigned to avoid being a real-time audio graph participant.
