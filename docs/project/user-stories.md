# User Stories

Stories with acceptance criteria and Definition of Done.

---

## Tier 0 — Core Software Installation

CamillaDSP, Mixxx, and Reaper are not yet installed on the Pi 4B (verified
2026-03-08). This tier covers installing the core software stack that all
other stories depend on.

---

## US-000: Core Audio Software Installation

**As** the system builder,
**I want** CamillaDSP, Mixxx, Reaper, and all required Python DSP libraries
installed on the Pi 4B with verified basic functionality,
**so that** subsequent stories (benchmarks, latency tests, stability tests,
room correction pipeline) have a working software foundation.

**Status:** in-progress (worker running, ~2hr estimated)
**Depends on:** none (first story to execute)
**Blocks:** US-001 (CamillaDSP must be installed for CPU benchmarks), US-002 (CamillaDSP must be installed for latency measurement), US-006 (Mixxx must be installed for feasibility testing), US-017 (Reaper must be installed for IEM routing)
**Decisions:** none yet

**Note:** As of 2026-03-08, the Pi has PipeWire running (pipewire, pipewire-pulse,
wireplumber) and a labwc Wayland desktop. CamillaDSP, Mixxx, Reaper, and
RustDesk are not installed. Actual user on Pi is `ela` (not `pi`) — all
service files and paths from SETUP-MANUAL.md must be corrected (AD finding A10).

**Acceptance criteria:**
- [ ] CamillaDSP v3.0.1+ installed and running (binary or built from source for aarch64)
- [ ] CamillaDSP confirmed as ALSA-only backend (no JACK) — document that this is correct for the loopback architecture where CamillaDSP reads from ALSA loopback, not from JACK directly (AD finding A17)
- [ ] CamillaDSP configuration directory created (`/etc/camilladsp/configs/`, `/etc/camilladsp/coeffs/`)
- [ ] CamillaDSP websocket API accessible on localhost
- [ ] Mixxx installed (Debian package or built from source)
- [ ] Reaper installed (via Pi-Apps or manual download of ARM build)
- [ ] Python 3 with scipy, numpy, soundfile installed (for room correction pipeline)
- [ ] pycamilladsp Python package installed (for CamillaDSP API access)
- [ ] RustDesk installed for remote desktop access
- [ ] ALSA loopback module loaded and verified (CamillaDSP capture source)
- [ ] ALSA card numbering stabilized: udev rules or equivalent to ensure consistent device ordering across reboots (AD finding A9)
- [ ] PipeWire JACK bridge verified: applications can connect to JACK ports
- [ ] All systemd service files, scripts, and paths corrected from `User=pi` / `/home/pi` to `User=ela` / `/home/ela` (AD finding A10)
- [ ] Each installation step documented in lab notes with exact versions (for reproducibility per US-019)

**DoD:**
- [ ] All software installed and basic smoke test passed (each tool launches without error)
- [ ] All user/path references verified as `ela` (grep for `pi` in service files and configs — zero false references)
- [ ] ALSA device ordering tested across reboot (same card numbers after power cycle)
- [ ] Lab note written with exact package versions, installation commands, and any workarounds
- [ ] CLAUDE.md "Not installed yet" list updated to reflect current state

---

## US-000a: Platform Security Hardening

**As** the system builder,
**I want** the Pi hardened against casual network attacks before it connects to
any venue WiFi network,
**so that** exposed services cannot be exploited by untrusted devices on the
same network, protecting both system integrity and live performance availability.

**Status:** in-progress (partial: firewall, SSH, rpcbind/ModemManager/CUPS done; CamillaDSP localhost binding deferred to US-000 completion)
**Depends on:** US-000 (CamillaDSP and RustDesk must be installed before their configs can be hardened)
**Blocks:** none directly, but should be completed before any venue deployment
**Decisions:** D-006 (security specialist scope: availability/integrity for live performance)

**Note:** Based on security specialist assessment of Pi state (2026-03-08).
Current state: no firewall, SSH password auth likely enabled, rpcbind exposed
on port 111, CamillaDSP websocket (1234) and GUI (5005) will bind to 0.0.0.0
by default when installed.

**Acceptance criteria:**
- [ ] **nftables firewall** configured and persistent across reboot:
  - Default policy: deny inbound
  - SSH (port 22) allowed
  - RustDesk: stateful outbound allowed (client-only mode, no inbound ports needed)
  - All other inbound traffic dropped
- [ ] **SSH hardened:**
  - `PasswordAuthentication no` in sshd_config
  - `PermitRootLogin no` in sshd_config
  - Key-based auth verified working BEFORE disabling password auth (lockout prevention)
- [ ] **rpcbind disabled:** `systemctl disable --now rpcbind.service rpcbind.socket` (no NFS needed)
- [ ] **CamillaDSP websocket** (port 1234) bound to 127.0.0.1 only (access via SSH tunnel when needed remotely)
- [ ] **CamillaDSP GUI** (port 5005) bound to 127.0.0.1 only (access via SSH tunnel when needed remotely)
- [ ] **RustDesk** configured as client-only (Option A per security specialist): LAN direct preferred, public relay as fallback, strong permanent password set
- [ ] Verification: `ss -tlnp` shows no unexpected services listening on 0.0.0.0
- [ ] Security specialist review passed

**DoD:**
- [ ] All hardening steps applied and verified on Pi 4B
- [ ] Firewall rules persist across reboot (tested with actual reboot)
- [ ] Lab note documenting all changes, verification commands, and how to access localhost-only services via SSH tunnel
- [ ] Security specialist review passed

---

## Tier 1 — Platform Validation

These stories validate that the Pi 4B can run the required workload. They gate
all subsequent implementation work. Per design principle #1 ("test early"), these
must be completed first.

---

## US-001: CamillaDSP CPU Benchmark Suite

**As** the system builder,
**I want** to measure CamillaDSP's CPU consumption across a matrix of chunksize
and FIR filter length combinations on the Pi 4B,
**so that** I can confirm the hardware can handle the DSP workload and make
informed decisions about filter length and chunksize for each operating mode.

**Status:** draft
**Depends on:** US-000 (CamillaDSP must be installed)
**Blocks:** US-003 (stability tests use the config validated here), US-008 through US-011 (pipeline filter length depends on CPU budget), US-010 (correction filter tap count)
**Decisions:** D-002 (dual chunksize), D-003 (16,384-tap FIR)

**Acceptance criteria:**
- [ ] Synthetic Dirac FIR filters generated at 8,192, 16,384, and 32,768 taps (48kHz, mono WAV, float32)
- [ ] CamillaDSP test config created: 4-channel convolution (left HP, right HP, sub1 LP, sub2 LP) using the synthetic filters
- [ ] Test matrix T1a-T1e executed on Pi 4B with results recorded:
  - T1a: 16,384 taps @ chunksize 2048 — PASS if < 30% CPU
  - T1b: 16,384 taps @ chunksize 512 — PASS if < 45% CPU
  - T1c: 16,384 taps @ chunksize 256 — PASS if < 60% CPU
  - T1d: 8,192 taps @ chunksize 512 — PASS if < 30% CPU
  - T1e: 32,768 taps @ chunksize 2048 — PASS if < 40% CPU
- [ ] CPU measurement method documented (sampling interval, stabilization period, tool used)
- [ ] Decision tree outcome recorded: which filter length for DJ mode, which for live mode
- [ ] Results captured in lab notes with raw data

**DoD:**
- [ ] Test scripts written and syntax-validated (`bash -n` / `python -m py_compile`)
- [ ] All five test runs completed on Pi 4B hardware
- [ ] Lab note written with raw CPU measurements and decision tree outcome
- [ ] CLAUDE.md assumptions A1, A2 updated with validation results

---

## US-002: End-to-End Latency Measurement

**As** the system builder,
**I want** to measure the actual round-trip audio latency of the full signal
path (PipeWire -> CamillaDSP -> USB -> ADAT -> analog -> loopback -> analog ->
ADAT -> USB -> PipeWire),
**so that** I can confirm the live mode latency stays below the singer's
slapback perception threshold.

**Status:** draft
**Depends on:** US-000 (CamillaDSP must be installed; can run in parallel with US-001)
**Blocks:** US-003 (stability tests assume latency is acceptable)
**Decisions:** D-002 (dual chunksize)

**Note:** Loopback cable already connected (Output 1 -> Input 1 on ADA8200,
gain ~3/4) — hardware prerequisite is met. Audio engineer is also researching
whether the UMIK-1 has built-in latency measurement capability, which may
provide an alternative or complementary measurement method.

**Acceptance criteria:**
- [ ] Loopback cable verified working (Output 1 -> Input 1, already connected)
- [ ] Impulse-based latency measurement performed (send impulse, record return, measure sample offset)
- [ ] T2a executed: DJ/PA mode (chunksize 2048) — PASS if < 55ms round-trip
- [ ] T2b executed: Live mode (chunksize 512) — PASS if < 25ms round-trip
- [ ] Latency breakdown documented: PipeWire quantum, CamillaDSP chunksize, USB round-trip, ADAT encode/decode
- [ ] If UMIK-1 latency measurement capability is confirmed: document and compare with loopback method
- [ ] If T2b fails: document the gap and propose mitigations (smaller PipeWire quantum, smaller chunksize)

**DoD:**
- [ ] Measurement procedure documented (repeatable by someone else)
- [ ] Both test runs completed on Pi 4B hardware
- [ ] Lab note written with raw latency measurements and breakdown analysis
- [ ] CLAUDE.md assumption A3 updated with validation result

---

## US-003: Stability and Thermal Tests

**As** the system builder,
**I want** to run sustained 30-minute load tests in both DJ/PA and Live
configurations, monitoring for xruns, CPU usage, and thermal throttling,
**so that** I can confirm the system is reliable enough for a full live
performance without audio dropouts or thermal shutdown.

**Status:** draft
**Depends on:** US-001 (need to know which filter length/chunksize config to test)
**Blocks:** US-008 through US-011 (pipeline work should not proceed if platform is unstable)
**Decisions:** D-002 (dual chunksize), D-003 (16,384-tap FIR)

**Acceptance criteria:**
- [ ] T3a executed: CamillaDSP + Mixxx (2 decks, continuous playback) for 30 minutes — PASS if 0 xruns and peak CPU < 85%
- [ ] T3b executed: CamillaDSP + Reaper (8-track backing + FX) for 30 minutes — PASS if 0 xruns and peak CPU < 85%
- [ ] T4 executed: thermal test in actual flight case — PASS if CPU temp stays below 75C and clock frequency remains at maximum
- [ ] Temperature logged every 10 seconds throughout T3/T4 runs
- [ ] CamillaDSP processing load logged via websocket API every 10 seconds
- [ ] If any test fails: failure mode documented, mitigation proposed (heatsink, fan, reduced load, config change)

**DoD:**
- [ ] Monitoring scripts written and syntax-validated
- [ ] All test runs completed on Pi 4B hardware
- [ ] Lab note written with thermal curves, CPU timelines, xrun count
- [ ] CLAUDE.md assumption A4 updated with validation result

---

## US-004: Expanded Assumption Discovery and Tracking

**As** the system builder,
**I want** a comprehensive audit of all assumptions beyond A1-A8 that the
project relies on, tracked in a structured format,
**so that** hidden risks are surfaced early and can be validated before they
cause problems during implementation or live performance.

**Status:** ready
**Depends on:** none
**Blocks:** none directly, but informs prioritization of all other stories

**Note:** The Advocatus Diaboli has completed initial discovery, identifying 30
findings including 18 new assumptions (A9 through A26), 6 of which are blocking.
Blocking findings have been incorporated into the AC/DoD of affected stories
(US-000, US-005, US-006, US-012, US-017, US-022). This story now covers
formalizing and maintaining the expanded assumption register.

**Acceptance criteria:**
- [ ] All AD findings (A9-A26) formally documented in assumption register with: description, confidence level, validation method, affected stories
- [ ] Blocking findings cross-referenced to the stories where they are tracked (US-000: A9/A10/A17, US-005: A14, US-006: A15/A16, US-017: A11)
- [ ] Categories covered: ALSA card numbering, user/path correctness, CamillaDSP backend type, Bluetooth vs USB-MIDI, Xvfb service correctness, gpu_mem conflicts, loopback routing, Reaper OSC availability, memory budgets, and all others from AD report
- [ ] Assumptions list added to CLAUDE.md or a referenced document
- [ ] Each assumption linked to the story that will validate it
- [ ] Ongoing: new assumptions discovered during implementation are added to the register

**DoD:**
- [ ] Expanded assumption register written and reviewed
- [ ] CLAUDE.md updated with new assumption references
- [ ] Dependencies between assumptions and stories documented
- [ ] All 6 blocking findings confirmed addressed in their respective story AC/DoD

---

## Tier 2 — Hardware and Software Verification

These stories resolve specific unknowns about hardware devices and software
compatibility. They can partially run in parallel with Tier 1.

---

## US-005: Hercules DJControl Mix Ultra USB-MIDI Functional Verification

**As** the DJ,
**I want** to verify that the Hercules DJControl Mix Ultra works as a
functional USB-MIDI controller on the Pi 4B (beyond just USB enumeration),
**so that** I can use it to control Mixxx during DJ/PA sets.

**Status:** draft
**Depends on:** none (USB enumeration already confirmed by owner)
**Blocks:** US-006 (Mixxx feasibility includes controller integration)
**Decisions:** none yet

**Note:** Owner has already confirmed USB enumeration via `lsusb`. This story
covers functional MIDI verification: does it send/receive MIDI messages?

**CRITICAL (AD finding A14):** The Hercules DJControl Mix Ultra is
Bluetooth-primary. SETUP-MANUAL.md disables Bluetooth via `dtoverlay=disable-bt`
in config.txt. This story MUST complete USB-MIDI verification BEFORE Bluetooth
is disabled during hardening/setup. If USB-MIDI fails, Bluetooth MIDI is the
fallback and must remain available.

**Acceptance criteria:**
- [ ] Controller connected via USB, confirmed visible in `aconnect -l` as a MIDI device
- [ ] MIDI messages verified: pressing buttons/moving faders produces MIDI events visible in `aseqdump` or `amidi`
- [ ] All control types tested: faders, knobs, buttons, jog wheels (if applicable)
- [ ] Any non-functional controls documented
- [ ] USB-MIDI verification completed BEFORE Bluetooth is disabled in config.txt (A14)
- [ ] If USB-MIDI works: document as confirmed, Bluetooth can be safely disabled
- [ ] If USB-MIDI does not work: document the failure mode, DO NOT disable Bluetooth, research Bluetooth MIDI via bluez as primary path

**DoD:**
- [ ] Test completed on Pi 4B hardware
- [ ] Lab note written with MIDI message log excerpts and control mapping summary
- [ ] CLAUDE.md assumption A6 updated with full validation result
- [ ] Decision documented: is it safe to disable Bluetooth? (only if USB-MIDI confirmed working)

---

## US-006: Mixxx on Pi 4B Feasibility

**As** the DJ,
**I want** to verify that Mixxx runs adequately on the Pi 4B with acceptable
UI responsiveness and audio performance,
**so that** I can use it as my DJ software for PA/DJ sets.

**Status:** draft
**Depends on:** US-000 (Mixxx must be installed), US-005 (need working MIDI controller to test DJ workflow)
**Blocks:** US-003/T3a (stability test with Mixxx requires Mixxx to be working)
**Decisions:** none yet

**Note:** The Pi runs labwc (Wayland compositor) with lightdm. Mixxx may need
X11/XWayland — verify. Remote access is via RustDesk (not VNC).

**Known issues from AD review:**
- **A15:** The Xvfb systemd service in SETUP-MANUAL.md has a bug: trailing `&`
  in ExecStartPre backgrounding the process. Headless Mixxx will not work as
  documented. Must fix or find alternative approach.
- **A16:** gpu_mem=16 (headless config) conflicts with gpu_mem=128 (Mixxx
  requirement). Need to determine a single value or document a reboot procedure
  for mode switching.

**Acceptance criteria:**
- [ ] Mixxx launches on Pi 4B (verify Wayland/XWayland compatibility with labwc)
- [ ] GPU configuration resolved: determine single gpu_mem value that works for both headless and Mixxx modes, OR document reboot procedure for switching (AD finding A16)
- [ ] Waveform rendering tested: "Simple" renderer, GL renderer, disabled — document which works and performance of each
- [ ] Audio routing verified: Mixxx main output reaches CamillaDSP via PipeWire JACK bridge
- [ ] Two-deck playback tested with actual audio files — no audible glitches
- [ ] Remote operation tested: Mixxx controllable via RustDesk and/or entirely via MIDI controller
- [ ] Headless feasibility assessed: fix Xvfb service bug (trailing `&` in ExecStartPre, AD finding A15) or find alternative virtual display approach under Wayland
- [ ] If Mixxx is not viable: document the failure and evaluate alternatives

**DoD:**
- [ ] Tests completed on Pi 4B hardware
- [ ] gpu_mem decision documented with rationale (A16 resolved)
- [ ] Xvfb/virtual display approach documented and working or alternative identified (A15 resolved)
- [ ] Lab note with performance observations, configuration choices, screenshots/logs
- [ ] CLAUDE.md assumption A7 updated with validation result

---

## US-007: APCmini mk2 Mixxx Mapping Research and Creation

**As** the DJ,
**I want** a working Mixxx MIDI mapping for the Akai APCmini mk2,
**so that** I can use it as a supplementary controller (grid launcher, mixer,
effects) alongside the Hercules.

**Status:** draft
**Depends on:** US-006 (Mixxx must be working first)
**Blocks:** none (nice-to-have for DJ mode, not critical path)
**Decisions:** none yet

**Note:** The mk2 has a different MIDI mapping from the mk1. Existing mk1
mappings will not work without modification.

**Acceptance criteria:**
- [ ] Research completed: Mixxx forums, GitHub, wiki checked for existing mk2 mappings
- [ ] If mapping exists: installed and tested on Pi 4B with Mixxx
- [ ] If no mapping exists: basic custom mapping created using Mixxx's MIDI learning wizard covering at minimum: play/cue, volume faders, crossfader, EQ kills
- [ ] APCmini mk2 LED feedback verified (button LEDs respond to Mixxx state)
- [ ] Mapping file committed to the project repository

**DoD:**
- [ ] Working mapping tested on Pi 4B hardware
- [ ] Lab note documenting the mapping layout and any limitations
- [ ] CLAUDE.md assumption A8 updated with validation result

---

## Tier 3 — Automated Room Correction Pipeline

The next major deliverable. Each story covers one phase of the pipeline
described in CLAUDE.md "Next Steps." These depend on Tier 1 passing (confirming
the Pi 4B can handle FIR convolution at the chosen tap count).

---

## US-008: Measurement Engine — Sweep Generation, Recording, and Deconvolution

**As** the sound engineer,
**I want** a Python-based measurement engine that generates a log sweep, plays
it through a specified output channel, records the response via the UMIK-1,
and computes the impulse response via deconvolution,
**so that** I can measure the acoustic response of each speaker in the venue.

**Status:** draft
**Depends on:** US-001 (confirms viable filter length), US-002 (confirms latency path works)
**Blocks:** US-009 (time alignment needs impulse responses), US-010 (correction needs impulse responses), US-012 (end-to-end script wraps this)
**Decisions:** D-001 (minimum-phase FIR), D-004 (independent sub correction)

**Acceptance criteria:**
- [ ] Log sweep generation: 20Hz-20kHz, configurable duration (default 5s), 48kHz sample rate
- [ ] UMIK-1 calibration file parsing: reads frequency/dB pairs from `/home/ela/7161942.txt`, applies magnitude correction to recorded response
- [ ] Per-channel measurement: plays sweep through one output channel at a time (channels 1-4), records on UMIK-1 input
- [ ] Deconvolution: computes impulse response from recorded sweep using inverse filter method
- [ ] Multiple measurement positions: supports taking 3-5 measurements at different mic positions, stores each separately
- [ ] Spatial averaging: averages multiple impulse responses (complex average in frequency domain) to reduce position sensitivity
- [ ] Output: per-channel averaged impulse response saved as WAV file
- [ ] Audio routing: correctly routes sweep output and UMIK-1 input through PipeWire/JACK
- [ ] Error handling: detects clipping, low signal level, or failed recording and reports clearly

**DoD:**
- [ ] Python module written with clear API
- [ ] Syntax-validated (`python -m py_compile`)
- [ ] Unit tests for sweep generation and deconvolution (synthetic test cases)
- [ ] Integration test on Pi 4B with actual UMIK-1 and USBStreamer
- [ ] Lab note with example impulse response plots

---

## US-009: Time Alignment Computation

**As** the sound engineer,
**I want** the system to automatically detect the arrival time of each
speaker's impulse response and compute the relative delays needed for time
alignment,
**so that** all speakers are phase-coherent at the listening position without
manual measurement.

**Status:** draft
**Depends on:** US-008 (needs per-channel impulse responses)
**Blocks:** US-012 (end-to-end script includes time alignment)
**Decisions:** D-004 (independent sub correction — each sub has its own delay)

**Acceptance criteria:**
- [ ] Arrival time detection: finds the onset of energy in each channel's impulse response (threshold-based or envelope-based method)
- [ ] Relative delay computation: furthest speaker = reference (delay 0), all others get positive delay to compensate
- [ ] Delay values output in both samples and milliseconds at 48kHz
- [ ] Delay values formatted for CamillaDSP config (pipeline delay parameter)
- [ ] Edge cases handled: no arrival detected (speaker not connected), multiple peaks (strong early reflection), very short distances (all speakers equidistant)
- [ ] Results logged with clear per-channel breakdown

**DoD:**
- [ ] Python module written with clear API
- [ ] Syntax-validated (`python -m py_compile`)
- [ ] Unit tests with synthetic impulse responses at known delays
- [ ] Lab note with example delay computation from real measurements

---

## US-010: Correction Filter Generation

**As** the sound engineer,
**I want** the system to compute a room correction filter for each output
channel from its measured impulse response, applying psychoacoustic smoothing,
frequency-dependent windowing, regularization, and a user-selectable target
curve,
**so that** the correction addresses real room problems without chasing
artifacts or wasting amplifier headroom on uncorrectable nulls.

**Status:** draft
**Depends on:** US-008 (needs measured impulse responses)
**Blocks:** US-011 (crossover integration convolves correction with crossover shape), US-012 (end-to-end script wraps this)
**Decisions:** D-001 (minimum-phase FIR), D-003 (16,384-tap FIR)

**Acceptance criteria:**
- [ ] Target curve support: at minimum Harman-like curve with SPL-dependent bass shelf. User can select from presets or provide custom curve file
- [ ] Frequency-dependent windowing: aggressive correction below ~300Hz (room modes), gentle correction above 300Hz (only broad speaker response deviations, not individual reflections/comb filtering)
- [ ] Psychoacoustic smoothing applied to measured response before inversion: 1/6 octave below 200Hz, 1/3 octave 200Hz-1kHz, 1/2 octave above 1kHz
- [ ] Regularization: maximum boost limited (configurable, default +12dB). Nulls are gently filled, not aggressively boosted
- [ ] Minimum-phase chain preserved throughout: measured IR minimum-phase extraction, inverse computation in minimum-phase domain
- [ ] Output: per-channel correction filter as minimum-phase FIR (not yet combined with crossover — that is US-011)
- [ ] Configurable filter length (default 16,384 taps, fallback 8,192)

**DoD:**
- [ ] Python module written with clear API
- [ ] Syntax-validated (`python -m py_compile`)
- [ ] Unit tests: synthetic room response with known mode -> verify correction flattens it
- [ ] Unit tests: verify output filter is minimum-phase (check via Hilbert transform)
- [ ] Lab note with example correction curves (before/after magnitude plots)

---

## US-011: Crossover Integration and Combined Filter Export

**As** the sound engineer,
**I want** the system to generate minimum-phase FIR crossover shapes (highpass
for mains, lowpass for subs), convolve them with the room correction filters,
and export the combined result as WAV files for CamillaDSP,
**so that** each output channel has a single FIR filter that handles both
crossover and room correction with minimum latency and no pre-ringing.

**Status:** draft
**Depends on:** US-010 (needs per-channel correction filters)
**Blocks:** US-012 (end-to-end script wraps this), US-013 (T5 verification needs real combined filters)
**Decisions:** D-001 (combined minimum-phase FIR), D-003 (16,384-tap FIR)

**Acceptance criteria:**
- [ ] Crossover shape generation: highpass and lowpass as minimum-phase FIR, configurable crossover frequency (default 80Hz), configurable slope (48-96 dB/oct)
- [ ] Convolution of crossover shape with correction filter (multiply in frequency domain)
- [ ] Final combined filter converted to minimum-phase via Hilbert transform of log magnitude
- [ ] Truncation/windowing to target length (16,384 or 8,192 taps)
- [ ] Export as WAV files to CamillaDSP coefficients directory:
  - `combined_left_hp.wav` — Left main (highpass + correction)
  - `combined_right_hp.wav` — Right main (highpass + correction)
  - `combined_sub1_lp.wav` — Sub 1 (lowpass + correction)
  - `combined_sub2_lp.wav` — Sub 2 (lowpass + correction)
- [ ] WAV format: 48kHz, mono, float32
- [ ] Verification: combined filter magnitude response plotted, showing both crossover slope and correction effect

**DoD:**
- [ ] Python module written with clear API
- [ ] Syntax-validated (`python -m py_compile`)
- [ ] Unit tests: synthetic correction + crossover -> verify combined response shape
- [ ] Unit tests: verify output is minimum-phase
- [ ] Unit tests: verify WAV file format and length
- [ ] Lab note with example combined filter plots

---

## US-012: End-to-End Room Correction Automation Script

**As** the sound engineer setting up at a venue,
**I want** a single script that guides me through mic placement, runs all
measurements, computes correction filters, deploys them to CamillaDSP, updates
delay values, and optionally runs a verification measurement,
**so that** I can calibrate the system at each venue with one command and
minimal manual intervention.

**Status:** draft
**Depends on:** US-008 (measurement engine), US-009 (time alignment), US-010 (correction filters), US-011 (crossover integration)
**Blocks:** none
**Decisions:** D-001, D-002, D-003, D-004

**Acceptance criteria:**
- [ ] Interactive guided workflow: prompts user for mic placement, confirms before proceeding to each phase
- [ ] Runs measurement phase: per-channel sweeps, multiple positions per the user's choice
- [ ] Computes time alignment and displays results for user confirmation
- [ ] Generates combined FIR filters with user-selected target curve and crossover parameters
- [ ] Deploys filter WAV files to `/etc/camilladsp/coeffs/`
- [ ] Updates CamillaDSP configuration with new delay values
- [ ] Restarts CamillaDSP with new configuration (or hot-swaps via websocket API if available)
- [ ] Optional verification measurement: runs a quick sweep post-correction and displays before/after comparison
- [ ] All parameters configurable via command-line arguments or config file (crossover freq, target curve, filter length, max boost, number of measurement positions)
- [ ] Memory budget estimated and documented: peak RAM usage during filter computation (FFT of 16k+ tap filters, multiple channels, spatial averaging) must fit within Pi 4B's 4GB alongside running CamillaDSP and PipeWire (AD finding — memory is constrained)
- [ ] Graceful error handling: any failure rolls back to previous configuration
- [ ] Progress output: clear status messages throughout the process

**DoD:**
- [ ] Script written and syntax-validated
- [ ] Peak memory usage measured during a full calibration run (document actual vs budget)
- [ ] End-to-end test on Pi 4B with real speakers and UMIK-1
- [ ] Lab note documenting a complete calibration run with before/after measurements
- [ ] How-to guide written for the calibration procedure

---

## US-013: Correction Effectiveness Verification (Test T5)

**As** the sound engineer,
**I want** to verify that the generated 16,384-tap FIR correction filters
actually provide effective room correction down to 20Hz,
**so that** I can confirm the filter design achieves its stated goals and the
sub-bass correction works as designed.

**Status:** draft
**Depends on:** US-011 (needs real combined filters generated from real measurements)
**Blocks:** none
**Decisions:** D-003 (16,384-tap FIR)

**Acceptance criteria:**
- [ ] Before/after measurement: magnitude response measured at listening position with and without FIR correction active
- [ ] Sweep range: 15Hz-20kHz (extending below 20Hz to check rolloff behavior)
- [ ] Correction effectiveness quantified: deviation from target curve in dB, per-octave band
- [ ] Specific check at 20Hz: is the correction measurably effective? (compare to no-correction baseline)
- [ ] Specific check at 30Hz: confirm solid correction (10.2 cycles at 16k taps)
- [ ] If 20Hz correction is insufficient: document the shortfall and evaluate whether longer filters (32k taps) are viable given T1e CPU results
- [ ] Results compared against target curve overlay

**DoD:**
- [ ] Measurements completed in a real room on Pi 4B hardware
- [ ] Lab note with before/after frequency response plots
- [ ] CLAUDE.md assumption A5 updated with validation result

---

## Tier 4 — Documentation Suite

The documentation suite structure is defined in `.claude/team/config.md` (five
document types). These stories create the initial content. They can run in
parallel with Tier 2 and Tier 3 work.

---

## US-014: Documentation Suite Structure and Introduction

**As** a reader of this project's documentation,
**I want** a clear documentation structure with an introduction that explains
the project, its goals, and how to navigate the documentation,
**so that** I can quickly understand what this project is and find the
information I need.

**Status:** draft
**Depends on:** none
**Blocks:** US-015 (theory doc), US-016 (how-to guides) — they need the structure to exist
**Decisions:** D-005 (technical writer on core team)

**Acceptance criteria:**
- [ ] Directory structure created per config.md: `docs/guide/introduction.md`, `docs/guide/howto/`, `docs/handbook/`, `docs/theory/`, `docs/lab-notes/`
- [ ] Introduction document written: project summary, hardware overview, software stack, two operating modes, documentation map
- [ ] Introduction links to all other documentation sections
- [ ] Content is accurate and reviewed by technical writer

**DoD:**
- [ ] Directories created, introduction document written
- [ ] Technical writer review passed
- [ ] Audio engineer review passed (technical accuracy of overview)

---

## US-015: Theory and Design Document

**As** a reader who wants to understand the signal processing decisions,
**I want** a theory and design document that explains the rationale behind
minimum-phase FIR filters, the crossover design, the latency budget, the room
correction approach, and the psychoacoustic constraints,
**so that** I can understand WHY the system is designed this way, not just HOW
it is configured.

**Status:** draft
**Depends on:** US-014 (documentation structure must exist)
**Blocks:** none
**Decisions:** D-001, D-002, D-003, D-004

**Acceptance criteria:**
- [ ] Covers: IIR vs linear-phase FIR vs minimum-phase FIR comparison (with group delay and pre-ringing analysis)
- [ ] Covers: crossover design rationale (slope steepness, frequency choice, combined FIR approach)
- [ ] Covers: latency budget analysis (DJ mode vs live mode, singer slapback threshold)
- [ ] Covers: room correction theory (frequency-dependent windowing, psychoacoustic smoothing, regularization, why not to correct nulls)
- [ ] Covers: filter length vs frequency resolution tradeoff
- [ ] Covers: time alignment principles
- [ ] References decisions D-001 through D-004
- [ ] Content extracted and expanded from CLAUDE.md "Critical Design Decisions" and "Next Steps" sections — not duplicated but properly structured

**DoD:**
- [ ] Document written at `docs/theory/signal-processing.md` (or appropriate path)
- [ ] Audio engineer review passed (technical accuracy)
- [ ] Technical writer review passed (clarity, structure)

---

## US-016: How-To Guides

**As** a user of the audio workstation,
**I want** task-oriented how-to guides for common operations (initial setup,
switching modes, running calibration, connecting controllers, headless
operation),
**so that** I can perform each task without reading the entire setup manual.

**Status:** draft
**Depends on:** US-014 (documentation structure must exist), US-012 (calibration how-to depends on the automation script existing)
**Blocks:** none
**Decisions:** none

**Note:** The how-to for room calibration (US-012's DoD includes a how-to)
should live in this collection. Other how-tos can be written as the
corresponding features are implemented.

**Acceptance criteria:**
- [ ] At minimum these guides written:
  - Initial hardware setup (power on, verify audio stack starts)
  - Switching between DJ/PA and Live mode
  - Connecting and verifying MIDI controllers
  - Remote operation via RustDesk
  - Basic troubleshooting (no sound, xruns, high CPU)
- [ ] Each guide is self-contained: a user can follow it without reading other docs
- [ ] Each guide includes prerequisites and expected outcomes
- [ ] Content distilled from SETUP-MANUAL.md, not copy-pasted — restructured for task orientation

**DoD:**
- [ ] Guides written in `docs/guide/howto/`
- [ ] Technical writer review passed
- [ ] Audio engineer review passed (operational correctness)

---

## Tier 5 — Singer IEM and Live Mode

Stories specific to live vocal performance mode.

---

## US-017: Singer IEM Mix — Engineer-Controlled Independent Mix

**As** the live sound engineer,
**I want** to control the singer's in-ear monitor mix independently of the main
PA mix and the engineer headphone mix,
**so that** the singer hears an optimal monitor blend (her voice, backing tracks,
vocal cues) without affecting what the audience hears.

**Status:** draft
**Depends on:** US-003 (live mode stability confirmed)
**Blocks:** US-018 (singer self-control is a future enhancement of this)
**Decisions:** D-002 (live mode chunksize 512)

**Note:** MVP scope per owner direction: engineer controls the IEM mix. Singer
self-control of her own mix is a nice-to-have (see US-018). IEM signal path
per owner confirmation: Reaper -> USBStreamer ch 7/8 directly, bypassing
CamillaDSP entirely.

**Known issue (AD finding A11):** The 4-channel loopback routing from Reaper
through PipeWire to CamillaDSP (for the PA path) is not documented in
SETUP-MANUAL.md. This routing must be validated as part of this story since
the IEM path (Reaper direct to USBStreamer) coexists with the PA path
(Reaper -> PipeWire -> loopback -> CamillaDSP -> USBStreamer ch 1-4).

**Acceptance criteria:**
- [ ] Reaper routing configured: singer IEM outputs (USBStreamer channels 7-8) receive an independent mix routed directly from Reaper, bypassing CamillaDSP
- [ ] PA path routing validated: Reaper main outputs route through PipeWire JACK bridge to ALSA loopback, which CamillaDSP reads (AD finding A11)
- [ ] Both paths coexist: IEM direct path and PA loopback path work simultaneously without conflicts
- [ ] IEM mix sources: vocal mic (ch 1), backing tracks from Reaper, vocal cue track from Reaper
- [ ] IEM mix independent of main PA mix (changing PA levels does not affect IEM)
- [ ] IEM mix independent of engineer headphone mix (channels 5-6)
- [ ] Engineer can adjust IEM mix levels via Reaper mixer (and optionally via MIDI controller)
- [ ] Vocal cue track routed to IEM only (not to PA or engineer headphones)
- [ ] Low latency confirmed: IEM path avoids CamillaDSP convolution, total latency ~5ms (Reaper + USB + ADAT)

**DoD:**
- [ ] Reaper routing configuration written (IEM path is Reaper-only, does not involve CamillaDSP)
- [ ] Full signal routing diagram documented: which Reaper outputs go where (PA via loopback, IEM direct, engineer headphones)
- [ ] Reaper OSC interface verified working on Pi 4B (prerequisite for US-018 singer web UI control)
- [ ] Configuration validated on Pi 4B hardware with actual routing through USBStreamer ch 7/8
- [ ] Audio engineer review passed
- [ ] Lab note documenting the routing and confirming independence of mixes

---

## US-018: Singer Self-Control of IEM Mix via Web UI

**As** the singer,
**I want** to adjust my own in-ear monitor mix levels (more/less voice, more/less
backing track) from a simple web interface on my phone,
**so that** I can fine-tune my monitoring comfort during performance without
needing the engineer's attention.

**Status:** draft
**Depends on:** US-017 (base IEM mix must work first), US-022 (web UI platform provides the delivery mechanism)
**Blocks:** none
**Decisions:** none yet

**Note:** Elevated from "deferred nice-to-have" per owner direction (2026-03-08).
The architecture for role-based web UI access should be planned now even if
this story is implemented after higher-priority work. The singer must see ONLY
her IEM mix controls (ch 7/8 levels), not the main PA mix or system settings.
IEM control goes through Reaper OSC (audio engineer blocking concern: singer
controls must NOT touch CamillaDSP / PA path).

**Acceptance criteria:**
- [ ] Singer accesses a web page on her phone (same WiFi network) showing IEM mix controls only
- [ ] UI layout per UX specialist design: 4 sliders (voice level, backing track level, vocal cue level, master IEM volume) + mute toggle, portrait orientation, single screen, no scrolling
- [ ] Controls are large, high-contrast, usable on a phone screen in dim stage lighting
- [ ] Singer view is restricted: no access to PA mix, engineer mix, DSP settings, or system controls
- [ ] IEM level changes sent via Reaper OSC (NOT CamillaDSP) — singer controls cannot affect PA routing
- [ ] Changes do not affect PA or engineer mixes
- [ ] Latency of control changes is imperceptible (< 100ms from slider move to level change in IEM)
- [ ] Authentication: singer role password, exchanged for session token (per US-022 auth model)
- [ ] Security specialist review: role isolation verified (singer cannot escalate to engineer controls)
- [ ] UX specialist review: performer usability confirmed

**DoD:**
- [ ] Singer web UI view implemented on US-022 platform
- [ ] Role-based access tested (singer sees only IEM controls)
- [ ] Tested on Pi 4B with actual phone on same network
- [ ] UX specialist, audio engineer, and security specialist reviews passed
- [ ] Lab note documenting the interface and access model

---

## Tier 5a — Web UI Platform

The owner wants a web-based control and monitoring interface where the Pi
serves data/audio streams and the browser handles heavy rendering (FFT
visualization via WebGPU/Web Audio API). This offloads compute from the
resource-constrained Pi. The platform serves multiple consumers: engineer
dashboard, singer IEM control, and potentially calibration monitoring.

---

## US-022: Web UI Platform — Architecture and Foundation

**As** the system builder,
**I want** a lightweight web server on the Pi that serves a control and
monitoring UI to browsers, with the browser performing all heavy rendering
(FFT visualization, meters, waveforms via WebGPU/Web Audio API),
**so that** I can monitor and control the system from any device on the network
without burdening the Pi's CPU with rendering work.

**Status:** draft
**Depends on:** US-000 (core software must be installed), US-000a (network access must be secured)
**Blocks:** US-018 (singer self-control uses this platform), US-023 (engineer dashboard uses this platform)
**Decisions:** none yet — pending formal decision record

**Note:** Owner direction: browser-side rendering is key. The Pi should serve
data streams (audio levels, DSP state, CamillaDSP stats) and the browser
should do FFT, visualization, and UI rendering. This is a compute-offloading
architecture: the Pi is the data source, the browser is the rendering engine.

**Architectural direction (from advisory team session 2026-03-08):**
- **Backend:** FastAPI + pycamilladsp. FastAPI serves REST/WebSocket endpoints;
  pycamilladsp reads CamillaDSP state. Static files served by FastAPI.
- **CamillaDSP stays on localhost.** The web UI acts as an authenticated proxy —
  browsers never talk to CamillaDSP's websocket directly. This preserves the
  security hardening from US-000a (CamillaDSP bound to 127.0.0.1).
- **IEM control via Reaper OSC, NOT CamillaDSP.** The singer's IEM mix is
  routed through Reaper (US-017). Level adjustments must go through Reaper's
  OSC interface, not CamillaDSP. Audio engineer blocking concern: CamillaDSP
  controls the PA path; singer IEM adjustments must not touch PA routing.
- **Auth model:** Pre-shared role passwords (one for engineer, one for singer)
  exchanged for session tokens. No user accounts — just role-level access.
- **Transport:** HTTP for MVP (LAN-only, trusted network). HTTPS with
  self-signed cert as a future enhancement.
- **Singer phone UI:** 4 sliders (voice, backing, cue, master) + mute toggle.
  Portrait orientation, single screen, no scrolling. Large touch targets for
  dim stage lighting. (UX specialist design direction.)

**Acceptance criteria:**
- [ ] FastAPI server running on Pi, minimal CPU overhead (< 5% idle, < 10% under active use). CPU budget must be validated alongside CamillaDSP + application (Mixxx or Reaper) — web server cannot push total system load past T3 stability thresholds (AD finding — web server adds to constrained CPU budget)
- [ ] Serves static HTML/JS/CSS — all rendering logic runs in the browser
- [ ] WebSocket connection for real-time data push (audio levels, DSP processing load, system stats)
- [ ] Role-based access: two roles — "engineer" (full control) and "singer" (IEM only)
- [ ] Authentication: pre-shared role passwords, exchanged for session tokens
- [ ] API endpoints for reading CamillaDSP state (via pycamilladsp on localhost)
- [ ] API endpoints for writing CamillaDSP parameters (gain, mute — engineer role only)
- [ ] API endpoints for Reaper IEM mix control (via Reaper OSC — singer and engineer roles)
- [ ] CamillaDSP websocket never exposed to browsers — FastAPI proxies all access
- [ ] Browser receives raw data and performs FFT / visualization locally (WebGPU or Web Audio API)
- [ ] Bound to LAN only (not exposed to internet) — security specialist review
- [ ] Accessible via SSH tunnel from outside LAN if needed
- [ ] Works on modern mobile browsers (Chrome, Safari — for singer's phone)

**DoD:**
- [ ] Architecture documented (data flow, API design, auth model, OSC integration)
- [ ] Proof-of-concept: server running on Pi, browser showing live audio level meters
- [ ] Architect, security specialist, and UX specialist reviews passed
- [ ] Lab note with performance measurements (Pi CPU impact, browser responsiveness)

---

## US-023: Engineer Dashboard — Web UI for System Monitoring and Control

**As** the live sound engineer,
**I want** a web-based dashboard showing real-time system status (audio levels,
DSP load, CPU temperature, xrun count, filter state) with controls for
adjusting levels and switching configurations,
**so that** I can monitor and adjust the system from a tablet or laptop without
needing SSH or RustDesk.

**Status:** draft
**Depends on:** US-022 (web UI platform must exist)
**Blocks:** none
**Decisions:** none yet

**Acceptance criteria:**
- [ ] Real-time audio level meters for all 8 channels (input and output)
- [ ] CamillaDSP status: processing load, state, active config, current filter files
- [ ] System status: CPU temperature, CPU usage, memory usage, xrun count
- [ ] FFT / spectrum visualization rendered in browser (WebGPU or Web Audio API) — Pi sends audio data, browser renders
- [ ] Controls: channel gain adjustment, mute/unmute per channel
- [ ] Configuration display: current mode (DJ/PA vs Live), active CamillaDSP config
- [ ] Engineer role required for access (via US-022 auth model)
- [ ] Responsive layout: usable on tablet and laptop screens
- [ ] UX specialist review: dashboard layout is scannable at a glance during live performance

**DoD:**
- [ ] Dashboard implemented on US-022 platform
- [ ] Tested on Pi 4B with real audio flowing
- [ ] UX specialist and audio engineer reviews passed
- [ ] Lab note with screenshots and performance measurements

---

## Tier 6 — Resilience and Operational Maturity

Future stories for production hardening.

---

## US-019: Reproducible System Setup — Lab Notes and Migration Path to NixOS

**As** the system builder,
**I want** meticulous lab notes documenting every installation step, package
version, and configuration choice on the current Trixie platform, plus a
deferred plan for NixOS migration,
**so that** I can reproduce the entire setup on a new SD card or new Pi, and
eventually migrate to a fully declarative NixOS configuration.

**Status:** draft (NixOS migration deferred; lab notes active)
**Depends on:** none
**Blocks:** none directly

**Note:** Owner direction: experiment on Trixie now, keep meticulous notes.
NixOS migration is a future goal, blocked by uncertainty about CamillaDSP,
Mixxx, and Reaper packaging for NixOS.

**Acceptance criteria:**
- [ ] Every package installation captured with exact version (`apt list --installed` snapshot or equivalent)
- [ ] Every configuration file change documented with rationale
- [ ] Every manual step documented in lab notes with enough detail for reproduction
- [ ] NixOS feasibility assessment: which components have Nix packages, which would need custom derivations
- [ ] Migration plan outlined as a future story (not implemented now)

**DoD:**
- [ ] Lab notes maintained throughout all other stories
- [ ] NixOS assessment document written (can be brief)
- [ ] Reproducibility verified: could someone rebuild from the lab notes alone? (review by technical writer)

---

## US-020: Redundancy Plan — Second SD Card, Second Pi, Laptop Fallback

**As** the performer,
**I want** a graded redundancy plan: (1) bootable backup SD card, (2) second Pi
as hot spare, (3) ability to run the stack on a Linux laptop,
**so that** a hardware failure at a gig does not end the show.

**Status:** draft (deferred — future story)
**Depends on:** US-019 (reproducibility is a prerequisite for backup strategies)
**Blocks:** none

**Acceptance criteria:**
- [ ] Level 1: SD card cloning procedure documented and tested (boot backup SD, system works)
- [ ] Level 2: second Pi provisioning procedure documented (same config, swap hardware)
- [ ] Level 3: laptop fallback documented (which components run on x86 Linux, what adapters are needed)
- [ ] Recovery time estimated for each level (how long to switch at a gig)

**DoD:**
- [ ] Procedures documented in how-to guides
- [ ] At least Level 1 tested on hardware
- [ ] Audio engineer review passed (is the fallback audio-viable?)

---

## US-021: Mode Switching — Whole-Gig Configuration Swap

**As** the performer,
**I want** a clean procedure to switch between DJ/PA mode and Live mode before
a gig starts,
**so that** I can configure the system for the type of performance without
error-prone manual config editing.

**Status:** draft
**Depends on:** US-003 (both modes validated), US-006 (Mixxx working), US-017 (live IEM mix working)
**Blocks:** none
**Decisions:** D-002 (dual chunksize)

**Note:** Owner direction: whole-gig switching for now. Mid-event quick switch
is a future nice-to-have and does not need to be seamless.

**Acceptance criteria:**
- [ ] Single command or script to switch from DJ/PA to Live mode (and vice versa)
- [ ] Switch includes: CamillaDSP config swap (chunksize change), application start/stop (Mixxx vs Reaper), PipeWire routing adjustment if needed
- [ ] Switch is idempotent (running it twice does not break things)
- [ ] Pre-switch validation: checks that required services are running, audio device is connected
- [ ] Post-switch verification: confirms audio routing is correct, DSP is processing
- [ ] Procedure documented as a how-to guide
- [ ] UX specialist review: is the switching workflow clear and error-resistant?

**DoD:**
- [ ] Switch script written and syntax-validated
- [ ] Tested on Pi 4B hardware in both directions
- [ ] How-to guide written
- [ ] UX specialist and audio engineer review passed

---

## Summary — Story Dependency Graph

```
US-000 (software install) ──> US-000a (security hardening) ──> [venue deployment]
                          │
                          ├──> US-001 (CPU benchmark) ──┐
                          │                             ├──> US-003 (stability) ──> US-017 (IEM mix)
                          └──> US-002 (latency) ────────┘                      └──> US-021 (mode switch)

US-001 ──> US-008 (measurement) ──> US-009 (time alignment) ──> US-012 (automation) ──> US-013 (T5 verification)
                                └──> US-010 (correction) ──> US-011 (crossover) ──┘

US-000 + US-000a ──> US-022 (web UI platform) ──> US-023 (engineer dashboard)
                                               └──> US-018 (singer IEM self-control)
                                                    ↑ also depends on US-017

US-004 (expanded assumptions) — independent, informs all

US-005 (Hercules MIDI) ──> US-006 (Mixxx feasibility) ──> US-007 (APCmini mapping)
                           ↑ depends on US-000

US-014 (doc structure) ──> US-015 (theory doc)
                      └──> US-016 (how-to guides)

US-019 (reproducibility) ──> US-020 (redundancy)
```
