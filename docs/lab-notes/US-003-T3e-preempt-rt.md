# US-003 T3e: PREEMPT_RT Kernel Validation

The project's real-time classification changed from soft to hard real-time with
human safety implications (D-013). The system drives amplifiers capable of
producing SPL levels that can cause permanent hearing damage, making scheduling
determinism a safety requirement. Stock PREEMPT provides good average
scheduling but no formal worst-case bound -- US-003 T3c confirmed a
steady-state underrun at quantum 128, demonstrating that the stock kernel
cannot guarantee the 5.33ms processing deadline under all conditions.

This test validates the PREEMPT_RT kernel on the production system: install the
RT kernel package, verify that all audio infrastructure starts and functions
correctly, then run a 30-minute stability test with concurrent cyclictest to
measure worst-case scheduling latency under sustained DSP load.

---

## Phase 1: RT Kernel Installation

**Date:** 2026-03-08
**Operator:** Claude (automated via change-manager)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8 (stock PREEMPT), aarch64

### Pre-conditions

- Previous kernel: `6.12.47+rpt-rpi-v8` with `CONFIG_PREEMPT=y`
- Target kernel: `6.12.47+rpt-rpi-v8-rt` with `CONFIG_PREEMPT_RT=y`
- Same kernel version (6.12.47) -- zero-risk package install with stock kernel
  retained as fallback

### Procedure

```bash
# Step 1: Install RT kernel package
$ sudo apt install linux-image-6.12.47+rpt-rpi-v8-rt linux-headers-6.12.47+rpt-rpi-v8-rt
```

```bash
# Step 2: Configure boot to use RT kernel
$ sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.bak-pre-rt
$ echo "kernel=kernel8_rt.img" | sudo tee -a /boot/firmware/config.txt
```
Backup created at `config.txt.bak-pre-rt`. Stock kernel remains on the SD card
and can be restored by removing the `kernel=` line.

```bash
# Step 3: Reboot
$ sudo reboot
```
Reboot successful.

```bash
# Step 4: Verify RT kernel loaded
$ uname -r
6.12.47+rpt-rpi-v8-rt
```

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| RT kernel installed | `linux-image-*-rt` package | Installed | PASS |
| Boot config backup | `config.txt.bak-pre-rt` exists | Created | PASS |
| Reboot successful | System boots to RT kernel | Booted | PASS |
| Kernel version | `6.12.47+rpt-rpi-v8-rt` | `6.12.47+rpt-rpi-v8-rt` | PASS |

---

## Phase 2: Smoke Test (6/6 PASS)

**Date:** 2026-03-08
**Operator:** Claude (automated via change-manager)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.47+rpt-rpi-v8-rt (PREEMPT_RT), aarch64

### Procedure

Verified all audio infrastructure starts and functions correctly on the RT
kernel. Each check targets a different layer of the audio stack.

```bash
# Check 1: PipeWire running
$ systemctl --user status pipewire
Active: active (running)
```

```bash
# Check 2: 8ch Loopback JACK ports
$ pw-jack jack_lsp 2>/dev/null | grep -i "camilladsp"
CamillaDSP 8ch Input:playback_AUX0
CamillaDSP 8ch Input:playback_AUX1
CamillaDSP 8ch Input:playback_AUX2
CamillaDSP 8ch Input:playback_AUX3
CamillaDSP 8ch Input:playback_AUX4
CamillaDSP 8ch Input:playback_AUX5
CamillaDSP 8ch Input:playback_AUX6
CamillaDSP 8ch Input:playback_AUX7
CamillaDSP 8ch Input:monitor_AUX0
... (8 more monitor ports)
```
All 8 playback + 8 monitor ports visible via JACK bridge.

```bash
# Check 3: CamillaDSP config validates
$ camilladsp -c /etc/camilladsp/production/live.yml
Config is valid
```

```bash
# Check 4: CamillaDSP running state
$ python3 -c "from camilladsp import CamillaClient; c = CamillaClient('127.0.0.1', 1234); c.connect(); print(c.general.state(), c.status.processing_load())"
ProcessingState.RUNNING 17.6
```
CamillaDSP in RUNNING state with 17.6% processing load.

```bash
# Check 5: ALSA devices
$ cat /proc/asound/cards | grep -E "USBStreamer|Loopback"
 3 [USBStreamer     ]: USB-Audio - USBStreamer
10 [Loopback       ]: Loopback - Loopback
```
Both present -- USBStreamer (card 3) and Loopback (card 10).

```bash
# Check 6: MIDI devices
$ cat /proc/asound/cards | grep -E "Hercules|SE25|APCmini"
 5 [... ]: ... - Hercules DJControl Mix Ultra
 6 [... ]: ... - Nektar SE25
 7 [... ]: ... - Akai APCmini mk2
```
All three MIDI controllers enumerated: Hercules (hw:5), SE25 (hw:6),
APCmini (hw:7).

### Validation

| Check | Expected | Actual | Pass/Fail |
|-------|----------|--------|-----------|
| PipeWire running | active | active (running) | PASS |
| 8ch Loopback JACK ports | 8 playback ports | 8 playback + 8 monitor | PASS |
| CamillaDSP config validates | "Config is valid" | "Config is valid" | PASS |
| CamillaDSP RUNNING state | ProcessingState.RUNNING | RUNNING, 17.6% load | PASS |
| ALSA devices | USBStreamer + Loopback | Both present (card 3, card 10) | PASS |
| MIDI devices | 3 controllers | Hercules (hw:5), SE25 (hw:6), APCmini (hw:7) | PASS |

### Deviations from Plan

Startup buffer underrun on CamillaDSP at chunksize 256 -- same behavior as
stock PREEMPT kernel (observed in US-001 T1c and US-028 T5). This is a known
transient during pipeline initialization, not a regression. Resolves
immediately once the processing loop stabilizes.

---

## Phase 3: 30-Minute Stability Test + Cyclictest

**Date:** 2026-03-08
**Status:** Running. Results pending.

Phase 3 runs a 30-minute sustained DSP load test (CamillaDSP with live.yml at
chunksize 256) concurrent with `cyclictest` to measure worst-case scheduling
latency under the PREEMPT_RT kernel. This is the validation that D-013
requires before the system can be connected to amplifiers at a venue.

*Results will be added when Phase 3 completes.*

---

## Notes

- The RT kernel is the same version (6.12.47) as the stock kernel, installed
  from the Trixie repository as a standard package. No custom kernel build was
  required.
- Stock PREEMPT kernel retained on the SD card as fallback for development and
  benchmarking. Reverting requires removing `kernel=kernel8_rt.img` from
  `/boot/firmware/config.txt` and rebooting.
- Phase 2 processing load (17.6%) is consistent with benchmark-configuration
  figures from US-001. Production 8-channel load is approximately 34% (see
  US-028 T5).
