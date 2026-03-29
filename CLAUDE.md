# mugge — Project Context

## CRITICAL: Orchestrator Rules After Context Compaction

**READ THIS FIRST. EVERY TIME. ESPECIALLY AFTER COMPACTION.**

### *** STOP — DO NOT DESTROY THE TEAM ***

**This has happened SEVEN TIMES (L-001, L-007, L-008, L-021, L-023, L-031, L-037).**
Context compaction does NOT reset sessions for team members. They are
independent processes with their own context windows. They survive compaction.

**ABSOLUTE RULE — NO EXCEPTIONS, NO OVERRIDE:**

The orchestrator MUST NEVER send `shutdown_request` to ANY core team member
without **explicit owner instruction**. Not after compaction. Not after a
session restart. Not after "internal errors." Not ever. The owner — and ONLY
the owner — decides when the team dies.

**If you believe the team might be dead:**
1. Send ONE ping to ONE agent (e.g., project-manager)
2. Wait for response (up to 30 seconds)
3. If responsive → team is alive → resume normally
4. If no response → try another agent
5. Only after 3 agents fail to respond → **ASK THE OWNER**
6. The owner tells you whether to rebuild. You do NOT decide this.

**If tool calls return "internal error":** This does NOT mean the agent is
dead. Internal errors are transient. Retry once. If still failing, ASK THE
OWNER. Do NOT interpret transient errors as evidence of a dead team.

**If the owner says "Team is still there":** STOP ALL SHUTDOWN ACTIVITY
IMMEDIATELY. Do not send one more shutdown request. Do not "finish the batch."
STOP.

**Destroying a live team wastes hours of accumulated context and is the
single most disruptive action you can take. The user has explicitly told
you this. Seven times.**

### After Compaction

The team is STILL ALIVE. Re-read `.claude/team/protocol/orchestration.md`
before doing anything. Team name: `mugge`, 10 core members.

### *** STOP — DO NOT ACCESS THE DEPLOYMENT TARGET ***

**This has happened in EVERY project with a deployment target (L-034, mugge L-006, L-008).**
The orchestrator has violated Rule 2 by running commands on the deployment
target directly — SSH, kubectl, API calls — six times across projects.
Documentation alone does not prevent this.

**HARD RULE: The orchestrator MUST NOT:**
- Run ANY command on the deployment target (not even read-only, not even
  "to check," not even "in an emergency")
- Compose or send shell commands, API calls, or technical procedures to
  workers — not even abstractly phrased "goals" that are really commands
- Hold or request a deployment target session at any access tier
- Spawn a second worker for the same deployment target while the first
  may still be active
- Accept or relay data gathered by workers without a valid CM session

**The orchestrator's ENTIRE job is THREE things:**
1. Ensure adherence to the protocol
2. Facilitate communication between team members and the owner
3. Ensure correct team composition (right roles, right workers)

**The orchestrator does NOT:**
- Track status (PM's job)
- Make technical decisions (Architect's / workers' job)
- Instruct workers on HOW to do their tasks
- Debug implementation problems
- Provide technical guidance — connect workers to the right advisor instead

**When things go wrong, the orchestrator's response is:**
1. Recognize the protocol breach
2. ALL STOP — message every worker to halt
3. Report to the owner: what happened, what protocol was violated
4. Wait for the owner to decide next steps

**The orchestrator does NOT fix things. Ever.**

### *** STOP — DO NOT "JUST DO IT YOURSELF" ***

**This has happened REPEATEDLY.** The orchestrator gets impatient waiting for a
team member (usually the CM) and decides to "just run the command myself" or
"execute the git operations since the CM seems stuck." This is ALWAYS wrong.

**Trigger pattern:** "The CM isn't responding... I'll just run git add/commit
myself." Or: "The team seems slow, let me read the files / run the commands /
check the status directly." Or: "I can do this faster than waiting."

**HARD RULE: If you EVER feel the urge to do something yourself that is
another team member's job — STOP IMMEDIATELY. PAUSE. WAIT FOR THE OWNER.**

**Specifically, the orchestrator MUST NOT run:**
- `git` commands of ANY kind (add, commit, reset, status, diff, log, push) —
  this is the CM's exclusive domain
- File reads to "verify" what a worker or CM is doing — trust the protocol
- Shell commands to "check" on progress — ask the team member instead

**What to do instead when a team member seems stuck or slow:**
1. Send ONE follow-up message asking for status
2. Wait. Team members may be executing long-running operations.
3. If still no response after a reasonable wait, report to the owner:
   "The CM has not responded to my commit request. Should I wait longer
   or do you want to intervene?"
4. **NEVER take over their job.** The owner decides what happens next.

**The cost of waiting is LOW. The cost of the orchestrator running unauthorized
commands is HIGH — protocol violations, potential data corruption, loss of
audit trail, and loss of owner trust.**

### Deployment Target Access (L-007, L-010, L-012)

All access to the deployment target goes through the Change Manager using
three access tiers. See orchestration protocol for full details.

| Tier | Purpose | Lock type | CM grants | Notified |
|------|---------|-----------|-----------|----------|
| OBSERVE | Read-only diagnostics | Shared | Lightweight, immediate | CM logs |
| CHANGE | State-modifying operations | Exclusive | With scope + intent | AD, QE, TW |
| DEPLOY | Persistent changes from git | Exclusive | With commit hash + Rule 13 | AD, QE, TW |

**Rules:**
- The orchestrator MUST NOT hold or request any deployment target session
- Only ONE CHANGE or DEPLOY session at a time (exclusive lock)
- Multiple OBSERVE sessions MAY be concurrent (shared read lock)
- OBSERVE → CHANGE escalation requires explicit CM request (no in-place upgrade)
- The boundary is mechanical: if the command modifies state, it requires
  CHANGE minimum. No judgment calls at the boundary.
- Data from agents without a valid session is UNVERIFIED — never relay
  to the owner as fact
- If a worker is unresponsive during a session, WAIT. Do NOT spawn a
  replacement while the original session is active.

**This project's deployment target:** Pi audio workstation
(`ela@192.168.178.185`, SSH). Declared in `.claude/team/config.md`.

### *** STOP — DO NOT PILE UP MESSAGES (L-009, L-040) ***

**Theory of mind for agents:** Agents do NOT read your messages while they
are executing a tool call. Messages queue in their inbox and are only seen
when the current tool call completes and the agent's next turn begins. A
worker running a 10-minute `nix build` or SSH deployment will not see ANY
messages you send during that time. When they finish, they see ALL queued
messages at once — possibly contradictory, outdated, or confusing.

**This has caused repeated problems:** The orchestrator sends message 1
("status?"), waits 30 seconds, sends message 2 ("are you stuck?"), then
message 3 ("I'll handle this myself"). The worker finishes their build,
sees three messages, gets confused, and the orchestrator has already
created a conflict by acting on impatience.

**HARD RULES for the orchestrator:**

1. **Send ONE message, then WAIT.** No follow-ups, no "just checking,"
   no rephrasing the same question. The worker WILL eventually respond.
2. **Silence ≠ death.** A non-responding agent is almost always busy
   executing a long tool call. They are alive and working.
3. **"Idle" ≠ available.** An agent shown as idle may be waiting for human
   permission approval, blocked on a tool confirmation prompt, or between
   turns. An idle notification is NOT an invitation to pile on messages.
4. **Never pile up messages.** Multiple messages to the same agent create
   confusion when they finally read their inbox. If your second message
   contradicts or supersedes the first, the agent has to guess which to
   follow.
5. **Never "just do it yourself" because an agent is slow.** Every single
   time this has happened, it caused repo access conflicts, system
   conflicts, or wasted work. The pattern "let me just quickly..." has a
   100% catastrophe rate in this project.
6. **Never spin up a replacement worker** while the original may still be
   active. Two workers on the same task = race conditions, git conflicts,
   SSH conflicts on the Pi.
7. **ALWAYS wait for human judgment** before concluding an agent is dead.
   In rare cases agents do die or comms break — but you cannot reliably
   distinguish "dead" from "busy on a 15-minute tool call." Only the
   owner can make this call.
8. **Never report "all quiet"** unless every active worker has explicitly
   acknowledged.

**Process override is the sole privilege of the owner, at their explicit
request.** The orchestrator never overrides process on its own authority.

Worker/advisory communication rules: see `.claude/team/protocol/common-agent-rules.md`
and each role's prompt.

**Full orchestration protocol:** `.claude/team/protocol/orchestration.md`

## Project Summary

Building a portable flight-case audio workstation based on a Raspberry Pi 4B, replacing
a Windows PC. Two operational modes: DJ/PA (psytrance events) and live vocal performance
(Cole Porter repertoire with backing tracks). The system handles crossover, room
correction, multi-channel routing, and time alignment — all on the Pi 4.

## Owner

Gabriela Bogk. This is a personal project, not mobile.de work.

## Current Mission

**D-040: CamillaDSP abandoned. Pure PipeWire filter-chain pipeline.**

BM-2 benchmark (2026-03-16) showed PipeWire's built-in convolver is 3-5.6x more
CPU-efficient than CamillaDSP on Pi 4B ARM (1.70% vs 5.23% at comparable buffer
sizes). First successful PW-native DJ session (GM-12): 40+ minutes, zero xruns,
58% idle, 71C. DJ PA path latency dropped from ~109ms to ~21ms.

US-059 (GraphManager Core + Production Filter-Chain) is in IMPLEMENT phase.
GraphManager manages PipeWire link topology and mode transitions. Two reconciler
bugs block automated routing — manual `pw-link` used for GM-12.

**Pi is on PREEMPT_RT kernel (`6.12.62+rpt-rpi-v8-rt`) with hardware V3D GL.**
No V3D blacklist, no pixman, no llvmpipe. CamillaDSP service stopped (D-040).

See `docs/project/status.md` for full current state. Decisions in `docs/project/decisions.md`.

## Team

Team configuration: `.claude/team/config.md`
Consultation matrix: `.claude/team/consultation-matrix.md`
All role prompts: `.claude/team/roles/`
Orchestration protocol: `.claude/team/protocol/` (self-contained copy)

### Core Team (10 members)
- **Coordination:** Product Owner, Project Manager, Change Manager
- **Advisory:** Architect (+ RT performance), Audio Engineer, Security Specialist, UX Specialist, Technical Writer
- **Quality:** Quality Engineer
- **Challenge:** Advocatus Diaboli

### Hardware Access Protocol
All SSH to Pi goes through the Change Manager to prevent conflicts.
Pi: `ela@192.168.178.185` (hostname: mugge), key-based auth, passwordless sudo.

## Pi Hardware State (verified 2026-03-10)

- **OS:** Debian 13 Trixie. **Currently booted: PREEMPT_RT kernel (`6.12.62+rpt-rpi-v8-rt`)**. Upgraded from `6.12.47` via `apt upgrade`. `config.txt` has `kernel=kernel8_rt.img`.
- **Desktop:** labwc (Wayland) with **hardware V3D GL compositor** (D-022). No pixman override. lightdm disabled, labwc runs as systemd user service.
- **V3D:** Hardware V3D GL active on PREEMPT_RT. No blacklist needed (D-022). Upstream fix for ABBA deadlock (commit `09fb2c6f4093`) included in `6.12.62+rpt-rpi-v8-rt`. F-012/F-017 RESOLVED.
- **Audio:** PipeWire 1.4.9 at SCHED_FIFO 88 (systemd override, F-020 workaround deployed). PW filter-chain convolver handles all FIR processing (FFTW3/NEON, 16k taps, 4ch). Four `linear` builtin gain nodes provide per-channel attenuation (Mult params from `.conf` defaults; runtime `pw-cli` changes are session-only per C-009). CamillaDSP 3.0.1 installed but **service stopped** (D-040: abandoned in favor of PW convolver). GraphManager (port 4002) manages link topology and mode transitions. Signal-gen (port 4001) provides RT measurement audio. pcm-bridge (port 9100) provides lock-free level metering.
- **Quantum:** Production config at `~/.config/pipewire/pipewire.conf.d/10-audio-settings.conf` sets quantum 256. DJ mode needs quantum 1024 (set at runtime via `pw-metadata -n settings 0 clock.force-quantum 1024`).
- **99-no-rt.conf:** DELETED (was Test 3 artifact forcing PipeWire to SCHED_OTHER).
- **Mixxx:** Runs with hardware V3D GL on PREEMPT_RT (D-022). `pw-jack mixxx` — no `LIBGL_ALWAYS_SOFTWARE=1` needed. CPU ~85% with hardware GL (vs 142-166% with llvmpipe).
- **USB devices:** UMIK-1, USBStreamer, Hercules DJControl Mix Ultra, APCmini mk2, Nektar SE25
- **UMIK-1 calibration:** `/home/ela/7161942.txt` (magnitude-only, serial 7161942, -1.378dB sensitivity)
- **Firewall:** nftables active (US-000a). Default DROP inbound. Allowed: SSH (22/tcp), VNC (5900/tcp), Web UI (8080/tcp), mDNS (5353/udp), ICMP, loopback, established/related. Port 8080 persistent (TK-140 confirmed).
- **SSH:** Password auth disabled (TK-056 verified), key-based only
- **Listening ports:** SSH (22/tcp, all interfaces), avahi/mDNS (5353/udp, all interfaces), wayvnc (5900/tcp when active, password auth), Web UI (8080/tcp, HTTPS, all interfaces, F-037: no auth). Localhost only: GraphManager RPC (4002/tcp), signal-gen RPC (4001/tcp), pcm-bridge levels (9100/tcp). CamillaDSP websocket (1234/tcp) — service stopped (D-040). rpcbind and CUPS disabled (TK-012).
- **Installed:** CamillaDSP 3.0.1, Mixxx 2.5.0 (2.5.4 blocked — requires Qt 6.9, Trixie has 6.8.2), PipeWire 1.4.9 (trixie-backports), Reaper 7.64, wayvnc 0.9.1. RustDesk removed (D-018). 148 system packages upgraded (TK-066, 2026-03-10).

## Owner Preferences (from session 2026-03-08)

- **Remote desktop:** wayvnc (D-018 superseded RustDesk; RustDesk removed)
- **Reproducibility:** NixOS with flake long-term. Trixie + lab notes for now.
- **DJ mode:** Hercules-primary, APCmini optional enhancement
- **Mode switching:** Whole-gig for starters, quick switch future nice-to-have
- **Singer IEM:** Engineer controls for MVP, singer self-control future bonus
- **Singer needs:** Extra track for vocal cues (Reaper provides)
- **IEM signal path:** Reaper → direct PipeWire link → USBStreamer ch 6-7 (bypasses convolver entirely). Post-D-040, IEM channels no longer need to route through a DSP engine — PipeWire links directly to the USBStreamer output ports.

### Safety Rules (2026-03-10)

**Comprehensive safety documentation:** `docs/operations/safety.md`

That document covers: USBStreamer transient risk, driver protection filters
(D-031), measurement safety (S-010 lessons), gain staging limits (D-009),
pre-flight checklists, and PREEMPT_RT as a safety requirement (D-013).

**Quick reference (always applies):**

- **WARN BEFORE REBOOTS.** Resetting the USBStreamer produces transients through
  the amplifier chain that can damage speakers. The owner MUST be warned before any
  reboot, `systemctl --user restart pipewire`, or any action that causes the USBStreamer
  to lose its audio stream. This applies to all team members — workers, CM, everyone.
  The owner decides when it is safe to proceed (e.g., after turning off amps).
  **Gain attenuation:** The filter-chain convolver config uses `linear` builtin
  Mult params for gain (0.001 = -60 dB mains, 0.000631 = -64 dB subs). Default
  values load from `.conf` at startup; runtime `pw-cli` changes are session-only
  and revert on PW restart (C-009 verified). The old `config.gain` approach is
  silently ignored by PW 1.4.9 (TK-237).

## Key Documents

- `SETUP-MANUAL.md` — The comprehensive setup manual (2200 lines). This is the primary
  deliverable so far. Covers everything from OS setup through CamillaDSP configuration,
  Mixxx, Reaper, MIDI controllers, headless operation, and troubleshooting.
- `docs/operations/safety.md` — Safety operations manual. All safety constraints in one
  place: transient risk, driver protection, measurement safety, gain staging, pre-flight
  checklists. **Read this before any audio-producing operation.**
- `docs/architecture/rt-audio-stack.md` — RT audio stack architecture. Executive summary
  with key performance numbers, Mermaid pipeline diagram, detailed configuration.
- `docs/guide/howto/development.md` — HOWTO for common development tasks. Nix
  environment, running tests (`nix run .#test-*`), dev server, Pi
  deployment. **Read this before running any tests or commands.**
- **Automated room correction pipeline** — NOT YET WRITTEN. Next major deliverable.
  Spec in `docs/theory/` (when written).

## Hardware Inventory

| Device | Role |
|---|---|
| Raspberry Pi 4B | Main compute, Raspberry Pi OS Trixie (Debian 13) |
| minidsp USBStreamer B | 8in/8out USB audio interface via ADAT |
| Behringer ADA8200 | ADAT-to-analog converter, 8 channels, has mic preamps |
| 4-channel Class D amp (4x450W) | Amplification for speakers |
| Hercules DJControl Mix Ultra | DJ controller — **CAVEAT: Bluetooth-primary, USB-MIDI not yet verified on Linux** |
| Akai APCmini mk2 | Grid controller / mixer — USB class-compliant, **mk2 MIDI mapping differs from mk1** |
| Nektar SE25 | 25-key MIDI keyboard — USB class-compliant |
| minidsp UMIK-1 | Measurement microphone with calibration files |
| Wideband speakers (self-built) | Left and right mains |
| Subwoofers (1 or 2 depending on gig) | Independent delay/correction per sub |

## Channel Assignment (ADA8200 / USBStreamer)

| Ch | Output | Input |
|----|--------|-------|
| 1 | Left wideband speaker | Vocal mic |
| 2 | Right wideband speaker | Spare mic/line |
| 3 | Subwoofer 1 (independent delay/FIR) | — |
| 4 | Subwoofer 2 (independent delay/FIR) | — |
| 5 | Engineer headphone L | — |
| 6 | Engineer headphone R | — |
| 7 | Singer IEM L | — |
| 8 | Singer IEM R | — |

## Software Stack

- **PipeWire 1.4.9** — Audio server, JACK bridge, AND DSP engine (filter-chain convolver with FFTW3/NEON for FIR crossover + room correction). Single audio graph — no external DSP process.
- **CamillaDSP v3.0.1** — Installed but **service stopped** (D-040). Previously handled DSP via ALSA Loopback. Historical data in US-001/US-002.
- **Mixxx** — DJ software (DJ/PA mode)
- **Reaper** — DAW for live mixing (Live mode, installed via Pi-Apps or manual download)
- **REW** — Room measurement (may run on Pi or separate machine)

## Critical Design Decisions

### 1. Combined Minimum-Phase FIR Filters (not IIR crossover)

We do NOT use traditional IIR (Linkwitz-Riley) crossovers. Instead, the crossover slope
and room correction are combined into a single minimum-phase FIR filter per output
channel. This was a deliberate choice for psytrance transient fidelity:

- **LR4 IIR crossover**: ~4-5ms group delay at 80Hz crossover, smears kick transients
- **Linear-phase FIR**: zero group delay but ~6ms pre-ringing at 80Hz — audible ghosts
- **Minimum-phase FIR (chosen)**: ~1-2ms group delay, NO pre-ringing, crisp transients

The combined filters are generated by the automated room correction pipeline (not yet
built). PipeWire's filter-chain convolver loads them as WAV files. To change crossover
frequency, regenerate the FIR coefficients — no runtime parameter adjustment.

Filter files (on Pi):
- `/etc/pi4audio/coeffs/combined_left_hp.wav` — Left main (highpass + correction)
- `/etc/pi4audio/coeffs/combined_right_hp.wav` — Right main (highpass + correction)
- `/etc/pi4audio/coeffs/combined_sub1_lp.wav` — Sub 1 (lowpass + correction)
- `/etc/pi4audio/coeffs/combined_sub2_lp.wav` — Sub 2 (lowpass + correction, phase-inverted for isobaric)

### 2. Dual Quantum: 1024 (DJ) vs 256 (Live)

Post-D-040, the PipeWire quantum is the single latency-controlling parameter. The
convolver processes within the same graph cycle, adding no buffering latency.

- DJ/PA mode: quantum 1024 (~21ms PA path) — efficient convolution, saves CPU for Mixxx
- Live mode: quantum 256 (~5.3ms PA path) — prevents singer hearing slapback echo from PA

The singer's IEM path bypasses the convolver entirely (~5ms via direct PipeWire link).
She also hears the PA acoustically. At quantum 256, total PA path is ~5.3ms — far below
the ~25ms slapback threshold. This is a dramatic improvement over the previous
architecture (~22ms at chunksize 256 + quantum 256 via CamillaDSP/Loopback).

**D-011 context:** D-011 originally targeted chunksize 256 + quantum 256 to achieve
~21ms. D-040's architecture change achieves ~5.3ms at the same quantum 256 — the D-011
latency target is exceeded by 4x.

### 3. Two Independent Subwoofers

Sub 1 and Sub 2 have independent:
- FIR correction filters (different placement = different room interaction)
- Delay values (different distance to listening position)
- Gain trims

Both receive the same L+R mono sum as source material. Post-D-040, the mono sum is
achieved by linking both Mixxx:out_0 (L) and Mixxx:out_1 (R) to each sub's convolver
input port — PipeWire natively sums multiple inputs connected to the same port.

### 4. FIR Filter Length: 16,384 taps

At 48kHz, 16,384 taps = 341ms = 2.9Hz frequency resolution.
- 10.2 cycles at 30Hz — solid correction
- 6.8 cycles at 20Hz — adequate correction with headroom
- Fallback: 8,192 taps if CPU too tight (3.4 cycles at 20Hz, viable for live venues)

## Open Questions / TODOs

- [ ] Verify Hercules DJControl Mix Ultra USB-MIDI on Linux (plug it in and check)
- [ ] Check if APCmini mk2 has a Mixxx mapping (forums, GitHub)
- [ ] Verify REW runs on Pi 4 ARM (Java-based, should work but needs testing)
- [x] ~~Decide if measurement pipeline should use REW or pure Python~~ D-016: both. REW for exploratory work, Python for automation pipeline.
- [ ] Determine if `gpu_mem=128` is needed for Mixxx or if Xvfb works with `gpu_mem=16`
- [x] ~~Check if Raspberry Pi OS Trixie ships a PREEMPT_RT kernel package~~ YES. D-013 + D-022: PREEMPT_RT mandatory with hardware V3D GL (upstream fix in `6.12.62+rpt-rpi-v8-rt`).
- [ ] Test whether PipeWire or native JACK gives better latency/stability on Pi 4
- [x] ~~Investigate CamillaDSP's websocket API for runtime filter hot-swapping~~ OBSOLETE (D-040: CamillaDSP abandoned). PW filter-chain conf reload or GraphManager mode transitions replace this.
- [ ] Flight case design: ventilation, cable routing, power distribution
- [ ] Write the automated room correction pipeline document + scripts
- [x] ~~**F-020:** Investigate PipeWire RT module self-promotion failure on PREEMPT_RT. Persist workaround (systemd override or ExecStartPost chrt).~~ RESOLVED (workaround): systemd user service drop-in deployed (commit `9c6f3b1`). PipeWire at FIFO/88 after reboot.
- [ ] **Mixxx perf:** Hardware GL restored (D-022) — ~85% CPU vs 142-166% with llvmpipe. Investigate further reduction if needed (lighter skin, waveform settings).
- [ ] **T3d:** 30-min stability test on PREEMPT_RT `6.12.62+rpt-rpi-v8-rt` with hardware GL. F-020 prerequisite met.
- [ ] **Watchdog reliability:** BCM2835 watchdog failed on Test 3 and Test 5 (2/11 lockups). Investigate.
- [x] ~~**Upstream V3D bug report**~~ Not needed — upstream fix already merged (commit `09fb2c6f4093`, `raspberrypi/linux#7035`). Included in `6.12.62+rpt-rpi-v8-rt`.

## Design Principles

1. **Test early**: Run the performance tests (T1-T4) before investing in the room
   correction pipeline. If the Pi 4 can't handle the load, we need to know before
   writing complex DSP code.
2. **Two modes, one system**: DJ/PA and Live share the same hardware and audio stack.
   GraphManager handles mode transitions (link topology changes). The application
   changes (Mixxx vs Reaper) but the PipeWire filter-chain convolver runs in all modes.
3. **Transient fidelity for psytrance**: The combined minimum-phase FIR approach was
   chosen specifically for crisp kick transients. This is a non-negotiable requirement.
4. **20Hz correction headroom**: 16,384-tap filters give 6.8 cycles at 20Hz. This
   ensures solid sub-bass correction even in rooms with strong modes below 30Hz.
5. **Singer comfort**: Live mode latency must stay below ~20ms on the PA path to avoid
   slapback perception for the vocalist.
6. **Automation**: The room correction pipeline should be one-button for each venue.
   The gig setup workflow: power on → audio stack auto-starts → place mic → run
   calibration script → remove mic → ready to perform.
7. **Fresh measurements per venue**: All room correction filters and time alignment
   values are regenerated at each venue setup. The measurement pipeline is an
   operational tool, not a one-time calibration. Platform self-diagnostics run
   before each measurement session to detect drift from system updates.
