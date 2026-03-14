# CHANGE Session S-002: Pi Reboot (Mixxx Xruns)

**Evidence basis: CONTEMPORANEOUS**

TW received command-level CC from CM in real time during session execution.
Commands and results recorded as they were relayed.

---

**Date:** 2026-03-12, ~22:10-22:13 CET
**Operator:** worker-reboot (via CM CHANGE session S-002)
**Host:** mugge (Raspberry Pi 4B, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt)
**Safety precondition:** Owner confirmed PA is OFF prior to session grant.
**Scope:** Pi reboot per owner request (Mixxx xruns observed). No config changes.

---

## Trigger

Owner reported Mixxx xruns. Reboot requested to clear transient state.

## Procedure

### Step 1: Reboot

```bash
$ ssh ela@192.168.178.185 "sudo reboot"
```

Connection closed (Pi rebooting). No error output.

### Step 2: SSH Verification

Pi back up at 22:12:16 CET. Uptime: 0 minutes. SSH connection re-established.

### Step 3: Service Verification

All critical services verified running after reboot:

| Service | Type | Status | PID | Notes |
|---------|------|--------|-----|-------|
| PipeWire | user | active (running) | 1358 | Clean start |
| PipeWire-Pulse | user | active (running) | 1366 | Clean start |
| WirePlumber | user | active (running) | 1363 | Minor warnings (UPower, BlueZ, libcamera) -- expected, benign |
| CamillaDSP | system | active (running) | 796 | v3.0.1, listening 127.0.0.1:1234, config: /etc/camilladsp/active.yml |
| labwc | user | active (running) | 1356 | Clean start |

**CamillaDSP startup warning:** Log shows `WARN: Prepare playback after buffer
underrun` at 22:11:16. This is a common transient at boot when CamillaDSP
starts before audio clients are connected. Not related to the Mixxx xrun issue
that triggered the reboot.

**WirePlumber warnings:** UPower, BlueZ, and libcamera warnings are expected on
this system (no Bluetooth audio, no camera). These are benign and have been
observed in previous boot logs.

## Validation Summary

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| SSH reachable after reboot | Yes | Yes (22:12:16) | PASS |
| PipeWire running | active (running) | active (running) | PASS |
| PipeWire-Pulse running | active (running) | active (running) | PASS |
| WirePlumber running | active (running) | active (running) | PASS |
| CamillaDSP running | active (running) | active (running) | PASS |
| CamillaDSP bound to localhost | 127.0.0.1:1234 | 127.0.0.1:1234 | PASS |
| CamillaDSP config | /etc/camilladsp/active.yml | /etc/camilladsp/active.yml | PASS |
| labwc running | active (running) | active (running) | PASS |

## Deviations from Plan

None. Reboot and service verification completed as scoped.

## Notes

- Boot time to SSH availability was approximately 2 minutes (reboot issued
  ~22:10, SSH verified 22:12:16). This is consistent with previous boot
  observations on this hardware.
- The original trigger (Mixxx xruns) was not further diagnosed in this session.
  The reboot clears transient state but does not identify root cause. If xruns
  recur, deeper investigation may be needed (PipeWire graph state, CPU
  scheduling, thermal).
- No config changes were made during this session (CHANGE tier, not DEPLOY).
- Web UI service (`pi4-audio-webui`) status was not checked in this session.
  It was restarted during S-001 earlier this evening and should have come back
  after reboot, but this was not explicitly verified.
