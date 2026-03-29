# Project Status

Last updated: 2026-03-29 (end of session 3). Individual story/defect/decision
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
| US-089 | TEST | Speaker config management web UI | QE + advisory reviews |
| US-090 | TEST | FIR filter generation web UI | QE + advisory reviews |
| US-091 | TEST | Multi-way crossover support | QE + advisory reviews |
| US-092 | TEST | Per-driver thermal/mechanical protection | QE + advisory reviews |
| US-093 | TEST | Amplifier sensitivity calibration | QE + advisory reviews |
| US-094 | TEST | ISO 226 equal loudness compensation | QE + advisory reviews |
| US-095 | TEST | Graph viz — truthful PW topology | QE + advisory reviews |
| US-096 | TEST | UMIK-1 full calibration pipeline | QE + advisory reviews |
| US-097 | TEST | Room compensation web UI workflow | QE + advisory reviews |
| US-098 | TEST | Room correction pipeline verification | P0 done, P1/P2 deferred |
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
| US-110 | ready | Web UI passkey authentication | Unblocked by D-060 (local CA) |
| US-111 | ready | Local-demo PW graph topology redesign | Architect design complete, AE signed off |


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
| F-209 | P1 / High | US-044 watchdog/gain integrity assume builtins are separate PW nodes (fix in progress) |
| F-037 | High | Web UI no auth — converted to US-110 (ready, blocked on D-060 implementation) |
| F-061 | High | pw-dump subprocess hangs under WebSocket load — event loop saturation |
| F-016 | Medium | Audible glitches after PW restart with capture adapter |
| F-013 | Medium | wayvnc TLS needed before US-018 guest devices |
| F-039 | Medium | DSP load gauge 0% — needs pw-top BUSY parsing |

## Key Metrics

| Metric | Value |
|--------|-------|
| Git commits | ~190 |
| Total stories filed | 115 |
| Stories done | 13 |
| Stories in TEST | 12 |
| Stories in IMPLEMENT/REVIEW | ~12 |
| Stories ready | 2 (US-110, US-111) |
| Open defects (HIGH+) | 4 (F-187, F-209, F-037, F-061) |
| Open defects (Medium) | ~15 |
| Total defects filed | 216 |
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

## Session 3 Summary (2026-03-29)

### Commits

| SHA | Description |
|-----|-------------|
| 6714dc0 | feat(nixos): US-072 web-ui service module (session 2 carryover) |
| 2c2311c | docs(project): resolve F-181/F-195/F-196, file F-213/F-214/F-215, verify F-160/F-197 |
| b9a39ea | docs(project): D-060 local CA for TLS, US-110 unblocked to ready |
| c34d3ea | feat(nixos): closure trim — disable docs, speechd, LVM (~15-20% build reduction) |
| 10de928 | docs(project): F-216 zombie process defect, US-111 local-demo redesign story |

### Accomplishments

1. **D-060 filed** — local CA for TLS (amends D-032), unblocks US-110 passkey auth
2. **US-110 moved to ready** — passkey auth story unblocked by D-060
3. **US-111 filed** — local-demo PW graph topology redesign (architect design complete, AE signed off with 6 requirements). Key innovation: room-sim filter-chain replaces USBStreamer + UMIK-1 with identical node names; `support.node.driver` via `spa-node-factory` for WP-free clock
4. **F-216 filed** — zombie/orphan process accumulation from local-demo/test runs
5. **F-213/F-214/F-215 filed** — QE exploratory testing findings from session 2
6. **F-181/F-195/F-196 resolved** — committed with Gate 1 + review approvals
7. **F-160/F-197 verified** — mode restore bug and 3-way target gains confirmed fixed
8. **NixOS closure audit completed** — 5850 build derivations normal, 99 runtime packages. Trim implemented: docs, speechd, LVM disabled (~15-20% build reduction)
9. **Test Pi SSH access** — key added to 192.168.178.35, key-based auth working for root
10. **`nix/nixos/services/web-ui.nix` committed** — session 2 carryover cleared

### Pending for Next Session

1. **US-111 implementation** — local-demo redesign. Design complete, needs empirical `support.node.driver` + filter-chain validation then coding
2. **US-072 Pi deployment** — test Pi accessible, SSH key working, `nixos-anywhere` ready
3. **US-110 implementation** — passkey auth, blocked on D-060 local CA implementation
4. **F-187 (Critical)** — noise on 4 channels after PW restarts, still open
5. **F-209 (P1/High)** — safety modules non-functional, fix in progress
6. **Builder hygiene** — 1,291 zombie processes need reboot to clear (F-216)
