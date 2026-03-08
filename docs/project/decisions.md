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
