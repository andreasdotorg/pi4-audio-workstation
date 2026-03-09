# F-019: labwc Mouse Input Fix

### Reproducibility

| Role | Path |
|------|------|
| Defect entry | `docs/project/defects.md` (F-019) |
| labwc service file | `/home/ela/.config/systemd/user/labwc.service` |

---

## Summary

Mouse connected to Pi via USB -- cursor visible but frozen. Root cause: two
environment variables in the labwc systemd user service prevented wlroots from
using the libinput backend. Fix: remove `WLR_LIBINPUT_NO_DEVICES=1` and change
`WLR_BACKENDS=drm` to `WLR_BACKENDS=drm,libinput`.

**Severity:** Medium (input device non-functional, VNC-only workaround available)
**Status:** Resolved (mouse and keyboard working). Headless regression filed as F-019.

---

## Diagnosis

**Date:** 2026-03-09
**Operator:** Owner (Gabriela Bogk) + Claude team
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8 (stock PREEMPT), aarch64

### Symptom

Mouse connected to Pi. Cursor visible on screen but did not respond to movement.
Replugging the mouse did not help.

### Hardware verification

```bash
$ libinput debug-events
```

138+ `POINTER_MOTION` events observed. Hardware and the libinput stack were
functioning correctly. The problem was above libinput -- in the Wayland compositor.

### Root cause analysis

Two environment variables in `/home/ela/.config/systemd/user/labwc.service`
prevented wlroots from using libinput:

| Variable | Value | Effect |
|----------|-------|--------|
| `WLR_LIBINPUT_NO_DEVICES=1` | Set | Told wlroots to skip libinput entirely -- no mouse, no keyboard via libinput |
| `WLR_BACKENDS=drm` | DRM only | Restricted wlroots to the DRM backend, excluding the libinput backend |

Both variables were originally added for headless operation (no physical input
devices connected). Together they made physical input devices invisible to labwc.

---

## Fix

### Change 1: Remove WLR_LIBINPUT_NO_DEVICES

Removed `WLR_LIBINPUT_NO_DEVICES=1` from the labwc service environment. This
alone was not sufficient -- `WLR_BACKENDS=drm` still excluded libinput.

### Change 2: Add libinput to WLR_BACKENDS

Changed `WLR_BACKENDS=drm` to `WLR_BACKENDS=drm,libinput`. This tells wlroots
to initialize both the DRM backend (display output) and the libinput backend
(input devices).

### Service reload

```bash
$ systemctl --user daemon-reload
$ systemctl --user restart labwc.service
```

---

## Verification

After restart, labwc (PID 2618) had 8 `/dev/input` file descriptors open.
Mouse movement and keyboard input both confirmed working.

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| Mouse cursor responds to movement | Cursor tracks mouse | Cursor tracks mouse | PASS |
| Keyboard input works | Keystrokes registered | Keystrokes registered | PASS |
| labwc holds /dev/input FDs | >0 input FDs open | 8 input FDs open | PASS |

---

## Regression: F-019

Removing `WLR_LIBINPUT_NO_DEVICES=1` introduces a headless regression: without
any input devices connected, labwc may fail to start. This is the normal state
for the audio workstation in production (no keyboard/mouse attached).

Filed as F-019 in `docs/project/defects.md`. Current impact: none (USB
peripherals -- Hercules, APCmini, Nektar SE25, UMIK-1 -- register as input
devices). Must be resolved before headless production deployment.

---

## Remaining log noise

kanshi warnings observed in journal ("no profile matched", "No such output").
These are display configuration issues (kanshi cannot match the current output
to its profile), not input-related. Non-blocking -- cosmetic log noise only.
