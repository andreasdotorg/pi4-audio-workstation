# Project Status

Last updated: 2026-03-31 (session 7, reflecting session 6 work). Individual
story/defect/decision details now in `stories/`, `defects/`, `decisions/`
directories with corresponding index files.

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
| US-072 | IMPLEMENT 16/20 | NixOS reproducible build | Remaining 4 tasks need Pi hardware. SD card build blocked: -dev kernel output fills 30GB builder (owner: exclude -dev) |
| US-075 | COMPLETE | Local PW integration test env | Done. 35 E2E production-replica tests committed (`7b43222`). |
| US-088 | REVIEW | Direct WS from Rust (CPU fix) | Owner Pi session for deploy |
| US-089 | TEST | Speaker config management web UI | Blocked by F-198 |
| US-090 | REVIEW | FIR filter generation web UI | OWNER REJECTED (F-223 NOW FIXED `adb93d9`). E2E re-verification needed. |
| US-091 | IMPLEMENT | Multi-way crossover support | Core engine done; 4 integration defects open (F-188, F-189, F-190, F-191 — N-way topology) |
| US-092 | REVIEW | Per-driver thermal/mechanical protection | OWNER REJECTED (F-223 FIXED). QE pass + UX pass. F-244 (DELETE confirmation) is cross-cutting, non-blocking. |
| US-093 | REVIEW | Amplifier sensitivity calibration | OWNER REJECTED (F-223 FIXED). E2E re-verification needed. |
| US-094 | REVIEW | ISO 226 equal loudness compensation | OWNER REJECTED (F-223 FIXED). E2E re-verification needed. |
| US-095 | REVIEW | Graph viz — truthful PW topology | OWNER REJECTED (F-223 FIXED). E2E re-verification needed. |
| US-096 | REVIEW | UMIK-1 full calibration pipeline | OWNER REJECTED (F-223 FIXED). E2E re-verification needed. |
| US-097 | REVIEW | Room compensation web UI workflow | OWNER REJECTED (F-223 FIXED). E2E re-verification needed. |
| US-098 | TEST | Room correction pipeline verification | P0 done; P1/P2 blocked by F-235 (measurement mode broken in local-demo) |
| US-077 | TEST 6/9 | Single-clock timestamp arch | DoD #2-3 in progress, #4 Pi perf regression |
| US-070 | TEST 3/7 | GitHub Actions CI pipeline | Branch protection, QE sign-off |
| US-044 | IMPLEMENT/TEST | Safety protection suite | AC #3-5 implemented (54 tests), AC #1-2/6-8 need Pi. Local-demo verification in progress. |
| US-071 | REVIEW 9/9 | SETUP-MANUAL doc quality | Gate 3 failed: prose rewrite |
| US-084 | IMPLEMENT 10/13 | Level-bridge crate extraction | Pi systemd templates + owner acceptance |
| US-079 | IMPLEMENT | Pre-convolver capture point | Owner re-validation |
| US-080 | IMPLEMENT | Multi-point spectrum analyzer | Owner re-validation |
| US-081 | IMPLEMENT | Peak+RMS meters with clip indicator | Owner re-validation |
| US-082 | IMPLEMENT | Audio file playback in signal-gen | Owner re-validation |
| US-083 | draft | Integration smoke tests | Depends US-075 (now COMPLETE) |
| US-110 | IMPLEMENT 0/17 | Web UI passkey authentication | Architect decomposed 17 tasks |
| US-111 | IMPLEMENT 8/13 | Local-demo PW graph topology redesign | AC #1,2,3,5,7,10,11 done. #4,6 dropped. #8 manual verify. #9 under investigation (T-111-10). |
| US-113 | deferred/parked | First-boot active config + FoH passthrough | D-062 filed. Owner: 8ch passthrough + universal audio gate. Parked for US-075. |


### Owner-Blocking Items

| Item | Blocked on |
|------|-----------|
| US-088 deploy + acceptance | Owner Pi session |
| US-079/080/081/082 re-validation | Owner local-demo test |
| US-084 Pi deployment | Owner Pi session |
| US-044 Pi tests (T-044-6/7) | Owner Pi session |
| US-077 DoD #4 Pi perf test | Owner Pi session |
| US-063 DoD #6 DJ soak test | Owner Pi session |
| US-090/092-097 re-acceptance | F-223 FIXED (`adb93d9`). E2E re-verification needed, then owner re-acceptance. |
| US-089 acceptance | Owner prioritization + Pi deploy |
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
| F-187 | Critical | Noise on 4 channels + broken spectrum after multiple PW restarts. Blocked — needs Pi at venue. |
| F-037 | High | Web UI no auth — converted to US-110 (ready, blocked on D-060 implementation) |
| F-222 | High | Zombie process accumulation in container dev environment (PID 1 = sleep infinity) |
| F-235 | High | Measurement mode still doesn't work in local-demo. Blocks US-097, US-098. |
| F-244 | High | All entity DELETE buttons in config tab lack confirmation dialogs. Cross-cutting UX (US-089/US-093). |
| F-245 | High | Measurement error UI shows raw Python/NumPy exception. Overlaps F-235. |
| F-234 | Medium | Only 35/39 DJ links in local-demo (4 missing). Investigation needed. |
| F-236 | Medium | UMIK-1 spectrum in test tab shows frequency-dependent rolloff (likely code duplication). |
| F-237 | Medium | Speaker config activation UX unclear / no venue config management (relates to US-113/D-062). |
| F-016 | Medium | Audible glitches after PW restart with capture adapter |
| F-013 | Medium | wayvnc TLS needed before US-018 guest devices |
| F-239 | Medium | Default profile 2way-80hz-ported fails: missing sub-ported-15.yml (US-090). |
| F-240 | Medium | Unknown filter_type "fullrange" not handled by backend (US-090). |
| F-241 | Medium | DRIVER PROTECTION stale state after profile activation (US-092). |
| F-039 | Medium | DSP load gauge 0% — needs pw-top BUSY parsing |
| F-242 | Low | Negative sensitivity returns opaque "write_failed" (US-093). |
| F-243 | Low | Negative phon values accepted client-side (US-094). |

### Defects Resolved in Session 6 (9 total)

| ID | Severity | Resolution |
|----|----------|------------|
| F-223 | High | Auth middleware now opt-in (`adb93d9`). Unblocks 7 stories. |
| F-225 | High | Convolver metering + passthrough coeffs fix (`c27d880`). |
| F-226 | High | UMIK-1 signal path + dead link cleanup (`c27d880`). |
| F-228 | Low | Default gm_mode changed from "dj" to "standby" (`00ff2f9`). |
| F-230 | Medium | Quantum change on mode switch — DJ now sets 1024 (`00ff2f9`). |
| F-232 | High | Topology endpoint stale/empty GM data — push event desync (`8962aab`). |
| F-233 | High | FilterChainCollector poll loop stops updating — push event fix (`8962aab`). |
| F-238 | Low | Documented as trade-off (production gains correct, low in sim). No code change. |
| (session 6 also fixed multiple US-075 audit bugs in commits `3e79abf`, `25b9595`, `180a4a8`) |

## Key Metrics

| Metric | Value |
|--------|-------|
| Git commits | ~212 (15 pushed in session 6) |
| Total stories filed | 118 |
| Stories done | 13 |
| Stories in TEST | 5 (US-089, US-077, US-070, US-044, US-098) |
| Stories in REVIEW | 8 (US-088, US-071, US-090, US-092-097 — 7 REJECTED, F-223 now fixed, E2E re-verification needed) |
| Stories in IMPLEMENT | ~7 |
| Stories ready | 0 |
| Open defects (HIGH+) | 6 (F-187, F-037, F-222, F-235, F-244, F-245) |
| Defects resolved session 6 | 9 (F-223, F-225, F-226, F-228, F-230, F-232, F-233, F-238 + audit bugs) |
| Open defects (Medium) | ~30 (F-234, F-236, F-237 session 6; F-239, F-240, F-241 session 7) |
| Open defects (Low) | F-242, F-243 (session 7) |
| Total defects filed | 245 (F-239 through F-245 filed session 7 from QE+UX reviews) |
| Test suites | test-all (537), test-e2e (229 — 35 new US-075 production-replica tests) |
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

See `decisions/` directory and `decisions-index.md` for all 63 decisions (D-001
through D-063). Most significant recent decisions:

- **D-040** (2026-03-16): Abandon CamillaDSP — pure PipeWire filter-chain pipeline
- **D-043** (2026-03-20): WirePlumber retained for device management, linking disabled
- **D-045** (2026-03-24): Project rename to mugge
- **D-058** (2026-03-28): GM supervises services — target arch (static units interim)
- **D-060** (2026-03-29): Local CA for TLS — replaces D-032 self-signed (unblocks US-110 passkeys)
- **D-061** (2026-03-30): GM manages PW/WP lifecycle — amends D-058 (PW/WP move from systemd to GM-managed)
- **D-062** (2026-03-30): First-boot / active config — symlink-based coefficient management, FoH passthrough baseline, mute-default safety (amends D-010, D-051, D-053)
- **D-063** (2026-03-30): 8ch filter-chain convolver + universal audio gate — owner directive: 8ch passthrough, mandatory gate, cosine ramp-up (amends D-062)

## Session 6 Summary (2026-03-31)

### Commits (15 pushed)

| SHA | Description |
|-----|-------------|
| 3e79abf | Consolidate PW lifecycle, start/stop, US-075 bugs |
| 4d11657 | Mixxx substitute + dirac removal |
| 62105d8 | Monitoring → standby rename (48 files) |
| 0104d30 | Room-sim IR 1024→16384 |
| 25b9595 | US-075 bugs #5, #8, #10 |
| e42cd61 | Docs D-062, D-063, F-224, US-113 |
| 180a4a8 | Fix stale measurement link count assertions |
| c27d880 | F-225/F-226/F-227 convolver metering, passthrough coeffs, dead links |
| 8962aab | F-233/F-232 skip GM push events in RPC response reads |
| 47b66fd | Defect docs F-225 through F-233 |
| 00ff2f9 | F-230 quantum change on mode switch, F-228 default mode standby |
| 3da77d6 | US-114 minimal kernel config story (draft) |
| adb93d9 | F-223 disable auth middleware by default (login page not implemented) |
| 7b43222 | US-075 E2E production-replica validation tests (35 new) |
| b9e4be0 | F-234 through F-238 filed, 7 defects RESOLVED |

### Accomplishments

1. **F-223 RESOLVED** — auth middleware now opt-in via `PI4AUDIO_AUTH_ENABLED=1` (`adb93d9`). Unblocks 7 OWNER REJECTED stories (US-090, US-092-097) for E2E re-verification.
2. **9 defects resolved** — F-223, F-225, F-226, F-228, F-230, F-232, F-233, F-238, plus multiple US-075 audit bugs.
3. **35 new E2E production-replica tests** committed (`7b43222`) for US-075 — mode switching, quantum, topology, meters.
4. **5 new defects filed** from owner morning testing — F-234 (4 missing DJ links), F-235 (measurement mode broken), F-236 (UMIK spectrum rolloff), F-237 (config activation UX), F-238 (sim gains trade-off).
5. **Monitoring → standby rename** across 48 files (`62105d8`).
6. **Room-sim IR length corrected** from 1024 to 16384 (`0104d30`).
7. **US-114** (minimal kernel config) filed as draft story.

### Pending for Session 7

1. **E2E re-verification of US-090, US-092-097** — F-223 fixed, stories unblocked.
2. **F-235 (HIGH)** — measurement mode broken in local-demo. Blocks US-098 P1/P2.
3. **F-234** — 4 missing DJ links. Investigation needed.
4. **F-236** — UMIK spectrum rolloff in test tab. Likely code duplication fix.
5. **US-072** — SD card build blocked on -dev kernel output exclusion.
6. **Status.md update** — this file was stale (session 5).

## Session 4/5 Summary (2026-03-30)

(See git history. Key: F-061/F-209 verified, 7 stories advanced to REVIEW, US-111
scope revised (WP required on PW 1.6.x), US-110/US-111 moved to IMPLEMENT, F-217
filed, nixos-upgrade.md written, US-098 P1/P2 deferral REJECTED by owner.)

## Session 3 Summary (2026-03-29)

(See git history for session 3 details. Key: D-060 filed, US-110/US-111 created,
NixOS closure trim, F-181/F-195/F-196 resolved, test Pi SSH access established.)
