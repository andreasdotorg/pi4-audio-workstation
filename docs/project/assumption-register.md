# Assumption Register

Comprehensive register of all assumptions the project relies on. Includes the
original A1-A8 from CLAUDE.md plus expanded assumptions A9-A28 discovered
through the Advocatus Diaboli audit (US-004).

Each assumption has: ID, description, confidence level, validation method,
affected decisions/stories, and current status.

**Confidence levels:** VALIDATED, HIGH, MEDIUM, LOW, UNKNOWN
**Status:** open, validated, invalidated, superseded, partially-resolved

---

## Original Assumptions (A1-A8)

| ID | Assumption | Confidence | Validation | Affects | Status |
|----|-----------|------------|------------|---------|--------|
| A1 | 16k taps @ quantum 1024 fits in Pi 4 CPU budget alongside Mixxx | VALIDATED | BM-2 (D-040): 1.70% CPU with PW filter-chain convolver at quantum 1024. GM-12: 58% idle with Mixxx + convolver. Previous: T1a (US-001) 5.23% via CamillaDSP at chunksize 2048. | D-003, D-040, US-001 | validated — dramatically improved by D-040 architecture |
| A2 | 16k taps @ quantum 256 fits in Pi 4 CPU budget alongside Reaper | VALIDATED | BM-2 (D-040): 3.47% CPU with PW filter-chain convolver at quantum 256. Previous: T1b (US-001) 10.42% at chunksize 512, T1c 19.25% at chunksize 256 via CamillaDSP. | D-003, D-040, D-011, US-001 | validated — dramatically improved by D-040 architecture |
| A3 | End-to-end PA latency in live mode < 25ms | VALIDATED | D-040: ~5.3ms theoretical at quantum 256 with PW filter-chain (convolver in-graph, no loopback). Previous: T2b (US-002) 30.3ms at chunksize 512 (CamillaDSP/loopback, pre-D-040). Formal measurement pending but architecture guarantees sub-25ms. | D-002, D-011, D-040, US-002 | validated — D-040 architecture exceeds target by 4x |
| A4 | Pi 4 thermals stay below 75C in flight case under sustained load | LOW | T4 (US-003), D-012. D-012 mitigation designed but T4 validation pending. | D-003, D-012, flight case design | open — active cooling mandatory per D-012 |
| A5 | 16k-tap FIR actually provides effective correction at 20Hz | MEDIUM | T5 (US-013) | D-003, US-013 | open |
| A6 | Hercules DJControl Mix Ultra presents as USB-MIDI on Linux | VALIDATED | US-005 DONE. Owner actively DJs with the Hercules over USB-MIDI (GM-12 session). | US-005, US-006 | validated |
| A7 | Mixxx runs adequately on Pi 4 with labwc Wayland and hardware V3D GL | VALIDATED | US-006 DONE. Hardware V3D GL on PREEMPT_RT (D-022), ~85% CPU. GM-12: 40+ min DJ session, zero xruns, 58% idle. | US-006, D-022 | validated |
| A8 | APCmini mk2 Mixxx mapping exists or can be created | UNKNOWN | Research (US-007) | US-007 | open |

---

## Expanded Assumptions (A9-A28) — from US-004 Audit

### A9 [HIGH]: Hardcoded ALSA device paths assume stable card numbering

**Description:** CamillaDSP configs and PipeWire configs use `hw:1,0` for the
USBStreamer. The udev rule (SETUP-MANUAL.md line 480) uses
`ATTR{number}="1"` which is non-standard syntax for ALSA card index
assignment. If USB enumeration order changes (e.g., UMIK-1 plugged in first),
card numbers shift and CamillaDSP/PipeWire break silently.

**Confidence:** MEDIUM — udev rule may work but syntax is suspect
**Validation:** Verify udev rule pins card index reliably across reboots with
varying USB plug order. Consider using `hw:USBStreamer,0` by ALSA card name
instead of numeric index.
**Affects:** US-000 (installation), all CamillaDSP configs, all PipeWire configs
**Status:** partially-resolved — `hw:USBStreamer,0` by-name addressing applied in US-000b

---

### A10 [HIGH]: systemd service user mismatch — User=pi vs actual user ela

**Description:** SETUP-MANUAL.md systemd services use `User=pi` and paths
like `/home/pi/bin/`. The actual Pi user is `ela` (confirmed in CLAUDE.md:
`ela@192.168.178.185`). All systemd services, script paths, and home
directory references must be updated. PipeWire runs as a user session under
`ela`, not `pi`.

**Confidence:** HIGH — confirmed wrong, now fixed
**Validation:** All user references corrected to `ela` in US-000.
**Affects:** US-000 (was blocking), US-021 (mode switching), section 10 (headless operation)
**Status:** validated — all paths corrected to `ela` in US-000

---

### A11 [HIGH]: All 8 channels must route through CamillaDSP — SUPERSEDED

**Description:** Originally documented as "IEM channels 5-8 bypass CamillaDSP
and route directly via PipeWire to the USBStreamer." D-011 discovered that
CamillaDSP holds exclusive ALSA access to all 8 USBStreamer channels. IEM
and headphone channels must transit CamillaDSP as passthrough (no FIR
processing). This changes the routing architecture fundamentally.

**Confidence:** VALIDATED — confirmed by D-011 investigation
**Validation:** Already validated. CamillaDSP configs must be updated to 8-channel
output with passthrough on channels 5-8.
**Affects:** D-011 (supersedes D-002), US-017 (IEM routing), SETUP-MANUAL.md (all signal flow diagrams)
**Status:** superseded — Superseded by D-040: CamillaDSP abandoned in favor of PipeWire filter-chain. PipeWire natively manages all channel routing without exclusive ALSA access constraints. IEM channels route via direct PipeWire links to USBStreamer output ports.

---

### A12 [HIGH]: CamillaDSP websocket API coefficient hot-swap capability unknown — SUPERSEDED

**Description:** CLAUDE.md open questions asks "can we update coefficients
without restarting the service?" US-012 says "restarts CamillaDSP or
hot-swaps via websocket API if available." The code example in
SETUP-MANUAL.md shows `client.config.set_active()` for delay/gain changes,
but changing filter WAV files may require a full restart, causing an audible
gap during room correction deployment.

**Confidence:** LOW — API capability unknown
**Validation:** Research CamillaDSP v3 API documentation for coefficient reload.
Test with pycamilladsp. Add to US-000 DoD.
**Affects:** US-012 (automation script), US-023 (engineer dashboard)
**Status:** superseded — Superseded by D-040: CamillaDSP abandoned in favor of PipeWire filter-chain. Filter coefficient deployment is now via PipeWire filter-chain config reload, not CamillaDSP websocket API.

---

### A13 [HIGH]: PipeWire quantum vs CamillaDSP chunksize alignment — SUPERSEDED

**Description:** PipeWire config allows dynamic quantum range 128-1024. If
PipeWire quantum exceeds CamillaDSP chunksize, buffer underruns occur. D-011
specifies quantum 256 for live mode and 1024 for DJ mode. The mode-switching
script must change PipeWire quantum alongside CamillaDSP chunksize atomically.
If PipeWire's dynamic quantum negotiation overrides the configured value,
the alignment breaks.

**Confidence:** MEDIUM — D-011 addresses the target values but PipeWire dynamic
behavior is not fully characterized
**Validation:** Pin PipeWire quantum per mode. Verify PipeWire does not
dynamically override. Test mode switching atomicity.
**Affects:** D-002, D-011, US-002, US-003, US-021
**Status:** superseded — Superseded by D-040: CamillaDSP abandoned in favor of PipeWire filter-chain. The quantum/chunksize alignment problem no longer exists — the convolver runs in the PipeWire graph at the graph quantum. Only PipeWire quantum needs to be set per mode (1024 DJ, 256 live) via `pw-metadata`.

---

### A14 [MEDIUM]: Bluetooth disabled in config.txt but Hercules may need it

**Description:** SETUP-MANUAL.md disables Bluetooth (`dtoverlay=disable-bt`)
for audio optimization. The Hercules DJControl Mix Ultra is Bluetooth-primary.
If USB-MIDI doesn't work (A6 UNKNOWN), Bluetooth is the only fallback path,
but it's been disabled at the hardware level.

**Confidence:** HIGH this is a sequencing conflict
**Validation:** Do NOT disable Bluetooth until A6 (USB-MIDI) is validated.
US-005 must complete before Bluetooth disable is applied.
**Affects:** A6, US-005
**Status:** superseded — D-019: Bluetooth scrapped for production. No BT fallback. If USB-MIDI fails, Hercules is dropped entirely.

---

### A15 [MEDIUM]: Xvfb systemd unit has a bug preventing headless Mixxx — SUPERSEDED

**Description:** SETUP-MANUAL.md line 1757 uses
`ExecStartPre=/usr/bin/Xvfb :99 -screen 0 1024x768x24 &` — the trailing
`&` does not work in ExecStartPre. systemd does not support shell
backgrounding in Exec directives. Xvfb will be killed when ExecStartPre
completes, and Mixxx will fail to find DISPLAY=:99.

**Confidence:** HIGH this is a bug
**Validation:** Fix Xvfb startup: use a separate systemd service for Xvfb,
use Type=forking, or use the `xvfb-run` wrapper.
**Affects:** US-006 (Mixxx feasibility), US-021 (mode switching)
**Status:** superseded — Superseded by D-022: Xvfb replaced by labwc Wayland compositor with hardware V3D GL. Mixxx runs natively under labwc, no Xvfb needed.

---

### A16 [MEDIUM]: gpu_mem=16 conflicts with Mixxx gpu_mem=128 requirement — SUPERSEDED

**Description:** SETUP-MANUAL.md section 3.2 sets `gpu_mem=16` for headless
audio. Section 7.1 says "Keep gpu_mem=128 if running Mixxx." Both cannot be
active simultaneously — config.txt has one value. Mode switching would require
editing config.txt and rebooting, which is not documented.

**Confidence:** HIGH this is a contradiction
**Validation:** Determine a single gpu_mem value that works for both modes.
Test Mixxx with gpu_mem=16 via Xvfb (may not need GPU rendering if headless).
Alternatively, set gpu_mem=128 permanently (sufficient for audio too).
**Affects:** US-006 (Mixxx feasibility), US-021 (mode switching), A7
**Status:** superseded — Superseded by D-022: hardware V3D GL compositor resolves the gpu_mem conflict. With labwc Wayland and hardware V3D GL, a single gpu_mem value works for both modes.

---

### A17 [MEDIUM]: CamillaDSP pre-built binary uses ALSA backend only — SUPERSEDED

**Description:** Pre-built CamillaDSP aarch64 binary includes only ALSA
backend, not JACK or PulseAudio. The current architecture uses ALSA loopback,
so this is fine. But if the architecture changes to use CamillaDSP's JACK
backend (eliminating the loopback device), a source build with JACK/NEON
flags would be required.

**Confidence:** HIGH — correct for current architecture
**Validation:** Document in US-000 that ALSA-only binary is sufficient for the
loopback architecture. Flag as a constraint if architecture changes.
**Affects:** US-000
**Status:** superseded — Superseded by D-040: CamillaDSP abandoned in favor of PipeWire filter-chain. CamillaDSP binary backend choice is no longer relevant.

---

### A18 [MEDIUM]: force_turbo + over_voltage voids Pi 4 warranty

**Description:** SETUP-MANUAL.md sets `force_turbo=1` and `over_voltage=2`.
This combination permanently sets the warranty void bit on the Pi 4. Also
increases idle power consumption and thermal stress — exacerbating A4 (flight
case thermals).

**Confidence:** HIGH — documented Pi Foundation behavior
**Validation:** Acknowledge warranty void in documentation. Consider
`performance` governor alone (without force_turbo) as less aggressive
alternative. Test whether governor alone provides sufficient scheduling
stability for audio.
**Affects:** A4 (thermal), US-003 (stability)
**Status:** open — owner should acknowledge warranty void

---

### A19 [MEDIUM]: ALSA loopback 4ch config with DJ mode 2ch capture — SUPERSEDED

**Description:** `snd-aloop` configured with `channels=4`. DJ mode CamillaDSP
captures only 2 channels. PipeWire writes stereo to a 4-channel loopback
device. Unclear how PipeWire maps stereo to channels 0-1 vs channels 2-3.
PipeWire could upmix or route incorrectly.

Note: D-011 changes the architecture to 8-channel CamillaDSP output. The
loopback channel count may also need updating depending on final routing.

**Confidence:** MEDIUM
**Validation:** Test DJ mode stereo routing through 4-channel loopback. Verify
silent channels. Update loopback config if D-011 routing requires it.
**Affects:** US-021, DJ mode audio routing
**Status:** superseded — Superseded by D-040: CamillaDSP abandoned in favor of PipeWire filter-chain. ALSA loopback device is no longer used. PipeWire handles all routing natively via graph links.

---

### A20 [MEDIUM]: FastAPI web server adds CPU load to constrained Pi

**Description:** US-022 targets "< 5% idle, < 10% active" CPU for the web
server. FastAPI on Python with WebSocket connections, GraphManager RPC /
FilterChainCollector polling, and Reaper OSC proxying is nontrivial. Python's
GIL may interfere with real-time audio scheduling. The CPU budget tables in
SETUP-MANUAL.md do NOT include the web server.

**Confidence:** MEDIUM
**Validation:** Add web server to CPU budget estimates. Test with audio
running. Consider CPU affinity to isolate web server from audio cores.
**Affects:** US-022, US-023, CPU budget tables
**Status:** open

---

### A21 [MEDIUM]: Reaper OSC interface for IEM control assumed available

**Description:** US-018 and US-022 assume Reaper's OSC interface can control
IEM mix send levels with < 100ms latency. Reaper supports OSC, but specific
messages for individual track send levels on ARM Linux are not documented
in the project.

**Confidence:** MEDIUM
**Validation:** Research Reaper OSC protocol. Verify send-level control via
OSC on ARM Linux. Add OSC verification to US-017 DoD.
**Affects:** US-017, US-018, US-022
**Status:** open

---

### A22 [MEDIUM]: No power protection for venue deployment

**Description:** No surge protection, UPS, or graceful shutdown mechanism
documented. Venue power can be unreliable. Ungraceful shutdown risks SD card
corruption — a known Pi failure mode. CamillaDSP filter files on ext4
filesystem may be corrupted mid-write during calibration.

**Confidence:** HIGH — venues have unreliable power
**Validation:** Add surge protection to flight case design. Consider read-only
root filesystem (overlayfs) or f2fs for SD card resilience. Document
graceful shutdown procedure.
**Affects:** US-020 (redundancy), flight case design
**Status:** open

---

### A23 [LOW]: USB hub model not specified

**Description:** SETUP-MANUAL.md recommends "a powered USB 3.0 hub" without
specifying a tested model. USB hubs vary in quality; some introduce MIDI
jitter or USB audio glitches.

**Confidence:** LOW
**Validation:** Test with the specific hub used in the flight case. Document
the tested model and any alternatives.
**Affects:** US-005 (MIDI verification), US-003 (stability)
**Status:** open

---

### A24 [LOW]: VNC documented but RustDesk is preferred

**Description:** SETUP-MANUAL.md section 11.2 documents TigerVNC setup.
CLAUDE.md owner preferences state "Remote desktop: RustDesk (not VNC)."
Documentation and owner preferences are misaligned.

**Confidence:** HIGH — documentation inconsistency
**Validation:** Update SETUP-MANUAL.md to use wayvnc as primary method.
**Affects:** US-000a (security hardening), US-006 (remote operation)
**Status:** superseded — D-018 removes RustDesk entirely; wayvnc is the sole remote desktop (VNC is now the primary method, not a fallback)

---

### A25 [LOW]: speaker-test 8-channel command is a hearing safety risk

**Description:** SETUP-MANUAL.md troubleshooting uses
`speaker-test -D hw:1,0 -c 8 -r 48000 -t sine` which sends sine to all 8
channels simultaneously, including IEM and headphones at potentially
dangerous volume if worn during troubleshooting.

**Confidence:** HIGH — safety hazard
**Validation:** Add warning to documentation. Use `-c 2` for initial testing.
Document channel-by-channel test approach.
**Affects:** Troubleshooting safety, SETUP-MANUAL.md
**Mitigation:** Partially mitigated by US-053 (test tool page) which provides channel-by-channel testing with safe defaults.
**Status:** open

---

### A26 [LOW]: ADAT clock sync recovery behavior unknown

**Description:** If the ADAT optical cable is briefly disconnected (loose
connection, transport vibration), the ADA8200 loses clock sync. Recovery
behavior (automatic re-sync? noise during recovery?) is not documented.

**Confidence:** LOW — cable is usually reliable in a secured flight case
**Validation:** Test ADAT disconnect/reconnect behavior. Ensure cable strain
relief in flight case design.
**Affects:** Hardware reliability, flight case design
**Status:** open

---

### A27 [MEDIUM]: Stock PREEMPT kernel provides adequate scheduling latency for production use — SUPERSEDED

**Description:** The system currently runs the stock PREEMPT kernel (D-015)
as an interim measure due to F-012 (Reaper lockup on PREEMPT_RT). D-013
mandates PREEMPT_RT for production use, but until F-012 is resolved, the
stock kernel must provide adequate scheduling latency for the 5.33ms
processing deadline at chunksize 256. T3e showed PREEMPT_RT achieves max
209us scheduling latency, but no cyclictest baseline exists for stock
PREEMPT — the actual worst-case scheduling latency on stock PREEMPT is
unknown.

**Confidence:** MEDIUM — stock PREEMPT works in practice (US-003 T3b/T3c
passed with zero xruns in 30-minute tests), but no formal worst-case bound
exists. PREEMPT_RT provides bounded 209us worst-case; stock PREEMPT
scheduling latency is empirically adequate but theoretically unbounded.
**Validation:** Needs stock PREEMPT cyclictest baseline under audio load
(not yet run). Compare worst-case latency to 5.33ms deadline. If stock
worst-case exceeds ~2ms, production use on stock PREEMPT is risky.
**Affects:** D-013 (PREEMPT_RT mandatory), D-015 (stock PREEMPT interim), US-003, F-012
**Status:** superseded — Superseded by D-022: PREEMPT_RT is now the production kernel (`6.12.62+rpt-rpi-v8-rt`). Upstream V3D deadlock fix resolved F-012. Stock PREEMPT scheduling latency question is moot.

---

### A28 [LOW]: System must function with zero venue network infrastructure

**Description:** US-034 requires all venue-time functionality to work without
Internet (replaces withdrawn D-017). The stronger form: the system must work
even if the venue provides no network at all. The Pi must be able to create
its own WiFi network (AP mode) or the operator must bring a portable router.
This is NOT an assumption that the venue provides a usable network — it is a
design requirement that the system is self-sufficient.

Note: the network topology question (Pi as AP vs. portable router, device
trust model for guest musicians' phones) is explicitly OPEN and not addressed
by A28 or US-034.

**Confidence:** HIGH — Pi 4B has onboard WiFi capable of AP mode via hostapd.
Portable travel routers are inexpensive and reliable. The core audio stack
has zero network dependency. The only networked features are remote access
(wayvnc/SSH per D-018) and web UI (US-022/US-018), which operate on the local
network the Pi itself creates or joins.
**Validation:** Test Pi as WiFi AP with hostapd: operator laptop and singer
phone connect to Pi's AP, web UI and wayvnc work. Alternatively,
test with a portable router and no Internet uplink.
**Affects:** US-034 (offline venue operation), US-000a (wayvnc + SSH remote access), US-022 (bundled assets), US-018 (singer phone), US-031 (offline rehearsal)
**Security note:** Security review required if Pi-as-AP is chosen (hostapd config, WPA3, client isolation).
**Status:** open

---

## D-040 Architecture Assumptions (A29-A34) — from team triage 2026-03-21

### A29 [MEDIUM]: PW filter-chain stability for multi-hour gigs

**Description:** GM-12 validated PipeWire filter-chain convolver stability for
40 minutes (zero xruns, 58% idle, 71C). Production psytrance gigs run 3-6 hours
— 4.5x to 9x longer. Long-duration failure modes (memory leaks, thermal
throttling, PipeWire graph renegotiation under sustained load) have not been
tested.

**Confidence:** MEDIUM — 40-minute validation is encouraging but insufficient
for production confidence at multi-hour scale.
**Validation:** T3d (30-min soak on PREEMPT_RT), then full-length rehearsal.
**Affects:** D-040, US-003, every gig
**Status:** open

---

### A30 [LOW]: PW filter-chain coefficient hot-swap requires PipeWire restart

**Description:** The room correction pipeline must deploy new FIR coefficient
WAV files after measurement. It is unknown whether PipeWire filter-chain can
reload coefficients at runtime (e.g., via `pw-cli` module parameter changes)
or whether a full PipeWire restart is required. A restart triggers USBStreamer
re-enumeration, which produces transients through the amplifier chain — a
speaker safety risk (see `docs/operations/safety.md`).

**Confidence:** LOW — not investigated.
**Validation:** Test pw-cli module parameter reload or PW restart with gain
nodes attenuated.
**Affects:** Room correction pipeline deployment step, safety rules (USBStreamer transient)
**Status:** open

---

### A31 [MEDIUM]: PW 1.4.9 config.gain silently ignored / future stacking risk

**Description:** PipeWire 1.4.9 silently ignores `config.gain` in filter-chain
node definitions. The project works around this using `pw-cli` runtime volume
commands and `linear` builtin Mult params. If a future PipeWire update fixes
`config.gain` handling, both gain mechanisms could stack, producing unexpected
volume levels — potentially dangerous for speakers and hearing.

**Confidence:** MEDIUM — stable workaround for PW 1.4.9 but fragile across
upgrades. The silent-ignore behavior is undocumented and could change without
notice.
**Validation:** Test on each PW upgrade. Add to pre-flight checklist.
**Affects:** Safety (gain staging), every PW upgrade
**Status:** open

---

### A32 [HIGH]: pw-cli runtime gain control works glitch-free under audio load

**Description:** The system uses `pw-cli` to set volume/gain at runtime (e.g.,
-30 dB attenuation after PipeWire restart, measurement gain presets). C-009
verified initial gain application works. It has not been formally tested whether
changing gain via `pw-cli` while audio is actively playing causes clicks, pops,
or dropouts.

**Confidence:** HIGH — C-009 verified initial set; formal load test pending.
**Validation:** Test pw-cli gain change while audio is playing. Verify no
click/pop/dropout.
**Affects:** Measurement workflow, mode switching gain presets
**Status:** open

---

### A33 [HIGH]: FFTW3/NEON performance dependency

**Description:** BM-2 benchmark numbers (1.70% CPU at quantum 1024, 3.47% at
quantum 256) implicitly depend on FFTW3 using ARM NEON SIMD instructions. The
numbers are impossible without SIMD acceleration. However, the NEON codepath
has not been explicitly verified — if the Debian package were compiled without
NEON support, or if an apt upgrade replaced the library with a non-NEON build,
convolver performance would degrade dramatically.

**Confidence:** HIGH — BM-2 numbers empirically confirm NEON active (impossible
without SIMD). Implicit dependency, not explicitly verified.
**Validation:** `readelf -A /usr/lib/aarch64-linux-gnu/libfftw3f.so.3 | grep NEON`.
Verify after any apt upgrade.
**Affects:** D-040 rationale, BM-2 validity
**Status:** open

---

### A34 [LOW]: GraphManager link reconciler production-ready for unattended mode transitions

**Description:** The GraphManager (US-059) manages PipeWire link topology and
mode transitions. Known reconciler bugs required manual `pw-link` workaround
for GM-12. Includes assumption that WirePlumber (device management only, linking
disabled per D-043) does not interfere with GraphManager link reconciliation.

**Confidence:** LOW — known bugs, manual pw-link workaround used for GM-12.
**Validation:** US-059 completion + automated mode transition soak test.
**Affects:** US-059, US-021, measurement workflow
**Status:** open

---

## Cross-Reference: Blocking Findings by Story

| Story | Blocking Assumptions | Notes |
|-------|---------------------|-------|
| US-000 | ~~A9~~ (resolved in US-000b), ~~A10~~ (resolved in US-000), ~~A17~~ (superseded by D-040) | A9, A10 resolved; A17 superseded — CamillaDSP binary no longer relevant |
| US-005 | ~~A14~~ (superseded by D-019) | BT scrapped — USB-MIDI only, no fallback. A6 now VALIDATED. |
| US-006 | ~~A15~~ (superseded by D-022), ~~A16~~ (superseded by D-022) | Both resolved by labwc Wayland + hardware V3D GL. A7 now VALIDATED. |
| US-017 | ~~A11~~ (superseded by D-040) | CamillaDSP routing constraint eliminated — PipeWire handles all routing natively |
| US-021 | ~~A13~~ (superseded by D-040), ~~A16~~ (superseded by D-022), ~~A19~~ (superseded by D-040) | All three blockers superseded by D-040/D-022 architecture changes |
| US-022 | A20 (web server CPU), A21 (Reaper OSC) | CPU budget must account for web server |
| US-003 | A4 (thermals, LOW confidence — D-012 active cooling mandatory), A18 (force_turbo), A23 (USB hub), ~~A27~~ (superseded by D-022), A29 (multi-hour stability), A33 (FFTW3/NEON) | T3b: 74.5C open-air. Active cooling required per D-012. T4 validates. A27 superseded — PREEMPT_RT is production kernel. A29: 40min validated, multi-hour pending. |
| US-021 (contd.) | A34 (GraphManager reconciler) | Known bugs block automated mode transitions |
| US-059 | A34 (GraphManager reconciler) | Manual pw-link workaround for GM-12; reconciler bugs block automation |
| Room correction | A30 (coefficient hot-swap), A31 (config.gain stacking), A32 (pw-cli gain glitch) | Deployment step safety and gain staging |

---

## Assumptions Resolved by Recent Decisions

| Finding | Resolution | Decision |
|---------|-----------|----------|
| C1 (binding decisions conditional) | Formalized as conditional | D-007 |
| A3 (latency < 25ms) | Validated: ~5.3ms at quantum 256 with PW filter-chain | D-040 (supersedes D-011) |
| A11 (IEM bypass CamillaDSP) | Superseded: PipeWire handles all routing natively | D-040 (supersedes D-011) |
| A12 (CamillaDSP hot-swap) | Superseded: CamillaDSP abandoned | D-040 |
| A13 (quantum/chunksize alignment) | Superseded: single PW quantum, no chunksize | D-040 |
| A15 (Xvfb systemd bug) | Superseded: labwc Wayland replaces Xvfb | D-022 |
| A16 (gpu_mem conflict) | Superseded: hardware V3D GL resolves | D-022 |
| A17 (CamillaDSP ALSA-only binary) | Superseded: CamillaDSP abandoned | D-040 |
| A19 (ALSA loopback channels) | Superseded: ALSA loopback eliminated | D-040 |
| A27 (stock PREEMPT scheduling) | Superseded: PREEMPT_RT is production kernel | D-022 |
| M4 (no filter versioning) | Per-venue regeneration; filters are ephemeral | D-008 |
| L2 (crossover slope undecided) | Configurable via speaker profiles | D-010 |
| +12dB boost concern | Cut-only with -0.5dB margin | D-009 |

---

## Summary

This register contains 34 formal assumptions (A1-A34). The original AD audit
identified 30 findings total; the additional 4 were meta-findings (C1, H1, M4, L2)
that were resolved by decisions D-007 through D-010 and are tracked in the
"Assumptions Resolved by Recent Decisions" table above rather than as numbered
assumptions. A27 was added post-audit based on D-015/F-012 findings.
A28 was added based on D-017 (now WITHDRAWN, replaced by US-034).
A29-A34 were added based on D-040 architecture review (team triage, 2026-03-21).

D-040 (CamillaDSP abandoned, PipeWire filter-chain) superseded 5 assumptions
(A11, A12, A13, A17, A19). D-022 (labwc Wayland, hardware V3D GL, PREEMPT_RT
production kernel) superseded 3 assumptions (A15, A16, A27). Three assumptions
previously open or invalidated are now VALIDATED (A3, A6, A7).

| Status | Count | Entries |
|--------|-------|---------|
| VALIDATED | 6 | A1, A2, A3, A6, A7, A10 |
| Superseded | 10 | A11, A12, A13 (D-040); A14 (D-019); A15, A16 (D-022); A17, A19 (D-040); A24 (D-018); A27 (D-022) |
| Partially-resolved | 1 | A9 |
| Open | 17 | A4, A5, A8, A18, A20, A21, A22, A23, A25, A26, A28, A29, A30, A31, A32, A33, A34 |
| **Total** | **34** | |

Note: A4 (LOW confidence, D-012 mitigation pending T4), A5 (MEDIUM), A8 (UNKNOWN)
from the original set remain open pending hardware validation. A29-A34 are new
D-040-era assumptions covering PW filter-chain stability, coefficient deployment,
gain staging safety, FFTW3/NEON dependency, and GraphManager readiness.
