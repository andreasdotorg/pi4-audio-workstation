# US-059 PipeWire Filter-Chain Configuration Reference

Complete configuration reference for the PipeWire filter-chain convolver
architecture (D-040). Consolidates information from GM-12, C-005, C-006,
C-007, and the production configuration files. Addresses DoD #14 requirement:
"filter-chain config" documentation.

**Evidence basis:** Production configuration files (`configs/pipewire/`),
lab notes from sessions GM-12, C-005, C-006, C-007.

### Context

| Item | Reference |
|------|-----------|
| Decision | D-040: Abandon CamillaDSP, pure PipeWire filter-chain pipeline |
| Benchmark | BM-2: PW convolver 1.70% CPU q1024, 3.47% q256 |
| DJ stability | GM-12: 11+ hours, zero xruns |
| Latency | C-006: ~12.3ms round-trip at q256, ~43ms at q1024 |
| Architecture | `docs/architecture/rt-audio-stack.md` |

### Reproducibility

| Role | Path |
|------|------|
| Global audio settings | `configs/pipewire/10-audio-settings.conf` -> `~/.config/pipewire/pipewire.conf.d/` (on Pi) |
| USBStreamer capture | `configs/pipewire/20-usbstreamer.conf` -> `~/.config/pipewire/pipewire.conf.d/` (on Pi) |
| USBStreamer playback | `configs/pipewire/21-usbstreamer-playback.conf` -> `~/.config/pipewire/pipewire.conf.d/` (on Pi) |
| Convolver filter-chain | `configs/pipewire/30-filter-chain-convolver.conf` -> `~/.config/pipewire/pipewire.conf.d/` (on Pi) |
| FIR coefficients | `/etc/pi4audio/coeffs/combined_{left_hp,right_hp,sub1_lp,sub2_lp}.wav` (on Pi) |

---

## 1. Configuration File Overview

All PipeWire configuration lives in `~/.config/pipewire/pipewire.conf.d/` on
the Pi, loaded as drop-in files by the system PipeWire instance. No
infrastructure modules or external services are required.

### File Loading Order

Files are loaded in lexicographic order. The numbering prefix controls
precedence:

| File | Purpose | Load Order |
|------|---------|------------|
| `10-audio-settings.conf` | Global audio clock: sample rate, quantum range | First |
| `20-usbstreamer.conf` | ADA8200 capture adapter (8ch input via ADAT) | Second |
| `21-usbstreamer-playback.conf` | USBStreamer playback adapter (8ch output via ADAT) | Third |
| `25-loopback-8ch.conf` | ALSA Loopback (legacy, pre-D-040) | Fourth |
| `30-filter-chain-convolver.conf` | FIR convolver + gain nodes (4ch) | Fifth |

Post-D-040, the `25-loopback-8ch.conf` is unused (CamillaDSP stopped). The
active pipeline uses files 10, 20, 21, and 30.

---

## 2. Global Audio Settings (`10-audio-settings.conf`)

```
context.properties = {
    default.clock.rate          = 48000
    default.clock.quantum       = 256
    default.clock.min-quantum   = 256
    default.clock.max-quantum   = 1024
    default.clock.force-quantum = 256
}
```

| Property | Value | Notes |
|----------|-------|-------|
| `default.clock.rate` | 48000 | Fixed sample rate, matches USBStreamer and FIR coefficients |
| `default.clock.quantum` | 256 | Default quantum (live mode) |
| `default.clock.min-quantum` | 256 | Prevents PipeWire from negotiating below 256 |
| `default.clock.max-quantum` | 1024 | Allows DJ mode at quantum 1024 |
| `default.clock.force-quantum` | 256 | Forces quantum 256 at startup |

**Quantum switching:** DJ mode uses quantum 1024 (set at runtime via
`pw-metadata -n settings 0 clock.force-quantum 1024`). Live mode uses the
default quantum 256. The GraphManager's mode-switch logic handles quantum
transitions.

**Warning (TK-243):** The `force-quantum = 256` setting causes compositor
starvation when the system is in DJ mode — PW RT threads wake every 5.3ms,
starving the SCHED_OTHER labwc compositor. The quantum should be managed
dynamically, not forced at boot. See C-005 Finding 2.

---

## 3. ALSA Adapters

### 3.1 USBStreamer Playback (`21-usbstreamer-playback.conf`)

The USBStreamer playback adapter is the PipeWire graph driver — it sets the
quantum for the entire graph.

| Property | Value | Notes |
|----------|-------|-------|
| `node.name` | `alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0` | GraphManager matches on this |
| `api.alsa.path` | `hw:USBStreamer,0` | ALSA device path |
| `audio.format` | `S32LE` | 32-bit signed integer |
| `audio.rate` | 48000 | Matches global clock |
| `audio.channels` | 8 | Full 8-channel output via ADAT |
| `audio.position` | `[ AUX0 ... AUX7 ]` | AUX channel positions |
| `api.alsa.period-size` | 1024 | Must match quantum range |
| `api.alsa.period-num` | 3 | Triple buffering |
| `api.alsa.disable-batch` | true | Prevents ALSA batch scheduler adding latency |
| `node.driver` | true | This node drives the graph |
| `node.group` | `pi4audio.usbstreamer` | Groups with ada8200-in capture |
| `node.autoconnect` | false | GraphManager manages all links |
| `priority.driver` | 2000 | High driver priority |

**USB mode:** USB ASYNC with explicit feedback — the device provides its own
clock, the host adapts. This is the gold standard for USB audio (C-006
Finding 6.1).

### 3.2 ADA8200 Capture (`20-usbstreamer.conf`)

The ADA8200 capture adapter shares the same ADAT link as the USBStreamer
playback. It is a follower, not a driver.

| Property | Value | Notes |
|----------|-------|-------|
| `node.name` | `ada8200-in` | GraphManager matches on this |
| `api.alsa.path` | `hw:USBStreamer,0` | Same ALSA device, capture direction |
| `audio.channels` | 8 | Full 8-channel capture via ADAT |
| `node.driver` | false | Follower — scheduled by USBStreamer driver |
| `node.group` | `pi4audio.usbstreamer` | Same group as USBStreamer playback |
| `priority.driver` | 0 | Lowest priority (follower) |

**Driver grouping (C-005 Finding 13):** Both ALSA adapters share `node.group
= pi4audio.usbstreamer`. This ensures PipeWire schedules them within the
same graph cycle under a single driver. Without grouping, each device runs
as an independent driver with its own RT thread, doubling the RT scheduling
pressure and causing compositor starvation at quantum 256.

---

## 4. Filter-Chain Convolver (`30-filter-chain-convolver.conf`)

The filter-chain convolver is the core DSP component. It replaces
CamillaDSP's convolution stage with PipeWire's built-in
`libpipewire-module-filter-chain`.

### 4.1 Node Architecture

The filter-chain defines 8 internal nodes connected by 4 internal links:

```
                   Filter-Chain Internal Graph
                   ===========================

Input ports           Convolver nodes        Gain nodes          Output ports
(capture side)                                                   (playback side)

AUX0 ──> conv_left_hp  ──> gain_left_hp  ──> AUX0
AUX1 ──> conv_right_hp ──> gain_right_hp ──> AUX1
AUX2 ──> conv_sub1_lp  ──> gain_sub1_lp  ──> AUX2
AUX3 ──> conv_sub2_lp  ──> gain_sub2_lp  ──> AUX3
```

Each channel has two stages:
1. **Convolver** (`builtin/convolver`): FIR convolution with 16,384-tap
   combined crossover + room correction filter
2. **Gain node** (`builtin/linear`): Flat attenuation via `y = x * Mult + 0.0`

### 4.2 Convolver Nodes

| Node Name | FIR Coefficient File | Channel | Crossover Role |
|-----------|---------------------|---------|----------------|
| `conv_left_hp` | `combined_left_hp.wav` | AUX0 (ch 1) | Highpass + room correction for left main |
| `conv_right_hp` | `combined_right_hp.wav` | AUX1 (ch 2) | Highpass + room correction for right main |
| `conv_sub1_lp` | `combined_sub1_lp.wav` | AUX2 (ch 3) | Lowpass + room correction for sub 1 |
| `conv_sub2_lp` | `combined_sub2_lp.wav` | AUX3 (ch 4) | Lowpass + room correction for sub 2 |

**FIR coefficients:** Located at `/etc/pi4audio/coeffs/` on the Pi. Each WAV
file contains a combined minimum-phase FIR filter embedding:
- Crossover slope (highpass for mains, lowpass for subs)
- Room correction (per-channel)
- Speaker trim (-24 dB for mains, -6 dB mono-sum compensation + -24 dB trim
  for subs)

All coefficients are verified <= -0.5 dB peak per D-009 (cut-only correction
with safety margin).

**FFT engine:** FFTW3 single-precision with ARM NEON SIMD
(`libfftw3f.so.3`). Non-uniform partitioned convolution. CPU: 1.70% at
quantum 1024, 3.47% at quantum 256 (BM-2).

**Processing latency:** Zero additional quanta. The convolver processes within
the same PipeWire graph cycle as capture and playback (C-006 Key Finding).

### 4.3 Gain Nodes

| Node Name | Label | Mult (current) | Equivalent dB | Speaker |
|-----------|-------|----------------|---------------|---------|
| `gain_left_hp` | `linear` | 0.001 | -60 dB | CHN-50P left main |
| `gain_right_hp` | `linear` | 0.001 | -60 dB | CHN-50P right main |
| `gain_sub1_lp` | `linear` | 0.000631 | -64 dB | PS28 III sub 1 |
| `gain_sub2_lp` | `linear` | 0.000631 | -64 dB | PS28 III sub 2 |

**Why gain nodes exist:** PipeWire 1.4.9's builtin convolver silently ignores
the `config.gain` parameter (GM-12 Finding 4). The `linear` builtin provides
an alternative: `y = x * Mult + Add`, where Mult is the gain multiplier and
Add is a DC offset (always 0.0).

**Per-channel values (C-005 Finding 7):** Mains at -60 dB, subs at -64 dB.
The 4 dB offset reflects different speaker thermal limits:
- CHN-50P mains: 7W thermal limit, -31.9 dBFS thermal ceiling -> 28.1 dB margin
- PS28 III subs: 62W thermal limit, -24.8 dBFS thermal ceiling -> 39.2 dB margin

**Runtime adjustment:** Per-channel gain is adjustable via `pw-cli`:
```bash
# Find the gain node ID
pw-cli ls Node | grep -A1 gain_left_hp

# Set new Mult value (example: -50 dB = 0.00316)
pw-cli s <node-id> Props '{ params: [ "Mult", 0.00316 ] }'
```

**Safety rule (S-012):** Never increase gain (increase Mult) without explicit
owner confirmation. Gain decreases (lower Mult) are safe.

**Persistence:** Mult values in the `.conf` file persist across PipeWire
restarts. Runtime `pw-cli` changes are also persistent for the session but
revert to the `.conf` defaults on PipeWire restart.

### 4.4 Capture and Playback Properties

**Capture side (`pi4audio-convolver`):**

| Property | Value | Notes |
|----------|-------|-------|
| `node.name` | `pi4audio-convolver` | GraphManager matches on this |
| `media.class` | `Audio/Sink` | Receives audio from applications |
| `audio.channels` | 4 | AUX0-AUX3 (speaker channels only) |
| `audio.position` | `[ AUX0 AUX1 AUX2 AUX3 ]` | Mapped to convolver inputs |
| `node.autoconnect` | false | GraphManager manages all links |
| `session.suspend-timeout-seconds` | 0 | Never suspend |
| `node.pause-on-idle` | false | Never pause |

**Playback side (`pi4audio-convolver-out`):**

| Property | Value | Notes |
|----------|-------|-------|
| `node.name` | `pi4audio-convolver-out` | GraphManager matches on this |
| `node.passive` | true | Does not drive the graph |
| `audio.channels` | 4 | AUX0-AUX3 (speaker channels only) |
| `node.autoconnect` | false | GraphManager manages all links |

### 4.5 Internal Links

The filter-chain defines 4 internal links connecting convolver outputs to
gain node inputs:

```
conv_left_hp:Out  -> gain_left_hp:In
conv_right_hp:Out -> gain_right_hp:In
conv_sub1_lp:Out  -> gain_sub1_lp:In
conv_sub2_lp:Out  -> gain_sub2_lp:In
```

These are internal to the filter-chain module. They are NOT PipeWire graph
links — they cannot be seen or modified via `pw-link`. The external PipeWire
links (application -> convolver, convolver-out -> USBStreamer) are created by
GraphManager or manual `pw-link`.

---

## 5. Channel Assignment

| AUX Channel | ADA8200/USBStreamer Channel | Output | Routing |
|-------------|---------------------------|--------|---------|
| AUX0 | Ch 1 | Left wideband main | Through convolver (HP FIR) |
| AUX1 | Ch 2 | Right wideband main | Through convolver (HP FIR) |
| AUX2 | Ch 3 | Subwoofer 1 | Through convolver (LP FIR), L+R mono sum |
| AUX3 | Ch 4 | Subwoofer 2 | Through convolver (LP FIR), L+R mono sum |
| AUX4 | Ch 5 | Engineer headphone L | Direct bypass (no convolver) |
| AUX5 | Ch 6 | Engineer headphone R | Direct bypass (no convolver) |
| AUX6 | Ch 7 | Singer IEM L | Direct bypass (no convolver) |
| AUX7 | Ch 8 | Singer IEM R | Direct bypass (no convolver) |

Channels 4-7 (headphones and IEM) bypass the filter-chain entirely.
GraphManager links them directly from the application to the USBStreamer
output ports.

---

## 6. Known Issues and Workarounds

| Issue | Severity | Status | Workaround | Reference |
|-------|----------|--------|------------|-----------|
| `config.gain` silently ignored | High | Known (PW 1.4.9) | `linear` gain nodes in chain | GM-12 F4, TK-237 |
| `bq_lowshelf` at Freq=0 distorts | Medium | Known | Do not use for flat gain | C-005 F5, TK-247 |
| WP `channelVolumes` silences convolver | Medium | Open | `pw-cli s <id> Props '{ channelVolumes: [1.0, 1.0] }'` | C-005 F9, TK-246 |
| F-033: JACK bridge threads at SCHED_OTHER | High | Open | `chrt -f 80` on pw-REAPER TIDs | C-007, F-033 |
| `force-quantum = 256` causes compositor starvation | High | Fixed | Disabled service; use runtime `pw-metadata` | C-005 F2, TK-243 |

---

## 7. Performance Characteristics

### By Quantum

| Metric | q1024 (DJ) | q256 (Live) | Source |
|--------|-----------|-------------|--------|
| Convolver CPU | 1.70% | 3.47% | BM-2 |
| convolver-out B/Q | 0.15 | 0.60 (74C) / 0.10 (51C) | O-004, O-007, O-012 |
| PA path (one-way) | ~21ms | ~6.3ms | C-006 |
| Round-trip latency | ~43ms | ~12.3ms | C-006 |
| Xruns | 0 (11+ hr soak) | ~65-70 in 104 min (pre-FIFO) | GM-12 F12, O-007 |
| Graph deadline | 21.3ms | 5.3ms | 1024/48000, 256/48000 |

### Stability Requirements

| Condition | Status | Evidence |
|-----------|--------|----------|
| q1024 DJ mode | **Production-stable** | GM-12: 11+ hr, 0 xruns |
| q256 live mode (FIFO + fan) | **Under evaluation** | C-007: ERR stable at 23, B/Q=0.10 |
| q256 live mode (no FIFO) | Not stable | O-007: ~0.6 xruns/min |

---

## 8. Rollback Procedure: PW Filter-Chain to CamillaDSP

If the PW filter-chain architecture (D-040) needs to be reverted to the
previous CamillaDSP architecture, follow this procedure. The rollback
restores the dual-graph architecture: PipeWire -> ALSA Loopback -> CamillaDSP
-> USBStreamer.

**Safety warning:** Restoring CamillaDSP involves restarting PipeWire and
starting the CamillaDSP service. Both actions interrupt the USBStreamer audio
stream and may produce full-scale transients through the amplifier chain.
**Warn the owner and wait for confirmation that amplifiers are safe before
proceeding.** See `docs/operations/safety.md` Section 1.

### 8.1 Pre-Rollback Checklist

| # | Check | How |
|---|-------|-----|
| 1 | Owner confirms amps safe | Verbal/written confirmation |
| 2 | Note current git HEAD | `git rev-parse HEAD` (on dev machine) |
| 3 | Note PW filter-chain state | `pw-cli ls Node` (for reference) |

### 8.2 Rollback Steps (on Pi)

**Step 1: Stop audio applications.**
```bash
# Stop Mixxx/Reaper if running
pkill -x mixxx
pkill -x reaper
```

**Step 2: Remove the PW filter-chain config.**
```bash
rm ~/.config/pipewire/pipewire.conf.d/30-filter-chain-convolver.conf
```
This removes the convolver and gain nodes from the PipeWire graph.

**Step 3: Remove the USBStreamer playback adapter config.**
```bash
rm ~/.config/pipewire/pipewire.conf.d/21-usbstreamer-playback.conf
```
CamillaDSP accesses the USBStreamer playback direction directly via ALSA
(`hw:USBStreamer,0`). The PW adapter conflicts with CamillaDSP's ALSA access.

**Step 4: Restore the ALSA Loopback config (if removed).**
```bash
cp ~/mobile/gabriela-bogk/pi4-audio-workstation/configs/pipewire/25-loopback-8ch.conf \
   ~/.config/pipewire/pipewire.conf.d/25-loopback-8ch.conf
```
The loopback sink (`hw:Loopback,0,0`) bridges PipeWire to CamillaDSP.

**Step 5: Restart PipeWire.**
```bash
# SAFETY: Owner must confirm amps are safe before this step
systemctl --user restart pipewire.service
```

**Step 6: Start CamillaDSP.**
```bash
systemctl --user start camilladsp.service
# Verify it started at FIFO/80
chrt -p $(pgrep -x camilladsp)
```
CamillaDSP reads from `hw:Loopback,1,0` (capture side of the ALSA Loopback)
and writes to `hw:USBStreamer,0` (direct ALSA access, bypassing PipeWire).

**Step 7: Verify the signal path.**
```bash
# Check CamillaDSP is running and processing
systemctl --user status camilladsp.service

# Check PipeWire sees the loopback sink
pw-cli ls Node | grep loopback

# Check no filter-chain nodes remain
pw-cli ls Node | grep pi4audio-convolver
# Should return nothing
```

**Step 8: Re-apply quantum settings (if needed).**

CamillaDSP production configs use:
- DJ mode: `dj-pa.yml` with chunksize 2048, PW quantum 1024
- Live mode: `live.yml` with chunksize 256, PW quantum 256

Set the PipeWire quantum to match the CamillaDSP chunksize:
```bash
# DJ mode
pw-metadata -n settings 0 clock.force-quantum 1024

# Live mode
pw-metadata -n settings 0 clock.force-quantum 256
```

### 8.3 Rollback Verification

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | CamillaDSP running | `systemctl --user status camilladsp` | active (running) |
| 2 | CamillaDSP at FIFO/80 | `chrt -p $(pgrep -x camilladsp)` | SCHED_FIFO, priority 80 |
| 3 | Loopback sink present | `pw-cli ls Node \| grep loopback` | `loopback-8ch-sink` |
| 4 | No filter-chain nodes | `pw-cli ls Node \| grep pi4audio-convolver` | No output |
| 5 | No PW USBStreamer adapter | `pw-cli ls Node \| grep USBStreamer` | No output (or only capture) |
| 6 | Audio plays through speakers | Play test audio in Mixxx/Reaper | Audible output |

### 8.4 Reverting the Rollback (Back to PW Filter-Chain)

To return to the D-040 PW filter-chain architecture:

```bash
# Stop CamillaDSP
systemctl --user stop camilladsp.service

# Deploy PW configs from repo
cp ~/mobile/gabriela-bogk/pi4-audio-workstation/configs/pipewire/21-usbstreamer-playback.conf \
   ~/.config/pipewire/pipewire.conf.d/
cp ~/mobile/gabriela-bogk/pi4-audio-workstation/configs/pipewire/30-filter-chain-convolver.conf \
   ~/.config/pipewire/pipewire.conf.d/

# Remove loopback config (optional -- harmless if left)
rm ~/.config/pipewire/pipewire.conf.d/25-loopback-8ch.conf

# SAFETY: Owner must confirm amps are safe
systemctl --user restart pipewire.service

# Verify convolver nodes appear
pw-cli ls Node | grep pi4audio-convolver
```

### 8.5 Configuration Files Involved

| File | D-040 (PW filter-chain) | Pre-D-040 (CamillaDSP) |
|------|------------------------|----------------------|
| `30-filter-chain-convolver.conf` | Present (convolver + gain nodes) | Absent |
| `21-usbstreamer-playback.conf` | Present (PW owns USBStreamer playback) | Absent (CamillaDSP owns it) |
| `25-loopback-8ch.conf` | Unused (can be absent) | Present (PW -> Loopback bridge) |
| `20-usbstreamer.conf` | Present (ada8200-in capture) | Present (ada8200-in capture) |
| `10-audio-settings.conf` | Present (quantum config) | Present (quantum config) |
| CamillaDSP service | Stopped | Running at FIFO/80 |
| CamillaDSP config | N/A | `dj-pa.yml` or `live.yml` via `/etc/camilladsp/active.yml` |

### 8.6 Known Rollback Risks

1. **USBStreamer transients:** Restarting PipeWire and starting CamillaDSP
   both interrupt the USBStreamer audio stream. Amplifiers must be safe.

2. **Latency regression:** CamillaDSP adds 2 chunks of internal buffering
   plus the ALSA Loopback bridge. DJ-mode PA path increases from ~21ms to
   ~109ms. Live-mode PA path increases from ~6.3ms to ~31ms (projected).

3. **CPU regression:** CamillaDSP uses 3-5.6x more CPU than the PW
   filter-chain convolver (5.23% vs 1.70% at comparable buffer sizes).

4. **Gain staging difference:** PW filter-chain uses `linear` Mult nodes
   for per-channel gain. CamillaDSP uses its own mixer/gain configuration
   in the YAML config. The gain values are NOT equivalent -- CamillaDSP
   configs have their own attenuation baked into the mixer section.

5. **WirePlumber interaction:** WP's behavior with the ALSA Loopback sink
   may differ from its behavior with the filter-chain convolver sink. The
   `channelVolumes` interference (TK-246) may not apply, but other WP
   auto-linking behavior may cause issues.

---

## 9. Routing Policy

This section documents the complete PipeWire link topology per operating mode.
All links are created by GraphManager (or manually via `pw-link` when
GraphManager is not deployed). WirePlumber's auto-linking is suppressed for
application nodes to prevent bypass links (GM-12 Finding 11).

### 9.1 DJ Mode (Mixxx via `pw-jack`)

Mixxx registers 6 JACK output ports (`out_0` through `out_5`). No JACK input
ports are used in DJ mode. The routing topology was validated in GM-12.

**Application -> Convolver (PA channels):**

| Source Port | Destination Port | Content | Notes |
|-------------|-----------------|---------|-------|
| `Mixxx:out_0` | `pi4audio-convolver:playback_AUX0` | Left master | Stereo L to left main HP FIR |
| `Mixxx:out_1` | `pi4audio-convolver:playback_AUX1` | Right master | Stereo R to right main HP FIR |
| `Mixxx:out_0` | `pi4audio-convolver:playback_AUX2` | Left master (mono sum) | L component to sub1 LP FIR |
| `Mixxx:out_1` | `pi4audio-convolver:playback_AUX2` | Right master (mono sum) | R component to sub1 LP FIR |
| `Mixxx:out_0` | `pi4audio-convolver:playback_AUX3` | Left master (mono sum) | L component to sub2 LP FIR |
| `Mixxx:out_1` | `pi4audio-convolver:playback_AUX3` | Right master (mono sum) | R component to sub2 LP FIR |

**Convolver -> USBStreamer (PA output):**

| Source Port | Destination Port | Content |
|-------------|-----------------|---------|
| `pi4audio-convolver-out:capture_AUX0` | `USBStreamer:playback_AUX0` | Left main (HP filtered) |
| `pi4audio-convolver-out:capture_AUX1` | `USBStreamer:playback_AUX1` | Right main (HP filtered) |
| `pi4audio-convolver-out:capture_AUX2` | `USBStreamer:playback_AUX2` | Sub 1 (LP filtered, mono sum) |
| `pi4audio-convolver-out:capture_AUX3` | `USBStreamer:playback_AUX3` | Sub 2 (LP filtered, mono sum, phase-inverted) |

**Direct bypass (headphones):**

| Source Port | Destination Port | Content |
|-------------|-----------------|---------|
| `Mixxx:out_4` | `USBStreamer:playback_AUX4` | Engineer headphone L |
| `Mixxx:out_5` | `USBStreamer:playback_AUX5` | Engineer headphone R |

**Total DJ mode links:** 12 (6 app->convolver + 4 convolver->USBStreamer + 2 headphone bypass)

**Mono sum mechanism:** PipeWire natively sums multiple inputs connected to the
same port. Both `Mixxx:out_0` (L) and `Mixxx:out_1` (R) are linked to
`pi4audio-convolver:playback_AUX2`, and PipeWire produces the arithmetic sum
at the convolver input. No explicit mixer node is needed. This is documented
in GM-12 Finding 5.

**WirePlumber bypass hazard (GM-12 Finding 11):** WirePlumber auto-links JACK
clients to the default sink. When Mixxx connects, WP may create direct links
(`Mixxx:out_0-3 -> USBStreamer:playback_AUX0-3`) that bypass the convolver.
This causes double-signal (processed + raw) on speakers -- garbled audio.
These bypass links must be prevented (WP linking rule) or removed (`pw-link
-d`). GraphManager's reconciler should detect and remove bypass links on
speaker channels (AUX0-3).

### 9.2 Live Mode (Reaper via `pw-jack`)

Reaper registers JACK output ports for each track/bus output. The exact port
names depend on the Reaper project configuration. Live mode uses the same PA
routing as DJ mode (convolver channels AUX0-3) plus singer IEM on AUX6-7.

**Application -> Convolver (PA channels):**

Same structure as DJ mode. Reaper's master output ports are linked to the
convolver inputs with identical mono-sum topology for subs.

| Source Port | Destination Port | Content |
|-------------|-----------------|---------|
| `REAPER:out_0` | `pi4audio-convolver:playback_AUX0` | Left master |
| `REAPER:out_1` | `pi4audio-convolver:playback_AUX1` | Right master |
| `REAPER:out_0` | `pi4audio-convolver:playback_AUX2` | Left (mono sum for sub1) |
| `REAPER:out_1` | `pi4audio-convolver:playback_AUX2` | Right (mono sum for sub1) |
| `REAPER:out_0` | `pi4audio-convolver:playback_AUX3` | Left (mono sum for sub2) |
| `REAPER:out_1` | `pi4audio-convolver:playback_AUX3` | Right (mono sum for sub2) |

**Convolver -> USBStreamer:** Identical to DJ mode (4 links).

**Direct bypass (headphones + IEM):**

| Source Port | Destination Port | Content | Notes |
|-------------|-----------------|---------|-------|
| `REAPER:out_4` | `USBStreamer:playback_AUX4` | Engineer headphone L | Direct bypass |
| `REAPER:out_5` | `USBStreamer:playback_AUX5` | Engineer headphone R | Direct bypass |
| `REAPER:out_6` | `USBStreamer:playback_AUX6` | Singer IEM L | Direct bypass, live mode only |
| `REAPER:out_7` | `USBStreamer:playback_AUX7` | Singer IEM R | Direct bypass, live mode only |

**Capture links (when active):**

| Source Port | Destination Port | Content |
|-------------|-----------------|---------|
| `ada8200-in:capture_AUX0` | `REAPER:in_0` | Vocal mic (ADA8200 ch 1) |
| `ada8200-in:capture_AUX1` | `REAPER:in_1` | Spare mic/line (ADA8200 ch 2) |

**Total live mode links:** Up to 22 as counted by `pw-link -l` (6 app->convolver
+ 4 convolver->USBStreamer + 4 headphone/IEM bypass + 2 capture + 4 filter-chain
internal links + 2 ada8200 capture internal). The 22-link topology was validated
in C-005 Finding 13 with zero compositor starvation after the `node.group` fix.

**Singer IEM signal path:** The IEM channels (AUX6/AUX7) bypass the convolver
entirely. The singer hears Reaper's direct mix output with no FIR processing
-- only the ~5.3ms PipeWire graph latency at quantum 256. Post-D-040, IEM
channels no longer route through any DSP engine. The singer also hears the PA
acoustically; at quantum 256, the PA path (~6.3ms) is well below the ~25ms
slapback threshold (C-006, D-011).

### 9.3 Port Name Convention

JACK clients (Mixxx, Reaper) use port names: `out_0`, `out_1`, ... `out_N`
for outputs and `in_0`, `in_1`, ... `in_N` for inputs. These are the names
visible in `pw-jack jack_lsp` and used by `pw-link`.

PipeWire nodes use AUX-indexed port names:
- Convolver capture: `pi4audio-convolver:playback_AUX0` through `playback_AUX3`
- Convolver output: `pi4audio-convolver-out:capture_AUX0` through `capture_AUX3`
- USBStreamer playback: `USBStreamer:playback_AUX0` through `playback_AUX7`
- ada8200-in capture: `ada8200-in:capture_AUX0` through `capture_AUX7`

**GraphManager port name issue (GM-12 Finding 7):** `routing.rs` generates
port names as `output_AUX0`, but JACK clients use `out_0`. This mismatch
blocks automated routing until the code is fixed.

### 9.4 Link Lifecycle

Links are managed by GraphManager (or manually when GM is not deployed):

1. **Mode switch (DJ -> Live or vice versa):** GraphManager destroys all
   existing application links, then creates new links matching the target
   mode topology. The quantum is switched via `pw-metadata -n settings 0
   clock.force-quantum <value>`.

2. **Application reconnect (crash/restart):** When a JACK client reconnects,
   PipeWire creates new node/port objects. GraphManager must detect the new
   client and re-establish links. WirePlumber may race to create bypass links
   first (Finding 11 hazard).

3. **Convolver -> USBStreamer links:** These are persistent across mode
   switches -- the convolver output always feeds USBStreamer AUX0-3 regardless
   of which application is active.

4. **Capture links:** Only active in live mode when Reaper needs mic input.
   Not created in DJ mode.

### 9.5 Forbidden Links

The following link patterns must never exist simultaneously with the convolver
routing:

| Forbidden Pattern | Risk | Detection |
|-------------------|------|-----------|
| `Mixxx:out_0-3 -> USBStreamer:playback_AUX0-3` | Double-signal on speakers (processed + raw) | `pw-link -l \| grep -E "Mixxx.*USBStreamer.*AUX[0-3]"` |
| `REAPER:out_0-3 -> USBStreamer:playback_AUX0-3` | Same double-signal risk | `pw-link -l \| grep -E "REAPER.*USBStreamer.*AUX[0-3]"` |
| Any source -> `USBStreamer:playback_AUX0-3` (not from convolver-out) | Bypasses crossover + room correction | Audit `pw-link -l` for unexpected sources on AUX0-3 |

GraphManager should detect and remove these as part of its reconciliation
loop. Until GM is deployed, manual verification via `pw-link -l` is required
after any application connect/reconnect event.

---

## 10. Cross-References

| Document | Covers |
|----------|--------|
| `docs/architecture/rt-audio-stack.md` | Architecture diagrams, RT priority hierarchy, executive summary |
| `docs/lab-notes/GM-12-dj-stability-pw-filter-chain.md` | DJ stability test, gain workaround, sub routing, WP issues |
| `docs/lab-notes/change-C-005-live-mode-investigation.md` | Gain control investigation, thermal safety, node.group, S-012 |
| `docs/lab-notes/change-C-006-q256-latency-characterization.md` | Latency at q1024 and q256, CPU performance, xrun analysis |
| `docs/lab-notes/change-C-007-reaper-fifo-promotion.md` | FIFO scheduling for JACK bridge threads, F-033 |
| `docs/lab-notes/LN-BM2-pw-filter-chain-benchmark.md` | CPU benchmark: PW convolver vs CamillaDSP |
| `docs/operations/safety.md` | Transient risk, gain staging limits, measurement safety |
| `docs/project/defects.md` | F-033 (JACK thread promotion), F-020 (PW daemon promotion) |

---

**Date:** 2026-03-17
**Documented by:** technical-writer (consolidation of GM-12, C-005, C-006, C-007 data)
