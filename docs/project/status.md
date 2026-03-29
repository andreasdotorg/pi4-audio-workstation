# Project Status

Last updated: 2026-03-29. Individual story/defect/decision details now in
`stories/`, `defects/`, `decisions/` directories with corresponding index files.

## Current Mission

**D-040: Pure PipeWire filter-chain pipeline (CamillaDSP abandoned).**

BM-2 benchmark showed PipeWire's built-in convolver is 3-5.6x more CPU-efficient
than CamillaDSP on Pi 4B ARM (1.70% vs 5.23% at comparable buffer sizes). First
successful PW-native DJ session (GM-12): 40+ minutes, zero xruns, 58% idle, 71C.

**US-072 (NixOS Build) reactivated** — 20 tasks filed, 4 done, entering IMPLEMENT.
Test Pi available at `192.168.178.35`. Production Pi at venue (unreachable).

## Active Work

| Story | Phase | Summary | Blocker |
|-------|-------|---------|---------|
| US-072 | IMPLEMENT 4/20 | NixOS reproducible build | Builder disk space (19G after GC) |
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
| US-109 | IMPLEMENT 3/4 | Playwright MCP integration | AC #4 deferred (needs session restart) |

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
| Platform security | partial | Firewall active, SSH hardened. F-037 (web UI no auth) open |
| GitHub Actions CI | merged | Two parallel jobs, Nix store caching. Branch protection pending |
| NixOS build (US-072) | in progress | RT kernel compiles, convolver module designed, 16 tasks remaining |

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
| F-037 | High | Web UI no authentication — signal-gen controllable by network |
| F-209 | P1 / High | US-044 watchdog/gain integrity assume builtins are separate PW nodes (fix in progress) |
| F-212 | Medium | 55 JS 404 errors for missing static resources across all web UI tabs |
| F-016 | Medium | Audible glitches after PW restart with capture adapter |
| F-013 | Medium | wayvnc TLS needed before US-018 guest devices |
| F-085 | High | Graph tab rendering (10 sub-items, pan+zoom needed) |
| F-039 | Medium | DSP load gauge 0% — needs pw-top BUSY parsing |

## Key Metrics

| Metric | Value |
|--------|-------|
| Git commits | ~185 |
| Total stories filed | 113 |
| Stories done | 12 |
| Stories in TEST | 12 |
| Stories in IMPLEMENT/REVIEW | ~12 |
| Open defects (HIGH+) | ~10 |
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

See `decisions/` directory and `decisions-index.md` for all 59 decisions (D-001
through D-058). Most significant recent decisions:

- **D-040** (2026-03-16): Abandon CamillaDSP — pure PipeWire filter-chain pipeline
- **D-043** (2026-03-20): WirePlumber retained for device management, linking disabled
- **D-045** (2026-03-24): Project rename to mugge
- **D-058** (2026-03-28): GM supervises services — target arch (static units interim)
