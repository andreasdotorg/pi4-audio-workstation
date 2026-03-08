# Task Register

Tasks are sub-story work items tracked below the story level. Each task belongs
to a parent story or is standalone infrastructure work. This file is the single
source of truth for items that are too granular for a user story but too important
to forget.

**Owner:** Project Manager
**Maintenance rule:** When any lab note, status update, or discussion surfaces a
new item that is not a full story, add it here with a source citation.

Status: `open` | `in-progress` | `blocked` | `done` | `wont-do`

---

## Active Tasks

| ID | Description | Owner | Status | Parent | Source | Notes |
|----|-------------|-------|--------|--------|--------|-------|
| TK-001 | UMIK-1 timing/sync research: does the USB audio stream provide a timing reference or sync signal? Does it have built-in latency measurement capability? | audio-engineer | open | standalone | user-stories.md:217, :226 (US-002 AC) | Owner-flagged dropped item. Two angles: (1) sync signal in USB stream, (2) latency measurement capability. Neither requires Pi access -- spec/documentation research. |
| TK-002 | Create CamillaDSP `active.yml` for systemd auto-start | unassigned | open | standalone | US-000 installation TODO #8, status.md line 67 | Blocks systemd service enable. Needs a valid config at `/etc/camilladsp/configs/active.yml`. Could symlink to dj-pa.yml or live.yml. |
| TK-003 | Test gpu_mem=128 for Mixxx (default ~76MB may be insufficient for OpenGL) | unassigned | blocked | US-006 | CLAUDE.md line 310, US-000 installation TODO #2 | Blocked on: Mixxx smoke test (TK-015). Can only test once Mixxx launches. |
| TK-004 | Decide: measurement pipeline uses REW or pure Python | architect | open | US-008 | CLAUDE.md line 309 | Architectural decision. REW = proven tool but Java dependency. Pure Python = full control, no JVM. Affects US-008 through US-013. |
| TK-005 | Investigate CamillaDSP websocket API for runtime filter hot-swapping | unassigned | open | US-008/US-012 | CLAUDE.md line 313-314 | Can filters be updated without restarting the service? Critical for measurement pipeline UX. |
| TK-006 | Flight case design: ventilation, cable routing, power distribution | unassigned | open | standalone (D-012) | CLAUDE.md line 317 | D-012 mandates active cooling. Blocks US-003 T4 (thermal test in flight case). Physical hardware task. |
| TK-007 | Disable cloud-init (~3.3s boot overhead) | unassigned | open | US-024 | US-000 installation TODO #7, status.md line 67 | Low priority. Permanent installation, not cloud. |
| TK-008 | Monitor pycamilladsp PyPI for Python 3.13 compatibility | unassigned | open | standalone | US-000 installation TODO #4 | Currently installed from GitHub. Watch for PyPI release. |
| TK-009 | PipeWire vs native JACK latency/stability comparison | unassigned | open | standalone | CLAUDE.md line 312 | Low priority -- PipeWire works. JACK alternative is speculative. |
| TK-010 | Live mode: evaluate whether shorter FIR filters would benefit chunksize 256 | unassigned | open | standalone | CLAUDE.md line 315-316 | Likely wont-do: US-001 proved 16k taps viable at chunksize 256 (19.25% CPU). |
| TK-011 | Install and test REW on Pi 4 ARM | unassigned | open | US-008 | CLAUDE.md line 308 | Java-based, should run on ARM. Useful for ad-hoc verification even if pipeline is pure Python. ~10 min task. |
| TK-012 | Verify CUPS/rpcbind port status | security-specialist | open | US-000a | US-000 installation TODO #5 | Listed as listening in pre-conditions but not checked post-hardening. May already be resolved. |
| TK-013 | Lab notes T6: correct latency budget (old IEM bypass assumption) | technical-writer | open | US-002 | status.md line 67 | Cosmetic correction. D-011 supersedes the old model but the lab note text should be accurate. |
| TK-014 | Verify Reaper installation path convention (/home/ela/opt vs /opt) | unassigned | open | standalone | PM observation during US-000b review | Minor -- confirm whether ~/opt is intentional (Pi-Apps default) or should be /opt. |
| TK-015 | Mixxx smoke test: connect via RustDesk, launch Mixxx, verify it renders and plays audio | unassigned | open | US-029 | team-lead directive (UAT gap) | Zero user testing done so far. All validation has been synthetic. First step toward DJ mode UAT. |
| TK-016 | Reaper smoke test: connect via RustDesk, launch Reaper, verify it runs with a project loaded | unassigned | open | US-030 | team-lead directive (UAT gap) | Reaper is installed but never launched with a real project. |
| TK-017 | Hercules USB-MIDI functional test: actual DJ control, not just enumeration | unassigned | open | US-005/US-029 | team-lead directive (UAT gap) | US-005 AC covers enumeration. This tests actual MIDI control messages, fader response, button mapping. Prerequisite for US-029 DJ UAT. |
| TK-018 | CamillaDSP stderr logging rule: all future test runs must use `2>/path/to/log` or run under systemd | unassigned | open | standalone | US-003 T3c analysis (lab notes line 527) | Monitoring gap: when CamillaDSP runs under sudo (not systemd), buffer underruns go to stderr only, not journal. Process improvement for all future tests. |
| TK-019 | US-003 T3a (real): DJ mode stability with Mixxx + Hercules (30 min) | unassigned | blocked | US-003 | US-003 AC line 251 | Blocked on: TK-015 (Mixxx smoke test), US-005 (Hercules MIDI), US-006 (Mixxx feasibility). AC requires "Mixxx (2 decks, continuous playback)". Current T3b-synth used aplay, not Mixxx. |
| TK-020 | US-003 T3b (real): Live mode stability with Reaper + vocal input (30 min) | unassigned | blocked | US-003 | US-003 AC line 252 | Blocked on: TK-016 (Reaper smoke test), Reaper project with backing tracks + FX chain. AC requires "Reaper (8-track backing + FX)". |
| TK-021 | US-003 T3d: Production-config stability retest (8ch, ~34% load) with Reaper | unassigned | blocked | US-003 | US-003 AC line 254 | Blocked on: TK-020. Validates production config under sustained load (vs benchmark 2ch config). |

---

## Completed Tasks

Items moved here when resolved. Preserves audit trail.

| ID | Description | Owner | Status | Parent | Source | Resolution |
|----|-------------|-------|--------|--------|--------|------------|
| TK-100 | Verify snd-aloop persists across reboot with index=10 | change-manager | done | US-000 | US-000 installation TODO #1 | DONE in T6. Loopback at card 10 after reboot. |
| TK-101 | Fix USBStreamer 4-channel capture (PipeWire sees only 4ch) | change-manager | done | US-028 | US-000 installation TODO #3 | DONE in T5 + US-028. Explicit PipeWire config with 8 channels. |
| TK-102 | Install RTKit for PipeWire real-time priority | change-manager | done | US-000b | US-000 installation TODO #6 | DONE in US-000b. RTKit installed, PipeWire FIFO rtprio 83-88. |
| TK-103 | PipeWire TS scheduling (running timeshare, not FIFO) | change-manager | done | US-000b | US-001 lab notes line 369, status.md | RESOLVED by US-000b. PipeWire now runs FIFO rtprio 83-88. |
| TK-104 | PipeWire Loopback stereo-only (BLOCKER for production 8ch routing) | change-manager | done | US-028 | US-003 stability tests line 171 | RESOLVED by US-028. Custom PipeWire profile + WirePlumber rules deployed. |
| TK-105 | PREEMPT_RT kernel package availability check | change-manager | done | US-003 | CLAUDE.md line 311 | DONE. `linux-image-6.12.47+rpt-rpi-v8-rt` available in Trixie repos. Installed in T3e Phase 1-2. |
| TK-106 | Fix CamillaDSP ALSA path (hw:3,0 -> hw:USBStreamer,0) | change-manager | done | US-000b | US-000b lab notes line 434-438 | DONE in US-000b T7. Stable ALSA name prevents USB renumbering failures. |

---

## Notes

- Tasks TK-001 through TK-021 are active. TK-100+ are completed (numbering gap is intentional for clarity).
- US-003 T3e Phase 3 (30-min RT stability + cyclictest) is actively running -- tracked in US-003 DoD, not as a separate task here.
- UAT stories created by product owner: US-029 (DJ UAT), US-030 (Live UAT), US-031 (Full Rehearsal). TK-015/016/017 are prerequisite smoke tests.
- The "T3b" in lab notes `US-003-stability-tests.md` is synthetic (CamillaDSP + aplay). The real T3b per AC requires Reaper load (TK-020).
