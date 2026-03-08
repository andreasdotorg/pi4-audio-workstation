# Decisions Log

Binding decisions made by the project owner. Append-only — never edit a past
decision. Add a new one that supersedes it (reference the old one).

---

## D-001: Combined minimum-phase FIR filters instead of IIR crossover (2026-03-08)

**Context:** Evaluating crossover implementation for a psytrance DJ/PA system where transient fidelity is critical.

**Decision:** Use combined minimum-phase FIR filters that integrate crossover slope and room correction into a single convolution per output channel. Do not use IIR (Linkwitz-Riley) crossovers.

**Rationale:** LR4 IIR crossover has 4-5ms group delay at 80Hz — smears kick transients. Linear-phase FIR has ~6ms pre-ringing at 80Hz — audible ghost attacks. Minimum-phase FIR gives ~1-2ms group delay, no pre-ringing, and allows combining crossover with room correction in one operation.

**Impact:** Crossover frequency cannot be adjusted in CamillaDSP YAML. Filter regeneration required for any crossover change. CamillaDSP loads combined WAV files.

## D-002: Dual chunksize — 2048 (DJ) vs 512 (Live) (2026-03-08)

**Context:** Live mode singer perceives slapback from PA if total path latency exceeds ~25ms.

**Decision:** DJ/PA mode uses chunksize 2048 (42.7ms latency, efficient). Live mode uses chunksize 512 (10.7ms CamillaDSP latency, ~18ms total PA path).

**Rationale:** Singer's IEM path is direct (~5ms). She also hears PA acoustically. At chunksize 2048, PA path = ~48ms — severe slapback. At chunksize 512, PA path = ~18ms — below 25ms perception threshold.

**Impact:** Live mode doubles CamillaDSP CPU cost. Offset by Reaper being lighter than Mixxx.

## D-003: 16,384-tap FIR filters at 48kHz (2026-03-08)

**Context:** FIR filter length determines the lowest frequency that can be effectively corrected.

**Decision:** 16,384 taps at 48kHz (341ms, 2.9Hz frequency resolution). Fallback: 8,192 taps if CPU budget is too tight.

**Rationale:** At 48kHz, 16,384 taps gives 10.2 cycles at 30Hz (solid), 6.8 cycles at 20Hz (adequate with headroom). 8,192 taps gives 3.4 cycles at 20Hz (marginal but viable for live venues).

**Impact:** CPU cost scales with tap count. Must validate on Pi 4B hardware (test T1).

## D-004: Two independent subwoofers with per-sub correction (2026-03-08)

**Context:** Different sub placement = different room interaction. A single correction filter cannot serve both.

**Decision:** Each subwoofer gets its own FIR correction filter, delay value, and gain trim. Both receive the same L+R mono sum as source material.

**Rationale:** Subs near walls/corners have strong room coupling that varies dramatically with position. Each sub needs independent measurement and correction.

**Impact:** Four combined FIR filters total (left HP, right HP, sub1 LP, sub2 LP). Four delay values. Measurement pipeline must measure each output independently.

## D-005: Team composition — Live Audio Engineer and Technical Writer on core team (2026-03-08)

**Context:** This is an audio engineering project where signal processing decisions are central, and comprehensive documentation is a primary deliverable.

**Decision:** Add a Live Audio Engineer as a core advisory team member. Promote the Technical Writer from worker to core team member. No Security Specialist (personal project, no secrets or auth).

**Rationale:** Audio Engineer ensures every technical decision serves the goal of a successful live event. Keeps track of signal processing requirements and is part of the approval process. Technical Writer maintains a comprehensive documentation suite (introduction, how-tos, handbook, theory, lab notes) and records experiment results during testing.

**Impact:** Both roles have blocking authority. Audio Engineer blocks on signal processing errors. Technical Writer blocks on documentation inaccuracy that could cause incorrect configuration.

## D-006: Expanded team — Security Specialist, UX Specialist, Product Owner; Architect gets real-time performance scope (2026-03-08)

**Context:** Supersedes D-005's "No Security Specialist" clause. The system is a headless Pi on venue WiFi networks with exposed services — reputation risk is real even without nation-state threats. Headless operation across multiple MIDI controllers needs dedicated interaction design. Story intake from owner inputs needs a dedicated Product Owner role.

**Decision:**
1. Add Security Specialist to core team, scoped to availability/integrity for live performance (not full enterprise security). Threat model: casual attackers at venue networks, service exposure, reputation protection.
2. Add UI/UX Specialist to core team, responsible for interaction design across MIDI controllers, headless operations, displays, web UIs, and remote access.
3. Add Product Owner to core team (Coordination category), responsible for translating owner inputs into structured stories with acceptance criteria.
4. Expand Architect's scope to include real-time performance on constrained hardware (CPU budgets, memory management, thermal planning, buffer sizing, systemd resource management).

**Rationale:** Security: a headless Pi with SSH, VNC, CamillaDSP websocket, and possibly web UIs on untrusted venue WiFi is a real attack surface — proportionate hardening is needed. UX: the interaction model spans MIDI grids, DJ controllers, headless systemd, web UIs, VNC — designing coherent workflows needs dedicated attention. Product Owner: structured story intake prevents requirements from being lost or misinterpreted. Architect real-time scope: Pi 4B with 4GB RAM under sustained DSP load is fundamentally a real-time performance challenge.

**Impact:** Security Specialist has blocking authority on network exposure and service hardening. UX Specialist has blocking authority on interaction design that could disrupt live performance. Product Owner has no blocking authority but flags incomplete/ambiguous AC. Consultation matrix updated with all new consultation rules.

## D-007: D-001, D-002, D-003 are conditional pending hardware validation (2026-03-08)

**Context:** AD review identified that D-001 (minimum-phase FIR), D-002 (dual chunksize 2048/512), and D-003 (16,384-tap FIR) are stated as binding decisions but depend on hardware validation tests (T1-T5) that have not yet been run on the Pi 4B.

**Decision:** D-001, D-002, and D-003 remain the design intent and working assumptions for all planning and story writing. However, they are explicitly conditional on US-001 (CPU benchmarks), US-002 (latency measurement), and US-003 (stability tests) passing. If any test fails, the affected decision will be revisited with a new superseding decision (e.g., D-003 may be superseded by a decision to use 8,192 taps if T1b fails).

**Rationale:** The decision tree in CLAUDE.md already documents fallback paths (8,192 taps, chunksize 1024, etc.). This decision formalizes that the current parameters are not yet validated on hardware and may change based on test results.

**Impact:** No change to current story AC or planning. All stories should continue to reference D-001/D-002/D-003 as the target configuration. The test stories (US-001, US-002, US-003) include decision tree outcomes in their DoD — if a fallback is triggered, a new decision entry will be added.
