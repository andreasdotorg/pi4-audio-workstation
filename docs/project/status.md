# Project Status

Last updated: 2026-03-30 (end of session 4). Individual story/defect/decision
details now in `stories/`, `defects/`, `decisions/` directories with corresponding
index files.

## Current Mission

**D-040: Pure PipeWire filter-chain pipeline (CamillaDSP abandoned).**

BM-2 benchmark showed PipeWire's built-in convolver is 3-5.6x more CPU-efficient
than CamillaDSP on Pi 4B ARM (1.70% vs 5.23% at comparable buffer sizes). First
successful PW-native DJ session (GM-12): 40+ minutes, zero xruns, 58% idle, 71C.

**US-072 (NixOS Build) reactivated** — 20 tasks filed, 16 done, IMPLEMENT phase.
Test Pi available at `192.168.178.35` (SSH key working). Production Pi at venue
(unreachable).

## Active Work

| Story | Phase | Summary | Blocker |
|-------|-------|---------|---------|
| US-072 | IMPLEMENT 16/20 | NixOS reproducible build | Remaining 4 tasks need Pi hardware (T-072-05, T-072-13, T-072-18, T-072-19) |
| US-075 | COMPLETE | Local PW integration test env | Done (AC 1-7, `dd019ea`+`25ed785`+`0eaf87c`) |
| US-088 | REVIEW | Direct WS from Rust (CPU fix) | Owner Pi session for deploy |
| US-089 | TEST | Speaker config management web UI | Blocked by F-198 (F-217 FIXED, commit bf15dfe) |
| US-090 | REVIEW | FIR filter generation web UI | ALL ADVISORS APPROVED (Architect + AE + UX). Awaiting owner acceptance. |
| US-091 | IMPLEMENT | Multi-way crossover support | Core engine done; 4 integration defects open (F-188, F-189, F-190, F-191 — N-way topology) |
| US-092 | REVIEW | Per-driver thermal/mechanical protection | ALL ADVISORS APPROVED (Architect + AE + Security). Awaiting owner acceptance. |
| US-093 | REVIEW | Amplifier sensitivity calibration | ALL ADVISORS APPROVED (Architect + AE + Security). Awaiting owner acceptance. |
| US-094 | REVIEW | ISO 226 equal loudness compensation | ALL ADVISORS APPROVED (Architect + AE). Awaiting owner acceptance. |
| US-095 | REVIEW | Graph viz — truthful PW topology | ALL ADVISORS APPROVED (Architect + UX). Awaiting owner acceptance. |
| US-096 | REVIEW | UMIK-1 full calibration pipeline | ALL ADVISORS APPROVED (Architect + AE). Awaiting owner acceptance. |
| US-097 | REVIEW | Room compensation web UI workflow | ALL ADVISORS APPROVED (Architect + AE + UX). Awaiting owner acceptance. AE note: document per-channel sweep sequencing as mandatory. |
| US-098 | TEST | Room correction pipeline verification | P0 done; P1/P2 deferral REJECTED — must verify locally (owner directive, session 5) |
| US-077 | TEST 6/9 | Single-clock timestamp arch | DoD #2-3 in progress, #4 Pi perf regression |
| US-070 | TEST 3/7 | GitHub Actions CI pipeline | Branch protection, QE sign-off |
| US-044 | IMPLEMENT/TEST | Safety protection suite | AC #3-5 implemented (54 tests), AC #1-2/6-8 need Pi. Local-demo verification in progress. |
| US-071 | REVIEW 9/9 | SETUP-MANUAL doc quality | Gate 3 failed: prose rewrite |
| US-084 | IMPLEMENT 10/13 | Level-bridge crate extraction | Pi systemd templates + owner acceptance |
| US-079 | IMPLEMENT | Pre-convolver capture point | Owner re-validation |
| US-080 | IMPLEMENT | Multi-point spectrum analyzer | Owner re-validation |
| US-081 | IMPLEMENT | Peak+RMS meters with clip indicator | Owner re-validation |
| US-082 | IMPLEMENT | Audio file playback in signal-gen | Owner re-validation |
| US-083 | draft | Integration smoke tests | Depends US-075 |
| US-110 | IMPLEMENT 0/17 | Web UI passkey authentication | Architect decomposed 17 tasks |
| US-111 | IMPLEMENT 8/13 | Local-demo PW graph topology redesign | AC #1,2,3,5,7,10,11 done. #4,6 dropped. #8 manual verify. #9 under investigation (T-111-10). |


### Owner-Blocking Items

| Item | Blocked on |
|------|-----------|
| US-088 deploy + acceptance | Owner Pi session |
| US-079/080/081/082 re-validation | Owner local-demo test |
| US-084 Pi deployment | Owner Pi session |
| US-044 Pi tests (T-044-6/7) | Owner Pi session |
| US-077 DoD #4 Pi perf test | Owner Pi session |
| US-063 DoD #6 DJ soak test | Owner Pi session |
| US-089-098 acceptance | Owner prioritization + Pi deploy |
| US-099-104 (Tier 13 venue workflow) | Owner prioritization |

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| PW filter-chain config | deployed | 4ch FIR convolver + gain nodes on Pi |
| GraphManager | deployed | Link topology + mode transitions (port 4002) |
| signal-gen | deployed | RT measurement audio (port 4001) |
| pcm-bridge | deployed | Lock-free level metering (port 9100) |
| Web UI platform | Stage 1+2 deployed | Dashboard, spectrum, config tab, graph viz. HTTPS (D-032) |
| Room correction pipeline | done (TK-071) | 13 DSP modules. Bose profiles measured |
| SETUP-MANUAL.md | draft | ~2200 lines. Gate 3 prose rewrite pending |
| Core software | installed | PipeWire 1.4.9, Mixxx 2.5.0, Reaper 7.64, wayvnc |
| Platform security | partial | Firewall active, SSH hardened. Web UI auth: US-110 (ready, passkey design, D-060 local CA) |
| GitHub Actions CI | merged | Two parallel jobs, Nix store caching. Branch protection pending |
| NixOS build (US-072) | in progress | RT kernel compiles, convolver module designed, 4 tasks remaining (need Pi) |

## Completed Stories

| Story | Summary | Accepted |
|-------|---------|----------|
| US-000 | Core audio software installation | 2026-03-22 |
| US-000a | Platform security hardening | 2026-03-21 |
| US-000b | Desktop trimming for headless | 2026-03-22 |
| US-001 | CamillaDSP CPU benchmark | 2026-03-22 |
| US-002 | Latency measurement | 2026-03-22 |
| US-004 | Assumption register (A1-A28) | 2026-03-21 |
| US-005 | Hercules DJ controller | 2026-03-12 |
| US-006 | Mixxx feasibility | 2026-03-12 |
| US-058 | PW filter-chain benchmark (BM-2) — triggered D-040 | 2026-03-16 |
| US-059 | GraphManager core + production filter-chain | 2026-03-21 |
| US-062 | Boot-to-DJ mode | 2026-03-20 |
| US-076 | Web UI visual polish | 2026-03-25 |
| US-109 | Playwright MCP integration | 2026-03-29 |

## Deferred / Cancelled

| Story | Reason |
|-------|--------|
| US-003 | Deferred: T3d/T4 pending, owner deselected for Tier 11 |
| US-028 | Cancelled: D-040 eliminated ALSA Loopback |
| US-056 | Cancelled: D-040, CamillaDSP abandoned |
| US-057 | Cancelled: D-040, CamillaDSP abandoned |

## Open Blockers

| ID | Severity | Summary |
|----|----------|---------|
| F-187 | Critical | Noise on 4 channels + broken spectrum after multiple PW restarts (diagnosing) |
| F-209 | ~~P1 / High~~ | ~~US-044 watchdog/gain integrity assume builtins are separate PW nodes~~ VERIFIED (session 4, 248 tests pass) |
| F-037 | High | Web UI no auth — converted to US-110 (ready, blocked on D-060 implementation) |
| F-061 | ~~High~~ | ~~pw-dump subprocess hangs under WebSocket load~~ VERIFIED (session 4) |
| F-016 | Medium | Audible glitches after PW restart with capture adapter |
| F-013 | Medium | wayvnc TLS needed before US-018 guest devices |
| F-039 | Medium | DSP load gauge 0% — needs pw-top BUSY parsing |

## Key Metrics

| Metric | Value |
|--------|-------|
| Git commits | ~197 |
| Total stories filed | 115 |
| Stories done | 13 |
| Stories in TEST | 5 (US-089, US-077, US-070, US-044, US-098) |
| Stories in REVIEW | 8 (US-088, US-090, US-092-097) |
| Stories in IMPLEMENT | ~7 |
| Stories ready | 0 |
| Open defects (HIGH+) | 2 (F-187, F-037) |
| Open defects (Medium) | ~17 |
| Total defects filed | 219 |
| Test suites | test-all (537), test-e2e (194) |
| PW convolver CPU (q1024) | 1.70% |
| PW convolver CPU (q256) | 3.47% |
| PA path latency (q256) | ~5.3ms |
| Longest stable run | 13h 39m, zero xruns (O-018) |

## External Dependencies

| Dependency | Status |
|------------|--------|
| Pi 4B hardware | Available (test Pi at 192.168.178.35) |
| Core software | Installed (PW 1.4.9, Mixxx 2.5.0, Reaper 7.64) |
| Hercules USB-MIDI | Enumeration confirmed, full test pending |
| APCmini mk2 mapping | Research needed |

## Key Decisions

See `decisions/` directory and `decisions-index.md` for all 60 decisions (D-001
through D-060). Most significant recent decisions:

- **D-040** (2026-03-16): Abandon CamillaDSP — pure PipeWire filter-chain pipeline
- **D-043** (2026-03-20): WirePlumber retained for device management, linking disabled
- **D-045** (2026-03-24): Project rename to mugge
- **D-058** (2026-03-28): GM supervises services — target arch (static units interim)
- **D-060** (2026-03-29): Local CA for TLS — replaces D-032 self-signed (unblocks US-110 passkeys)

## Session 4 Summary (2026-03-30)

### Commits

| SHA | Description |
|-----|-------------|
| 56a83a6 | docs(project): US-111/US-110 → IMPLEMENT, status updates |
| 54bad97 | docs(project): F-209 verified — gain_integrity fix confirmed, 248 tests pass |
| 2cfb477 | docs(project): F-061 verified — all PW subprocess calls use asyncio.to_thread |
| 7c0bd96 | (worker commit — US-072 / US-111 code) |
| 6a4ee23 | (worker commit — US-072 / US-111 code) |
| pending | docs(project): advance 8 stories to REVIEW, file F-217, US-111 scope revision |

### Accomplishments

1. **F-061 VERIFIED** — all PW subprocess calls migrated to `asyncio.to_thread(subprocess.run)`. Zero `create_subprocess_exec` instances remain. 827 tests pass.
2. **F-209 VERIFIED** — gain integrity + watchdog fixed. Both modules now use realistic convolver param model (not top-level nodes). 248 tests pass.
3. **HIGH+ defects reduced 4 → 2** — F-061 and F-209 verified. Remaining: F-187 (Critical, blocked/venue), F-037 (High, converted to US-110).
4. **7 stories advanced to REVIEW** — US-090, US-092-097 passed QE Gate 1. US-091 conditional (4 integration defects: F-188/189/190/191). US-098 contingent on owner P1/P2 deferral sign-off.
5. **US-111 scope revised** — T-111-01 spike confirmed WP required on PW 1.6.x. AC #4 (spa-node-factory clock) and AC #6 (WP elimination) DROPPED. 14 tasks → 13. Room-sim filter-chain and loopback components proceed.
6. **US-111 moved to IMPLEMENT** — architect decomposed 13 tasks (post scope revision), implementation started.
7. **US-110 moved to IMPLEMENT** — architect decomposed 17 tasks for passkey auth.
8. **F-217 filed (Medium)** — conftest filter gap (`/ws/pcm` 403 in mock mode). Blocks US-089 clean Gate 1.
9. **US-072 Pi-free sub-work identified** — ~5.5h: smoke test script, service dependency review, disko config, nixos-anywhere research, upgrade runbook.
10. **nixos-upgrade.md written** — T-072-19a complete. HOWTO for nixos-anywhere + nixos-rebuild deployment.

### Owner Notifications

1. **WP removal architecturally impossible on PW 1.6.x** — T-111-01 spike confirmed filter-chain ports require WirePlumber for activation. `spa-node-factory` clock driver enters error state. This is a permanent constraint, not a workaround gap. US-111 proceeds with WP retained (policy disabled).
2. **US-098 P1/P2 deferral REJECTED** — Owner directive (session 5): P1 (channel identity) and P2 (transient fidelity) must be verified in local-demo. US-098 reverted to TEST.
3. **7 stories ready for advisory review** — US-090, US-092-097 passed Gate 1, pending advisory sign-offs and owner acceptance. US-091 reverted to IMPLEMENT (4 integration defects).

### Pending for Next Session

1. **US-111 implementation** — room-sim filter-chain, loopback ada8200-in, process cleanup. 12 tasks remain.
2. **US-110 implementation** — passkey auth. 17 tasks. D-060 local CA prerequisite.
3. **US-072 Pi deployment** — test Pi at 192.168.178.35, nixos-anywhere ready.
4. **Advisory reviews** — 7 stories (US-090, US-092-097) need architect, AE, security, UX sign-offs. US-091 reverted to IMPLEMENT.
5. **F-187 (Critical)** — noise on 4 channels after PW restarts. Requires physical Pi at venue.
6. **F-217 fix** — conftest filter gap. Quick fix, unblocks US-089 Gate 1.
7. **US-098 P1/P2 local verification** — Owner rejected deferral. P1 (channel identity) and P2 (transient fidelity) must pass in local-demo.

## Session 3 Summary (2026-03-29)

(See git history for session 3 details. Key: D-060 filed, US-110/US-111 created,
NixOS closure trim, F-181/F-195/F-196 resolved, test Pi SSH access established.)
