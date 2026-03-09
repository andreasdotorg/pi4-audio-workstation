# VNC Testing Session: Pi Application Fixes

The owner's first interactive VNC session (via wayvnc + Remmina) revealed
several issues with Mixxx and Reaper on the headless Pi. This lab note tracks
the fixes applied during the session: native Wayland rendering for Qt6 apps,
missing icon themes, Reaper audio device access, and fullscreen window
configuration.

All fixes stem from the owner's VNC testing session on 2026-03-09, documented
as TK-035 through TK-038 in the task register.

---

## Environment

**Date:** 2026-03-09
**Operator:** change-manager (automated via SSH)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8 PREEMPT aarch64
**Remote desktop:** wayvnc 0.9.1 on NOOP-fallback virtual display, Remmina client

---

## TK-035: Install qt6-wayland for Native Wayland Rendering -- DONE

**Problem:** Mixxx 2.5.0 (Qt6) renders via XWayland because the `qt6-wayland`
platform plugin is not installed. This adds XWayland overhead and may
contribute to missing icons (TK-036).

**Fix:**

```bash
sudo apt install -y qt6-wayland
# Installed: qt6-wayland:arm64 (6.8.2-4)
```

**Verification:** Killed the old Mixxx process and relaunched with native
Wayland:

```bash
pkill mixxx
WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 QT_QPA_PLATFORM=wayland mixxx &
```

Confirmed native Wayland rendering by checking the process environment:

```
WAYLAND_DISPLAY=wayland-0
QT_QPA_PLATFORM=wayland
```

No `DISPLAY` variable present -- Mixxx is not using XWayland.

**Before:** Mixxx ran via XWayland (`DISPLAY=:0`), qt6-wayland plugin missing.
**After:** Mixxx runs natively on Wayland. No crashes, no Wayland-specific
errors.

**Side effects:** XWayland process (PID 2730781) still running from the
earlier session but Mixxx no longer uses it. SVG pixmap warnings persist
(Mixxx skin issue, unrelated to Wayland).

**Status:** DONE.

---

## TK-036: Fix Missing Icons in Mixxx -- Pending Visual Verification

**Problem:** Mixxx shows broken/missing icons on the headless virtual display.
Qt6 apps need a platform theme bridge to inherit the GTK icon theme.

**Diagnostics:**

```bash
gsettings get org.gnome.desktop.interface icon-theme
# Result: 'PiXtrix'

echo "QT_QPA_PLATFORMTHEME=$QT_QPA_PLATFORMTHEME"
# Result: QT_QPA_PLATFORMTHEME=  (not set)

dpkg -l | grep qt6-gtk-platformtheme
# Result: not installed
```

The GTK icon theme (PiXtrix) was configured, but Qt6 had no bridge to use it.

**Fix:**

```bash
sudo apt install -y qt6-gtk-platformtheme
# Installed: qt6-gtk-platformtheme:arm64 (6.8.2+dfsg-9+deb13u1)

# Persist for all future app launches:
echo 'QT_QPA_PLATFORMTHEME=gtk3' >> ~/.config/labwc/environment
```

Relaunched Mixxx with the new theme:

```bash
pkill mixxx
WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 \
  QT_QPA_PLATFORM=wayland QT_QPA_PLATFORMTHEME=gtk3 mixxx &
```

Verified environment:

```
QT_QPA_PLATFORMTHEME=gtk3
QT_QPA_PLATFORM=wayland
```

**Before:** `QT_QPA_PLATFORMTHEME` not set, `qt6-gtk-platformtheme` not
installed. Qt6 apps could not inherit the GTK icon theme (PiXtrix).
**After:** Platform theme bridge installed and configured. Mixxx running with
gtk3 platform theme.

**labwc environment file** (`~/.config/labwc/environment`) now contains:

```
XKB_DEFAULT_MODEL=pc105
XKB_DEFAULT_LAYOUT=de
XKB_DEFAULT_VARIANT=
XKB_DEFAULT_OPTIONS=
LABWC_FALLBACK_OUTPUT=NOOP-fallback
QT_QPA_PLATFORMTHEME=gtk3
```

**Side effects:** `labwc --reconfigure` exited with code 1 (may not be
supported in labwc 0.9.2). The env vars were passed explicitly to Mixxx for
the current session; the labwc environment file takes effect for all future
app launches after a labwc restart.

**Status:** Applied. Needs owner visual verification via VNC to confirm icons
render correctly.

---

## TK-037: Fix Reaper Audio Device Access

**Problem:** Reaper cannot open audio device when launched via VNC. Likely
needs PipeWire JACK bridge (`pipewire-jack`) and Reaper audio settings pointed
to JACK rather than ALSA directly.

**Status:** Awaiting execution details from change-manager.

---

## TK-038: Configure Fullscreen Launch for Mixxx and Reaper

**Problem:** Apps launch in windowed mode on the virtual display. Owner wants
fullscreen by default. Options: labwc window rules in `rc.xml`, or launch
scripts with fullscreen flags.

**Status:** Awaiting execution details from change-manager.

---

## Summary

| TK | Description | Status |
|----|-------------|--------|
| TK-035 | qt6-wayland install | DONE -- native Wayland rendering confirmed |
| TK-036 | Mixxx missing icons | Applied -- pending owner visual verification |
| TK-037 | Reaper audio device | Not started |
| TK-038 | Fullscreen config | Not started |
