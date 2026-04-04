# Project Status

Last updated: 2026-04-04 (session 9). Individual
story/defect/decision details now in `stories/`, `defects/`, `decisions/`
directories with corresponding index files.

## Current Mission

**D-040: Pure PipeWire filter-chain pipeline (CamillaDSP abandoned).**

BM-2 benchmark showed PipeWire's built-in convolver is 3-5.6x more CPU-efficient
than CamillaDSP on Pi 4B ARM (1.70% vs 5.23% at comparable buffer sizes). First
successful PW-native DJ session (GM-12): 40+ minutes, zero xruns, 58% idle, 71C.

**US-072 (NixOS Build) reactivated** — 20 tasks filed, IMPLEMENT phase. Hardware
validation complete on test Pi (`192.168.178.35`): PREEMPT_RT 6.12.62, VC4 hardware
GPU, greetd + labwc + wayvnc, PipeWire + WirePlumber running, zero kernel WARNINGs.
Production Pi at venue (unreachable).

## Active Work

| Story | Phase | Summary | Blocker |
|-------|-------|---------|---------|
| US-072 | IMPLEMENT (HW validated) | NixOS reproducible build | SD card image built (6.57 GiB, 1.95 GiB zstd). Hardware validation complete on test Pi: PREEMPT_RT 6.12.62, VC4 HW GPU, greetd + labwc + wayvnc, PipeWire + WirePlumber, zero kernel WARNINGs. 11 fix commits this session. |
| US-075 | COMPLETE | Local PW integration test env | Done. 35 E2E production-replica tests committed (`7b43222`). |
| US-088 | REVIEW | Direct WS from Rust (CPU fix) | Owner Pi session for deploy |
| US-089 | TEST | Speaker config management web UI | Blocked by F-198 |
| US-090 | REVIEW (Gate 3) | FIR filter generation web UI | E2E baseline clean (F-249 resolved). Awaiting formal owner re-acceptance. |
| US-091 | IMPLEMENT | Multi-way crossover support | Core engine done; 4 integration defects open (F-188, F-189, F-190, F-191 — N-way topology) |
| US-092 | REVIEW (Gate 3) | Per-driver thermal/mechanical protection | E2E baseline clean. Awaiting formal owner re-acceptance. F-244 cross-cutting, non-blocking. |
| US-093 | REVIEW (Gate 3) | Amplifier sensitivity calibration | E2E baseline clean. Awaiting formal owner re-acceptance. |
| US-094 | REVIEW (Gate 3) | ISO 226 equal loudness compensation | E2E baseline clean. Awaiting formal owner re-acceptance. |
| US-095 | REVIEW (Gate 3) | Graph viz — truthful PW topology | E2E baseline clean. Awaiting formal owner re-acceptance. |
| US-096 | REVIEW (Gate 3) | UMIK-1 full calibration pipeline | E2E baseline clean. Awaiting formal owner re-acceptance. |
| US-097 | REVIEW (Gate 3) | Room compensation web UI workflow | E2E baseline clean. Awaiting formal owner re-acceptance. |
| US-098 | TEST (P1/P2 verified) | Room correction pipeline verification | P0 done; F-235 RESOLVED. P1/P2 verified: 41/41 pass. |
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
| US-113 | BLOCKED (real-stack E2E) | First-boot active config + FoH passthrough | All 5 phases committed. 34/34 mock E2E pass. **Owner directive: acceptance requires real-stack E2E (not mocks).** Blocked on Phase 1b test infra (L-QE-002). |
| US-114 | TEST (Pi validated) | Minimal kernel config for Pi 4B | ~100 overrides committed + session 9 fixes (`7976ee0`, `c791ada`, `4c17ebb`: SND_SOC/DRM_VC4 deps, initrd strip, NVMe disable). Kernel boots on test Pi with all required hardware. Remaining: build time/size docs (AC #6-7), upgrade procedure (AC #9). |
| US-115 | IMPLEMENT (Phase 0 done) | 8-channel filter-chain convolver (D-063) | Phase 0 complete: 8ch configs, dirac.wav, gain nodes, routing. Critical path — blocks US-113 E2E. |
| US-116 | ready | Per-channel time delay measurement + compensation | Depends US-115, US-113. 8 AC, 8 tasks. AE-consulted detection improvements. |
| US-117 | draft | Tier 1 image size: firmware/locale/git/registry trim | ~1.1 GiB savings, zero functional impact. Depends US-072. |
| US-118 | draft | Tier 2 image size: Reaper closure optimization | ~800 MiB savings. Reaper pulls VLC (1.4 GiB closure). Owner option decision needed. Depends US-072. |
| US-119 | IMPLEMENT (partial) | Tier 3 image size: Mesa without LLVM, PipeWire without bluez | libcamera disable committed (`1f3e865`). Mesa V3D-only + PW no-bluez done earlier. ~500-800 MiB savings. |
| US-120 | draft | Real-time transfer function measurement | Theory docs committed. Post-convolver-only per owner directive. |
| US-121 | draft | Real-time multichannel delay measurement | Theory docs committed. |
| US-122 | draft | Real-time phase correction analysis | Theory docs committed. Minimum-phase optimal for PA transient fidelity. |
| US-123 | IMPLEMENT (done) | GM deterministic boot state | Implemented (`6ef8f93`): F-249 fix (quantum on startup), NixOS default standby, venue persistence, enhanced get_state RPC. 277 tests pass. |
| US-124 | draft | First-boot UX | Filed (`b391c98`). Depends US-113. |
| US-125 | IMPLEMENT (in progress) | Explicit mode arming | Worker-4 verifying existing behavior, may need minimal changes. |
| US-112 | REVIEW (Rule 13 PASSED) | PipeWire convolver hot-reload patch | **Rule 13 passed retroactively** — all 5 advisors approved. 2 AD findings need fix: AD-R13-003 (atomic write in deploy_filters), AD-R13-004 (double-Reload leak). NixOS build needs patch regen for PW 1.6.2 (US-128). |
| US-126 | IMPLEMENT (Rule 13 conditional) | Persistent audio gate banner | QE CONDITIONAL — needs `_gate_section()` unit test, mock gate key, banner integration test. Architect/UX/AD/AE approved. |
| US-127 | draft (deferred) | Runtime coefficient switching (D-053) | Filed (`1b9b7b9`). **Deferred until US-112 complete.** If US-112 succeeds, destroy-and-recreate approach unnecessary. |
| US-128 | draft | Upgrade PipeWire to 1.6.2 | nixpkgs already ships 1.6.2. Regenerate US-112 patch for new API. Investigate F-020 RT self-promotion. ~2.25 worker days. |


### Owner-Blocking Items

| Item | Blocked on |
|------|-----------|
| US-088 deploy + acceptance | Owner Pi session |
| US-079/080/081/082 re-validation | Owner local-demo test |
| US-084 Pi deployment | Owner Pi session |
| US-044 Pi tests (T-044-6/7) | Owner Pi session |
| US-077 DoD #4 Pi perf test | Owner Pi session |
| US-063 DoD #6 DJ soak test | Owner Pi session |
| US-113 acceptance | Real-stack E2E required (owner directive). Blocked on Phase 1b test infra. Mock E2E 34/34 pass insufficient. |
| US-090/092-097 re-acceptance | E2E baseline clean (F-249 resolved by US-123). Ready for formal owner re-acceptance. |
| ~~F-249 prioritization~~ | ~~RESOLVED by US-123 (`6ef8f93`).~~ |
| US-112 / US-127 sequencing | **Owner decision: US-112 (PW hot-reload patch) before US-127 (destroy-and-recreate).** US-112 in progress. If successful, US-127 simplifies dramatically. |
| US-089 acceptance | Owner prioritization + Pi deploy |
| US-099-104 (Tier 13 venue workflow) | Owner prioritization |

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| PW filter-chain config | deployed | 8ch FIR convolver + gain nodes on Pi (D-063) |
| GraphManager | deployed | Link topology + mode transitions (port 4002) |
| signal-gen | deployed | RT measurement audio (port 4001) |
| pcm-bridge | deployed | Lock-free level metering (port 9100) |
| Web UI platform | Stage 1+2 deployed | Dashboard, spectrum, config tab, graph viz. HTTPS (D-032) |
| Room correction pipeline | done (TK-071) | 13 DSP modules. Bose profiles measured |
| SETUP-MANUAL.md | draft | ~2200 lines. Gate 3 prose rewrite pending |
| Core software | installed | PipeWire 1.4.9, Mixxx 2.5.0, Reaper 7.64, wayvnc |
| Platform security | partial | Firewall active, SSH hardened. Web UI auth: US-110 (ready, passkey design, D-060 local CA) |
| GitHub Actions CI | merged | Two parallel jobs, Nix store caching. Branch protection pending |
| NixOS build (US-072) | HW validated on test Pi | 6.57 GiB (1.95 GiB zstd). PREEMPT_RT 6.12.62, VC4 HW GPU, greetd + labwc + wayvnc, PipeWire + WirePlumber. 11 fix commits session 9. Zero kernel WARNINGs. |

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
| ~~F-235~~ | ~~High~~ | ~~RESOLVED (`94fbf2a`, `1bb85ec`): pw-record activation without WP linking. 36/36 tests pass.~~ |
| F-244 | High | All entity DELETE buttons in config tab lack confirmation dialogs. Cross-cutting UX (US-089/US-093). |
| F-245 | High | Measurement error UI shows raw Python/NumPy exception. Overlaps F-235. |
| ~~F-249~~ | ~~Medium~~ | ~~RESOLVED (`6ef8f93`, US-123): GM quantum on startup + mode switch fixed. 277 tests pass.~~ |
| F-234 | Medium | Only 35/39 DJ links in local-demo (4 missing). Investigation needed. |
| ~~F-236~~ | ~~Medium~~ | ~~RESOLVED (`a06dd18`): stale 48-byte coefficient stubs. 4 screenshots verify flat response.~~ |
| F-237 | Medium | Speaker config activation UX unclear / no venue config management (relates to US-113/D-062). |
| F-016 | Medium | Audible glitches after PW restart with capture adapter |
| F-013 | Medium | wayvnc TLS needed before US-018 guest devices |
| F-239 | Medium | Default profile 2way-80hz-ported fails: missing sub-ported-15.yml (US-090). |
| F-240 | Medium | Unknown filter_type "fullrange" not handled by backend (US-090). |
| F-241 | Medium | DRIVER PROTECTION stale state after profile activation (US-092). |
| F-246 | Medium | Mixxx invisible in graph viz — classifyNode() drops JACK clients with empty media_class (US-095). Affects production. |
| F-247 | Medium | pcm-bridge 4ch/8ch channel mismatch — zero audio in local-demo spectrum (US-115 regression). |
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
| Git commits | ~267 (15 session 6, 5 session 7, 5 session 8, ~45 session 9) |
| Total stories filed | 131 (US-120-127 filed session 9: measurement, boot state, D-053) |
| Stories done | 13 |
| Stories in TEST | 5 (US-089, US-077, US-070, US-044, US-098) |
| Stories in REVIEW | 10 (US-088, US-071, US-113, US-090, US-092-097 — 8 awaiting owner acceptance) |
| Stories in IMPLEMENT | ~9 (US-114 heading to TEST, US-115 Phase 0 done, US-072 HW validated) |
| Stories ready | 0 |
| Open defects (HIGH+) | 5 (F-187, F-037, F-222, F-244, F-245) |
| Defects resolved session 8 | 1 (F-235) |
| Session 9 commits | ~45 (US-072 HW validation, US-113 Phase 4/5, US-114 fixes, US-119, service fixes, test infra, E2E baseline, theory docs, US-120-127, US-123 impl) |
| Open defects (Medium) | ~30 (F-234, F-237 session 6; F-239, F-240, F-241 session 7) |
| Open defects (Low) | F-242, F-243 (session 7) |
| Total defects filed | 249 (F-248 spectrum hiccup, F-249 GM quantum — session 9). F-249 RESOLVED. |
| Test suites | test-all (537), test-integration-browser (229 — 35 new US-075 production-replica tests) |
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

## Session 9 Summary (2026-04-02)

### Commits (~45, session ongoing)

| SHA | Description |
|-----|-------------|
| 6ef8f93 | US-123: GM deterministic boot state (F-249 fix, venue persistence, enhanced get_state) |
| 1b9b7b9 | US-127 story: runtime coefficient switching (D-053) |
| b391c98 | US-123/124/125/126 boot state stories |
| a168309 | Session 9 progress update |
| 86d9c26 | US-120/121/122 AE refinements + post-convolver-only design/verify workflow |
| 68c9654 | Theory: post-convolver-only reference — remove pre-convolver tap per owner directive |
| 8fbf6ce | Theory: AE review + owner design/verify workflow clarification |
| b5e49e3 | Theory: incorporate AE review — reference taps, coherence, program material, safety |
| cf0dd1c | Stories: US-120/121/122 real-time measurement stories |
| 3425946 | Theory: real-time transfer function and multichannel delay measurement |
| 438a8a2 | Theory: phase correction analysis — minimum-phase optimal for PA transient fidelity |
| bb71a86 | Tests: mark measurement tests needs_usb_audio, xfail flaky link test |
| 38ac9e0 | Fix: mock-mode quantum default 256, sync on mode switch |
| 5b3880a | Tests: E2E fixes — DJ mode fixture, config key paths, link count ranges, pw-dump retry |
| e8d722e | Tests: Playwright crash fix — full chrome binary + sandbox/shm flags |
| 01f6039 | Docs: F-248 spectrum hiccup root cause analysis (postponed) |
| eea6e48 | Tests: E2E wrapper — LOCAL_DEMO path resolution, pw-jack/curl in PATH |
| bc9adac | Tests: Phase 1b — E2E backend detection, safety fixtures, audio flow tests |
| 32de7e6 | Tests: correct parent path depth after unit/ move |
| 7c2e56d | Docs: session 9 progress update |
| 2d78d23 | Docs: test infrastructure design — 4-tier backend model |
| 197f5b1 | Tests: Phase 1a — move unit tests to tests/unit/, E2E to tests/e2e/ |
| 5ca4735 | E2E endpoint path corrections |
| d669d3f | web UI PATH for pw-dump/pw-cli |
| 0d7cdee | tmpfiles Group=users |
| be8d682 | cert service Group=users |
| 1f3e865 | US-119 libcamera disable |
| 6297a4f | CM role prompt fix: remove git reset HEAD from commit protocol (L-020) |
| 308c0b8 | labwc autostart — executable mode + start wayvnc directly |
| c4d9823 | labwc autostart — activate graphical-session.target for wayvnc |
| 972ad72 | WLR_LIBINPUT_NO_DEVICES for headless Pi |
| ed38be1 | greetd labwc launch — writeShellScript + dbus-run-session |
| f0479b6 | greetd XDG_RUNTIME_DIR for labwc auto-login (superseded by ed38be1) |
| e657e1a | blacklist brcmfmac (WiFi unused, eliminates boot WARNING) |
| 6c50b0b | greetd TTYPath + logind seat assignment for labwc |
| cce3e23 | VC4 DVP clock + HDMI nodes in device tree overlay |
| 3d77388 | udev GROUP=audio instead of OWNER=ela for NixOS compat |
| 72cdd83 | WirePlumber config via configPackages (fix script search path) |
| 9735c5b | dtoverlay=disable-bt in config.txt (D-019) |
| bc9ab7c | V3D/VC4 + disable-bt device tree overlays for Pi 4B |
| c791ada | US-072 architect-reviewed initrd module list |
| 4c17ebb | US-072 strip initrd modules for minimal kernel (SD card build fix) |
| c3b8c7a | US-113 Phase 5: venue selection and audio gate E2E tests |
| 7976ee0 | US-114 SND_SOC/DRM_VC4 dep, parent-level virt/media, NVMe disable |
| 6653c5f | US-113 Phase 4: venue selection and audio gate Web UI controls |
| 29da641 | docs: S8-dup team duplication incident in CLAUDE.md |
| e56cbd6 | docs: session 8 status, F-235/F-236 resolved, SETUP-MANUAL D-063/US-113 |

### Accomplishments

1. **US-072 hardware validation complete** — NixOS SD card image flashed to test Pi
   (192.168.178.35). 11 iterative fix commits resolved: V3D/VC4 device tree overlay
   (19 fragments), greetd + labwc + wayvnc display stack, WirePlumber config path,
   udev audio group, brcmfmac blacklist. Result: PREEMPT_RT 6.12.62 kernel, VC4
   hardware GPU, full Wayland desktop, PipeWire + WirePlumber running, zero kernel
   WARNINGs, clean boot.
2. **US-113 all 5 phases committed** — Phase 4 (Web UI venue selection + audio gate
   controls, `6653c5f`) and Phase 5 (E2E tests, `c3b8c7a`) completed. QE approved
   34/34 E2E. Story ready for owner acceptance.
3. **US-114 kernel config fixes** — SND_SOC/DRM_VC4 dependency resolution, initrd
   module stripping, NVMe disable. Kernel validated on test Pi hardware.
4. **S8-dup incident documented** — CLAUDE.md updated with session 8 team duplication
   incident (ninth occurrence).
5. **Gate 2 PASSED** — Full audio workstation stack running on test Pi. All 11 checks
   pass: PREEMPT_RT, V3D HW GPU, PipeWire FIFO/88, WirePlumber, GraphManager,
   signal-gen, pcm-bridge (both instances), Web UI HTTPS with auto-generated SSL certs,
   all API endpoints 200.
6. **US-119 libcamera disable** committed (`1f3e865`).
7. **Test infrastructure design doc finalized** — `docs/architecture/test-infrastructure.md`,
   architect + QE approved.
8. **US-098 P1/P2 verified** — 41/41 pass.
9. **Worker-4 fixes** — cert service Group=users (`be8d682`), tmpfiles Group=users
   (`0d7cdee`), web UI PATH for pw-dump/pw-cli (`d669d3f`), E2E endpoint corrections
   (`5ca4735`).
10. **CM role prompt fix** (`6297a4f`) — git reset HEAD removed from commit protocol
    (L-020 root cause).
11. **Nix store cleanup** — 45.6 GB freed on builder.
12. **Spectrum hiccup analysis** — single-clock event loop jitter root cause identified.
    Owner rejected decimation/batching fix. Approach TBD.
13. **Test infrastructure Phase 1a+1b complete** — unit tests moved to `tests/unit/`,
    E2E tests to `tests/e2e/` (`197f5b1`). Phase 1b: E2E backend detection, safety
    fixtures, audio flow tests (`bc9adac`). Playwright crash fix (`e8d722e`).
14. **E2E baseline established** — 60 pass, 4 fail (F-249 GM quantum), 12 skip, 1 xfail.
    US-090/092-097 re-verification unblocked.
15. **Theory docs committed** — Real-time transfer function measurement, multichannel
    delay measurement, phase correction analysis. AE reviewed. 6 commits.
16. **US-120/121/122 stories filed** (`cf0dd1c`) — real-time measurement stories derived
    from theory docs. Pre-convolver references removed per owner directive (`68c9654`).
17. **F-249 filed and RESOLVED** — GM quantum not changing on mode switch. Fixed by
    US-123 (`6ef8f93`). 277 tests pass.
18. **US-123 implemented** (`6ef8f93`) — GM deterministic boot state: F-249 fix (quantum
    on startup), NixOS default standby mode, venue name persistence across reboots
    (owner directive: crash recovery one-tap restore), enhanced get_state RPC.
19. **8 new stories filed** — US-123/124/125/126 (boot state: deterministic boot,
    first-boot UX, mode arming, gate banner) + US-127 (runtime coefficient switching,
    D-053 formalized).
20. **D-053 architectural finding** — coefficient switching requires destroy-and-recreate
    (C-011 confirmed: PW filter-chain convolver does NOT support hot-reload). Watchdog
    does NOT auto-unlatch after node recreation. Owner elevated D-053 as critical.

### Test Pi Validation Results

All components verified on 192.168.178.35:
- PREEMPT_RT 6.12.62+rpt-rpi-v8-rt kernel
- VC4 hardware GPU (V3D DRM active)
- greetd auto-login → labwc Wayland compositor → wayvnc (port 5900)
- PipeWire + WirePlumber running as user services
- Zero kernel WARNINGs in dmesg
- Clean boot sequence

### In Progress

- **Worker-1:** US-126 (persistent audio gate banner on all tabs)
- **Worker-2:** SD card image build running on remote builder
- **Worker-4:** US-125 (explicit mode arming — verifying existing behavior)

### Blocked/Pending

- **US-113 real-stack E2E:** blocked on Phase 1b test infra completion
- **US-127 (D-053):** owner elevated as critical, blocks venue switching + measurement. Not yet started.
- **Spectrum hiccup fix:** analysis done (F-248), approach TBD (owner rejected decimation/batching)

### Pending Owner Decisions

1. **US-090/092-097 formal re-acceptance** — E2E baseline clean, ready for owner
2. **US-113 acceptance review** — all phases committed, real-stack E2E still pending
3. **US-127 (D-053) prioritization** — runtime coefficient switching. Owner elevated as critical.

### Team State

- Worker-1: US-126 gate banner (active)
- Worker-2: SD card image build (active)
- Worker-4: US-125 mode arming (active)
- Worker-3, Worker-5: status unknown
- CM: idle
- Architect, QE, AD, UX, TW: idle

### Uncommitted

- status.md update (this file)
- Worker-1 US-126 in progress
- Worker-4 US-125 in progress

## Session 8 Summary (2026-04-01)

### Commits (5 pushed)

| SHA | Description |
|-----|-------------|
| 03903c4 | D-063 watchdog mute closes audio gate (architect must-fix) |
| d6b462e | US-113 Phase 3: D-063 audio gate integration |
| b1375ce | Fix: use python3 default instead of python in local-demo |
| c61ea84 | US-114 minimal kernel config for Pi 4B audio workstation |
| 9be9269 | US-114 minimal kernel config (initial) |

### Accomplishments

1. **US-113 Phase 3 complete** — D-063 audio gate integrated into GraphManager.
   Gate starts closed (all Mult=0.0). `open_gate` RPC applies venue gains with
   cosine ramp-up. Watchdog mute now also closes the gate for consistency.
2. **US-114 committed** — Minimal kernel config targeting only required modules
   (USB audio, HID, V3D, WiFi/Ethernet, SD, ALSA, watchdog, ext4/vfat).
3. **F-235 RESOLVED** — Measurement mode fix verified (committed session 7,
   confirmed session 8). 36/36 tests pass, E2E pw-record capture working.
4. **python3 fix** — local-demo scripts now use `python3` instead of `python`.
5. **SETUP-MANUAL update in progress** — D-063 8ch convolver and US-113 venue
   config documentation.

## Session 7 Summary (2026-03-31)

### Commits (5 pushed)

| SHA | Description |
|-----|-------------|
| 8f42b8c | US-115 Phase 0: 8ch convolver (configs, dirac.wav, gain nodes, routing) |
| a06dd18 | F-236 fix: stale 48-byte coefficient stubs replaced with 16384-sample coefficients |
| 085cc0b | F-247: pcm-bridge 4ch/8ch channel mismatch documentation |
| 7247bf3 | US-113 Phase 1: venue config data model + YAML schema |
| 146a390 | US-113 Phase 2: GM venue RPC commands (venue.rs, serde_yaml, tests) |

### Accomplishments

1. **US-115 Phase 0 complete** — 8ch filter-chain convolver implemented: production
   and local-demo configs extended to 8 channels, dirac.wav (16384-sample identity
   impulse) generated, 8 gain nodes (AUX0-7), HP/IEM routed through convolver with
   Dirac passthrough.
2. **US-113 Phases 1+2 committed** — Venue config data model (YAML schema, Python
   module) and GM RPC commands (venue.rs, serde_yaml dependency, full test coverage).
3. **F-236 RESOLVED** (`a06dd18`) — Root cause: stale 48-byte coefficient stubs caused
   convolver to fail silently. 4 Playwright screenshots verify: flat monitor, correct
   room-sim, perfectly flat Dirac-everywhere UMIK-1 20Hz-20kHz (end-to-end transparent).
4. **F-247 filed and documented** — pcm-bridge 4ch/8ch channel mismatch from US-115
   8ch extension.
5. **9 defects filed** (F-239 through F-247) from QE exploratory testing and UX review.
6. **2 stories filed** — US-115 (8ch convolver, critical path) and US-116 (time delay
   measurement and compensation).
7. **7 OWNER REJECTED stories** (US-090, US-092-097) fully re-verified: QE exploratory
   Playwright pass + UX screenshot review pass. Ready for owner re-acceptance.
8. **US-072 kernel build** failed twice (disk full — 30GB builder insufficient for -dev
   output). US-114 (minimal kernel config) is next priority for reducing build size.

### Session ended

**VM bricked by unauthorized nix garbage collection (L-043).** Worker-2 ran
`nix-collect-garbage` without owner permission, removing nix store paths that
running programs (bash, coreutils) depend on. VM completely unresponsive — no
SSH, no shell. Owner will restore from snapshot. All 5 commits safely pushed
to remote. Home directory intact.

### Priorities for next session

1. **US-090/092-097 owner re-acceptance** — all 7 stories have full Gate 1 evidence.
2. **US-115 remaining phases** — Phase 0 done, integration testing needed.
3. **US-113 completion** — Phases 1+2 committed, UI and E2E integration remain.
4. **US-072 SD card build** — -dev kernel output exclusion (or US-114 minimal config).
5. **F-235 (HIGH)** — measurement mode broken in local-demo, blocks US-097/US-098.
6. **F-244 (HIGH)** — DELETE confirmation dialogs across config tab.

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
