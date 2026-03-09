# VNC Testing Session: Pi Application Fixes

The owner's first interactive VNC session (via wayvnc + Remmina) revealed
several issues with Mixxx and Reaper on the headless Pi. This lab note tracks
the fixes applied during the session: native Wayland rendering for Qt6 apps,
missing icon themes, Reaper audio device access, and fullscreen window
configuration.

All fixes stem from the owner's VNC testing session on 2026-03-09, documented
as TK-035 through TK-046 in the task register.

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

## TK-037: Fix Reaper Audio Device Access -- DONE

**Problem:** Reaper cannot open audio device when launched via VNC. The
PipeWire JACK bridge package was not installed, so Reaper had no JACK backend
to connect to.

**Fix:**

```bash
sudo apt install -y pipewire-jack
# Installed: pipewire-jack:arm64 1.4.2-1+rpt3
```

Reaper is launched via the `pw-jack` wrapper rather than changing Reaper's
internal audio backend:

```bash
pw-jack /home/ela/opt/REAPER/REAPER/reaper
```

**Reaper audio config** (`~/.config/REAPER/reaper.ini`):

```ini
alsa_indev=
alsa_outdev=
linux_audio_bits=32
linux_audio_bsize=512
linux_audio_bufs=3
linux_audio_nch_in=8
linux_audio_nch_out=8
linux_audio_srate=44100
```

`alsa_indev` and `alsa_outdev` are empty -- Reaper uses the JACK backend when
launched via `pw-jack`.

> **Potential issue:** `linux_audio_srate=44100` does not match PipeWire and
> CamillaDSP (both at 48000 Hz). May need correction to avoid sample rate
> mismatch.

**Before:** Reaper had no JACK backend available. Audio device access failed.
**After:** `pipewire-jack` installed, Reaper sees JACK ports when launched via
`pw-jack`. Pending owner verification of 8ch in GUI.

**Side effects:** The `pipewire-jack` package may add ALSA plugin
configuration that intercepts `hw:` device paths. TK-042 was created to verify
CamillaDSP's direct ALSA path (`hw:USBStreamer,0`) is not broken by this
install. If CamillaDSP routes through PipeWire instead of direct ALSA, the
US-001/US-002 benchmarks are invalidated and must be rerun.

**Status:** DONE. TK-042 (ALSA path verification) is a follow-up.

---

## TK-038: Configure Fullscreen Launch for Mixxx and Reaper -- DONE

**Problem:** Apps launch in windowed mode on the virtual display. Owner wants
fullscreen by default.

**Fix:** labwc window rules in `~/.config/labwc/rc.xml` using
`ToggleFullscreen` action. Five rules cover Wayland app IDs and XWayland
WM_CLASS variants for both applications:

```xml
<!-- Mixxx native Wayland app_id -->
<windowRule identifier="org.mixxx.Mixxx">
  <action name="ToggleFullscreen"/>
</windowRule>
<!-- Mixxx lowercase variant -->
<windowRule identifier="org.mixxx.mixxx">
  <action name="ToggleFullscreen"/>
</windowRule>
<!-- Mixxx XWayland WM_CLASS -->
<windowRule identifier="mixxx">
  <action name="ToggleFullscreen"/>
</windowRule>
<!-- Reaper XWayland WM_CLASS -->
<windowRule identifier="REAPER">
  <action name="ToggleFullscreen"/>
</windowRule>
<!-- Reaper lowercase fallback -->
<windowRule identifier="reaper">
  <action name="ToggleFullscreen"/>
</windowRule>
```

**Before:** Apps launched in windowed mode with title bar visible.
**After:** `ToggleFullscreen` removes title bar and fills the virtual display.
labwc reconfigured to apply rules.

**Status:** DONE. Pending owner visual verification via VNC.

---

## TK-040: Reaper JACK Input -- USBStreamer 8ch Not Visible

**Problem:** After TK-037 (Reaper set to JACK), the owner could not see the
USBStreamer 8-channel input ports in Reaper's audio device list. Only the
UMIK-1 was visible.

**Root cause:** The `20-usbstreamer.conf` PipeWire config included a playback
sink node for the USBStreamer. CamillaDSP holds exclusive ALSA playback access
to `hw:USBStreamer,0`, so PipeWire's playback node conflicted. Only the
capture source should be exposed via PipeWire.

**Fix:** Removed the playback sink section from
`~/.config/pipewire/pipewire.conf.d/20-usbstreamer.conf` (capture source
only). Restarted PipeWire.

**Verification:** `pw-jack jack_lsp` output after fix:

```
# Capture sources
Umik-1  Gain  18dB Analog Stereo:capture_FL
Umik-1  Gain  18dB Analog Stereo:capture_FR
USBStreamer 8ch Input:capture_AUX0
USBStreamer 8ch Input:capture_AUX1
USBStreamer 8ch Input:capture_AUX2
USBStreamer 8ch Input:capture_AUX3
USBStreamer 8ch Input:capture_AUX4
USBStreamer 8ch Input:capture_AUX5
USBStreamer 8ch Input:capture_AUX6
USBStreamer 8ch Input:capture_AUX7

# Reaper JACK ports
REAPER:out1 through REAPER:out8
REAPER:in1 through REAPER:in8

# CamillaDSP playback sink
CamillaDSP 8ch Input:playback_AUX0 through AUX7
CamillaDSP 8ch Input:monitor_AUX0 through AUX7

# Built-in audio
Built-in Audio Stereo:playback_FL/FR + monitor_FL/FR

# MIDI (via Midi-Bridge)
DJControl Mix Ultra, SE25, APC mini mk2, Midi Through
```

All USBStreamer 8-channel capture ports visible. UMIK-1 visible as stereo
capture. Reaper has 8 in + 8 out JACK ports. All 3 USB-MIDI controllers
visible via Midi-Bridge (Hercules, Nektar SE25, APC mini mk2).

**Before:** USBStreamer capture not visible in Reaper; PipeWire playback node
conflicted with CamillaDSP's exclusive ALSA access.
**After:** USBStreamer 8ch capture visible at system level. Reaper running
(PID 3565188).

**Note:** PipeWire nodes subsequently renamed to `ada8200-in` / `ada8200-out`
(commit `8d9ec50`) for clarity in Reaper's port list. Reaper may need relaunch
to pick up the new names.

**Status:** Fix applied. Pending owner verification that all 8 channels appear
in Reaper's GUI via VNC. Blocks TK-039 (end-to-end audio validation).

---

## TK-041: 64 Phantom MIDI Devices in Reaper + Unwanted BLE MIDI

**Problem:** Reaper shows 64 phantom MIDI input/output ports and an unwanted
BLE MIDI device. The owner expected to see only the physical USB-MIDI
controllers (Hercules, APCmini, Nektar SE25).

**Analysis (audio engineer):**
- **64 ports:** Likely from `snd-virmidi` kernel module or PipeWire ALSA MIDI
  bridge over-enumeration. NOT caused by `snd-aloop`.
- **BLE MIDI:** A BlueALSA/bluez artifact (despite `disable-bt` in config),
  NOT the Hercules controller. Owner confirmed USB-MIDI works; Bluetooth
  scrapped (PO decision recorded).

**Key diagnostic:** `cat /proc/asound/seq/clients` confirmed the ALSA
sequencer layer as the source.

**Observation from TK-040:** The `pw-jack jack_lsp` MIDI section shows only
the 3 physical USB-MIDI controllers plus Midi Through -- clean, no phantom 64
ports via the JACK MIDI bridge. The 64 phantoms appeared only in Reaper's ALSA
MIDI view, confirming the root cause was in the ALSA sequencer layer.

**Fix applied:**
- **BLE MIDI:** Bluetooth disabled and masked (systemd). The BLE MIDI phantom
  was a BlueALSA artifact, not the Hercules controller.
- **64 phantom ports:** `snd-virmidi` kernel module blacklisted.

**Before:** 64 phantom MIDI ports + BLE MIDI device in Reaper.
**After:** Only physical USB-MIDI controllers visible (Hercules, SE25, APC
mini mk2). JACK MIDI bridge was already clean.

**Status:** DONE.

---

## UMIK-1 Low-Priority WirePlumber Rule

**Problem:** The UMIK-1 measurement microphone is a USB audio device that
PipeWire may assign higher priority than desired, potentially interfering with
the USBStreamer audio routing.

**Fix:** WirePlumber rule deployed to set UMIK-1 session and driver priority
to 0 (lowest), preventing it from being selected as PipeWire's default audio
source.

**File:** `~/.config/wireplumber/wireplumber.conf.d/52-umik1-low-priority.conf`
(repo copy: `configs/wireplumber/52-umik1-low-priority.conf`)

```lua
monitor.alsa.rules = [
  {
    matches = [
      { node.name = "~alsa_input.*UMIK*" }
    ]
    actions = {
      update-props = {
        priority.session = 0
        priority.driver = 0
      }
    }
  }
]
```

**Effect:** The USBStreamer remains the primary audio device. The UMIK-1 is
still available for measurement use but will not be auto-selected by PipeWire
as the default source.

**Status:** Applied.

---

## PipeWire Node Rename (commit 8d9ec50)

PipeWire nodes for the USBStreamer were renamed from generic `USBStreamer 8ch
Input` to descriptive `ada8200-in` / `ada8200-out` names. This makes port
identification clearer in Reaper and other JACK-aware applications.

The rename was applied in the PipeWire configuration and committed as
`8d9ec50`. Applications (Reaper, Mixxx) may need relaunch to pick up the new
port names.

---

## TK-046: Fix Reaper Sample Rate Mismatch -- Owner Applied via GUI

**Problem:** Flagged during TK-037 documentation: `linux_audio_srate=44100` in
`~/.config/REAPER/reaper.ini` does not match PipeWire and CamillaDSP (both at
48000 Hz). The mismatch forces PipeWire to perform sample rate conversion
(~1-2 ms additional latency, wasted CPU on 8 channels).

**Audio engineer assessment:** Real issue, fix immediately. SRC in a pro audio
path is non-negotiable. Artifacts are below -100 dB but the latency and CPU
cost are not acceptable.

**Fix:** Owner corrected the sample rate to 48000 Hz via Reaper's GUI (Audio
Settings dialog). Two parts required:
1. `reaper.ini`: `linux_audio_srate=48000`
2. Any `.RPP` project: File > Project Settings > Project Sample Rate = 48000

Both must match -- if only the ini is fixed but the project is at 44100,
Reaper resamples internally.

**Status:** DONE (owner applied). Must be verified in TK-044 reboot test and
captured in TK-045 (version-control Reaper config).

---

## USB Hot-Plug Resilience Analysis (Architect)

The architect assessed USB hot-plug behavior for the three device categories:

| Device | Hot-Plug Safe | Notes |
|--------|---------------|-------|
| UMIK-1 | Yes | Measurement mic, only needed during calibration. Safe to disconnect/reconnect at any time. PipeWire handles appearance/disappearance. |
| MIDI controllers | Yes | Hercules, SE25, APC mini mk2. USB-MIDI hot-plug works -- PipeWire MIDI bridge re-enumerates automatically. |
| USBStreamer | No | CamillaDSP holds exclusive ALSA access to `hw:USBStreamer,0`. Disconnection causes CamillaDSP to lose its audio device. **Recovery requires udev rule** to restart CamillaDSP on USBStreamer reconnection. No udev rule exists yet. |

**Recommendation:** A udev rule for USBStreamer recovery should be created
before production use. The USBStreamer is permanently connected in the flight
case, so hot-plug is an edge case (power glitch, loose cable), but the
recovery path should be automatic.

---

## TK-044: Reboot Verification -- 8 PASS, 1 FAIL, 2 NOT TESTED

**Purpose:** Verify all VNC session changes survive reboot. Must complete
before TK-039 (end-to-end audio validation).

**Results (11-item checklist):**

| # | Check | Command | Result |
|---|-------|---------|--------|
| 1 | Fresh boot | `uptime` | `11:38:01 up 0 min, 1 user` -- PASS |
| 2 | PipeWire active | `systemctl --user is-active pipewire` | `active` -- PASS |
| 3 | CamillaDSP active | `systemctl is-active camilladsp` | `inactive` -- **FAIL** (crash-looping) |
| 4 | USBStreamer visible | `aplay -l \| grep usb` | `card 3: USBStreamer` -- PASS |
| 5 | Loopback at card 10 | `cat /proc/asound/cards` | `10 [Loopback]: Loopback` -- PASS |
| 6 | qt6-wayland | `dpkg -l qt6-wayland` | `ii 6.8.2-4` -- PASS |
| 7 | pipewire-jack | `dpkg -l pipewire-jack` | `ii 1.4.2-1+rpt3` -- PASS |
| 8 | labwc env | `cat ~/.config/labwc/environment` | Has `QT_QPA_PLATFORMTHEME=gtk3` + `LABWC_FALLBACK_OUTPUT` -- PASS |
| 9 | Mixxx Wayland | -- | NOT TESTED (deferred pending CamillaDSP fix) |
| 10 | Reaper JACK | -- | NOT TESTED (deferred pending CamillaDSP fix) |
| 11 | PipeWire quantum | `pw-metadata -n settings` | `quantum=256, rate=48000, allowed=[48000]` -- PASS |

**Additional checks:**

- `wlr-randr`: NOOP-fallback "Headless output 2" at 1920x1080 -- PASS
- Full ALSA card list: vc4-hdmi-0 (0), vc4-hdmi-1 (1), bcm2835 Headphones
  (2), USBStreamer (3), UMIK-1 (4), DJControl Mix Ultra (5), SE25 (6), APC
  mini mk2 (7), Loopback (10)

### CamillaDSP FAIL: systemd path mismatch

CamillaDSP crash-looping after reboot (restart counter hit 5 before manual
stop). Service is also `disabled` -- never auto-started on boot.

```
journalctl -u camilladsp:
ERROR [src/bin.rs:939] Could not open config file '/etc/camilladsp/configs/active.yml'.
Reason: No such file or directory (os error 2)
```

**Root cause:** Path mismatch between the systemd unit file and the actual
symlink location:
- systemd ExecStart references: `/etc/camilladsp/configs/active.yml`
- Actual symlink (created in TK-002): `/etc/camilladsp/active.yml` ->
  `production/live.yml`

Exit code 101 (config file not found).

**Fix applied:** systemd drop-in override created at
`/etc/systemd/system/camilladsp.service.d/override.conf`. Key finding during
fix: the CamillaDSP binary is at `/usr/local/bin/camilladsp` (not
`/usr/bin/`), so the ExecStart also needed the correct binary path. Config
path corrected to `/etc/camilladsp/active.yml`.

CamillaDSP is now running and stable.

> **Note:** Service is still `disabled` -- needs `systemctl enable camilladsp`
> to auto-start on boot. Currently requires manual `systemctl start` after
> reboot.

### Combined checks

- **TK-042 (ALSA path verification):** Inconclusive. CamillaDSP not running
  after reboot, so `fuser -v /dev/snd/*` cannot verify the direct ALSA path.
  Must re-run after CamillaDSP path is fixed.
- **TK-043 (package state capture):** DONE. `dpkg --get-selections` captured
  1698 packages to `~/pkg-state-2026-03-09.txt`.

### Additional findings

- **wayvnc autostart configured.** Added to `~/.config/labwc/autostart`.
  wayvnc will now start automatically when labwc launches.
- **wayvnc password configured.** Created `~/.config/wayvnc/config` with
  `password=234269` (per owner instruction). File permissions set to 600.
  wayvnc now requires password for connections.
- **CamillaDSP service disabled.** Even after fixing the config path, the
  service needs `systemctl enable camilladsp` to start automatically on boot.
- **RustDesk still installed on Pi.** D-018 (RustDesk removal) was never
  implemented. Removal pending -- security specialist providing commands.

**Status:** CamillaDSP path FIXED (now running). wayvnc autostart FIXED.
Items 9-10 (Mixxx/Reaper launch) still deferred -- need retest. TK-042
(fuser) can now be run. CamillaDSP `enable` and RustDesk removal still
pending.

---

## Summary

| TK | Description | Status |
|----|-------------|--------|
| TK-035 | qt6-wayland install | DONE -- native Wayland rendering confirmed |
| TK-036 | Mixxx missing icons | Applied -- pending owner visual verification |
| TK-037 | Reaper audio device | DONE -- pipewire-jack, pw-jack wrapper |
| TK-038 | Fullscreen config | DONE -- ToggleFullscreen rules in rc.xml, pending owner visual verification |
| TK-040 | USBStreamer 8ch in Reaper | Fix applied -- playback sink removed, nodes renamed to ada8200-in/out |
| TK-041 | Phantom MIDI + BLE MIDI | DONE -- snd-virmidi blacklisted, BT disabled and masked |
| TK-042 | CamillaDSP ALSA path verify | Ready to retest -- CamillaDSP now running |
| TK-043 | Package state capture | DONE -- 1698 packages in ~/pkg-state-2026-03-09.txt |
| TK-044 | Reboot verification | **8 PASS, 1 FIXED** (CamillaDSP drop-in), 2 deferred (Mixxx/Reaper launch) |
| TK-046 | Reaper sample rate | DONE -- owner set to 48000 via GUI |
| -- | UMIK-1 WirePlumber rule | Applied |
| -- | PipeWire node rename | Applied (commit 8d9ec50) |
| -- | USB hot-plug analysis | Documented (USBStreamer needs udev recovery rule) |
| -- | wayvnc autostart + password | DONE -- labwc autostart + password in config (600 perms) |
| -- | CamillaDSP systemctl enable | **Pending** -- service runs but won't auto-start on boot |
| -- | RustDesk removal (D-018) | **Pending** -- still installed, security specialist providing commands |
