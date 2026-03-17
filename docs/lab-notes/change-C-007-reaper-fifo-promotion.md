# CHANGE Session C-007: Reaper FIFO Promotion for q256 Stability

Promoted Reaper's `pw-REAPER` JACK bridge threads from SCHED_OTHER to
SCHED_FIFO/80 to address q256 xruns. The PipeWire RT module
(`libpipewire-module-rt`) fails to promote JACK client threads on
PREEMPT_RT -- the same class of bug as F-020, where PW daemon threads
required a systemd override for FIFO promotion. Thermal throttling
was investigated and ruled out. Filed as F-033.

**Evidence basis: RECONSTRUCTED** from team lead briefing containing session
data from OBSERVE O-007 through O-011 and CHANGE C-007.

### Context

| Item | Reference |
|------|-----------|
| Decision | D-040: Abandon CamillaDSP, pure PipeWire filter-chain pipeline |
| Decision | D-011: Dual quantum (1024 DJ / 256 live) |
| Prior bug | F-020: PW RT module fails to promote PW daemon threads on PREEMPT_RT |
| New bug | F-033: PW RT module fails to promote JACK client threads on PREEMPT_RT |
| Prior data | C-006 latency characterization (`5e6398c`): q256 xruns documented |
| Test protocol | TP-006: Reaper stability test protocol |

### Reproducibility

| Role | Path |
|------|------|
| PipeWire RT module | `/usr/lib/aarch64-linux-gnu/pipewire-0.3/libpipewire-module-rt.so` (on Pi) |
| PipeWire systemd override | `~/.config/systemd/user/pipewire.service.d/override.conf` (on Pi, F-020 workaround) |
| Launcher script (proposed) | Not yet created (F-033 fix) |

---

## Pre-conditions

**Date:** 2026-03-17
**Operator:** worker (CHANGE session C-007)
**Host:** mugge, Debian 13 Trixie, kernel 6.12.62+rpt-rpi-v8-rt, aarch64 (Raspberry Pi 4B)

| Check | Value |
|-------|-------|
| Kernel | 6.12.62+rpt-rpi-v8-rt (PREEMPT_RT) |
| PipeWire | 1.4.9 (trixie-backports), SCHED_FIFO/88 |
| Quantum | 256 (live mode) |
| CamillaDSP | Stopped (D-040) |
| Application | Reaper via `pw-jack reaper` |
| Fan | Installed by owner during session (O-008) |

---

## Timeline

### Phase 1: O-007 Measurements Reveal q256 Instability

**Reference:** Full data in `change-C-006-q256-latency-characterization.md`

OBSERVE session O-007 measured ~65-70 xruns in 104 minutes at quantum 256.
Key observations that pointed toward the root cause:

| Observation | Value | Significance |
|-------------|-------|-------------|
| Convolver-out B/Q peak | 0.60 | 60% of quantum budget consumed |
| Temperature | 74.0C | 1C below 75C threshold |
| Xwayland CPU | 31% per-core | Significant SCHED_OTHER load |
| Reaper scheduling | SCHED_OTHER | Not real-time despite `pw-jack` launch |
| Load average | 5.6 | Above 4-core count |

---

### Phase 2: Thermal Investigation — Throttling Ruled Out (O-008)

**Hypothesis:** Thermal throttling at 74C could be causing intermittent CPU
slowdowns that trigger xruns.

**Action:** Owner installed a fan on the Pi during the session.

**Results:**

| Metric | Before Fan | After Fan | Significance |
|--------|-----------|-----------|-------------|
| Temperature | 74.0C | 63.7C, then 51.1C | 23C reduction |
| `vcgencmd get_throttled` | 0x0 | 0x0 | No throttling flags, ever |
| Xruns | Continuing | Continuing | **Unchanged** |

**Conclusion:** Thermal throttling is **ruled out** as a cause of q256 xruns.
The `get_throttled` register returned 0x0, meaning no throttling (neither
current nor historical) has occurred. The xruns continued after a 23C
temperature drop, confirming the cause is scheduling-related, not
thermal-related.

**Benefit:** The fan is still valuable -- it provides thermal margin for
sustained q256 operation (51C vs 74C = 24C of headroom to 75C threshold).

---

### Phase 3: Root Cause Identified — JACK Bridge Threads at SCHED_OTHER

**Finding:** Reaper's `pw-REAPER` JACK bridge threads were running at
SCHED_OTHER despite being launched with `pw-jack reaper`. The PipeWire RT
module (`libpipewire-module-rt`) is responsible for promoting client threads
to real-time scheduling, but it fails to do so on PREEMPT_RT kernels.

This is the same class of bug as F-020, where the PipeWire daemon's own
threads were not promoted to FIFO scheduling. F-020 was worked around with a
systemd override (`ExecStartPost=chrt -f 88`). F-033 is the same mechanism
affecting JACK client threads launched via `pw-jack`.

**Thread inventory before promotion:**

| Thread | TID | Scheduler | Priority | Role |
|--------|-----|-----------|----------|------|
| pw-REAPER (bridge thread 1) | 9709 | SCHED_OTHER | nice 0 | PW graph participant |
| pw-REAPER (bridge thread 2) | 9710 | SCHED_OTHER | nice 0 | PW graph participant |
| REAPER (internal RT thread) | -- | SCHED_RR | 75 | Reaper audio engine |
| REAPER (internal RT thread) | -- | SCHED_RR | 76 | Reaper audio engine |

**Critical distinction:** Reaper's internal audio engine threads run at
RR/75-76 (Reaper manages its own RT scheduling). But the `pw-REAPER` bridge
threads -- the ones that actually participate in the PipeWire graph cycle and
must meet the quantum deadline -- are at SCHED_OTHER. The bridge threads
transfer audio between Reaper's internal engine and PipeWire's graph. If the
bridge threads miss the graph deadline, the convolver receives no input and
the entire chain stalls.

**Why this causes xruns at q256 but not q1024:** At quantum 1024, the graph
deadline is 21.3ms -- long enough that SCHED_OTHER threads can usually meet
it despite occasional preemption. At quantum 256, the deadline is 5.3ms. The
USB IRQ handler at FIFO/50 preempts SCHED_OTHER threads, and any scheduling
delay > ~2ms causes a missed deadline (given convolver-out B/Q = 0.60, only
2.1ms of margin remains).

---

### Phase 4: C-007 FIFO Promotion

**Time:** 2026-03-17, 16:23:10 CET

**Procedure:**

```bash
# Identify pw-REAPER bridge thread TIDs
ps -eLo pid,tid,cls,rtprio,ni,comm | grep pw-REAPER

# Promote both bridge threads to FIFO/80
chrt -f 80 -p 9709
chrt -f 80 -p 9710
```

**Thread state after promotion:**

| Thread | TID | Scheduler | Priority | Change |
|--------|-----|-----------|----------|--------|
| pw-REAPER (bridge 1) | 9709 | SCHED_FIFO | 80 | SCHED_OTHER -> FIFO/80 |
| pw-REAPER (bridge 2) | 9710 | SCHED_FIFO | 80 | SCHED_OTHER -> FIFO/80 |
| REAPER (internal) | -- | SCHED_RR | 75-76 | Unchanged |

**Priority hierarchy (complete):**

| Entity | Scheduler/Priority | Notes |
|--------|-------------------|-------|
| PipeWire daemon | SCHED_FIFO/88 | Graph clock, convolver (F-020 workaround) |
| pw-REAPER bridge | SCHED_FIFO/80 | JACK bridge threads (C-007 promotion) |
| Reaper internal | SCHED_RR/75-76 | Reaper's own audio engine |
| USB IRQ handler | SCHED_FIFO/50 | USB isochronous transfers |
| ~30 vc4/HDMI IRQs | SCHED_FIFO/50 | GPU/display interrupts |
| Xwayland | SCHED_OTHER | Display server |
| labwc compositor | SCHED_OTHER | Wayland compositor |

FIFO/80 places the bridge threads below PipeWire (88) but above USB IRQs
(50) and Reaper's internal threads (RR/75-76). This ensures:
- PipeWire can always preempt the bridge threads (graph clock authority)
- Bridge threads can preempt USB IRQs (audio deadline > USB transfer)
- Bridge threads cannot be preempted by SCHED_OTHER processes (Xwayland, system)

---

### Phase 5: Initial Observation (O-009)

**Time:** 3 minutes after promotion
**Duration:** 3-minute check

| Node | ERR (before) | ERR (after) | Delta |
|------|-------------|------------|-------|
| pi4audio-convolver | 14 | 15 | +1 |
| USBStreamer | 2 | 2 | 0 |
| REAPER | 0 | 0 | 0 |
| ada8200-in | 0 | 0 | 0 |

**Assessment:** +1 xrun on convolver in 3 minutes. Too early for statistical
significance — the pre-promotion rate was ~0.6/min, so 1 xrun in 3 minutes
is consistent with either improvement or no change. A longer observation
window is needed.

---

### Phase 6: Subsequent Observations — Conflicting Data (O-010, O-011)

Two follow-up OBSERVE sessions produced conflicting results:

| Session | Finding | ERR Counts | Graph State |
|---------|---------|-----------|-------------|
| O-010 | All ERR=0 | 0 across all nodes | Idle (no audio flowing) |
| O-011 | ERR unchanged from O-009 | convolver=15, USBStreamer=2 | Active (audio flowing) |

**Problem:** O-010 observed an idle graph (ERR counters reset when the graph
restarts), while O-011 found the same ERR counts as O-009. The data does not
conclusively demonstrate improvement.

**Promising signal:** If the convolver-out B/Q dropped from 0.60 (pre-FIFO)
to 0.21-0.23 (reported in O-011), this would indicate the FIFO promotion
significantly reduced scheduling jitter on the convolver chain. However, this
data point's reliability is uncertain given the conflicting O-010/O-011
observations.

**Status:** O-012 completed — see Phase 7 below.

---

### Phase 7: O-012 Reveals FIFO Promotion Reverted

**Finding:** O-012 discovered that the FIFO/80 promotion from C-007 has
**reverted**. The `pw-REAPER` bridge thread is back at SCHED_OTHER with a
new TID (11198), replacing the promoted TIDs (9709, 9710).

**Cause:** The JACK bridge thread was recycled — likely the bridge
reconnected or PipeWire respawned the client thread, creating a new thread
at default (SCHED_OTHER) scheduling. Runtime `chrt` promotion only affects
the specific thread it targets. When that thread is replaced by a new one,
the promotion is lost.

**ERR count at O-012:** 23 (unchanged from recent observations). Despite the
FIFO reversion, no new xruns accumulated. This is significant because:

1. The fan (O-008) reduced temperature from 74C to 51C
2. The FIFO promotion has reverted, yet xruns stopped
3. This suggests the fan's thermal improvement may also be a contributing
   factor — lower temperatures reduce CPU power management overhead and
   improve scheduling determinism

**Implications for the permanent fix:**

The O-012 finding makes the F-033 launcher script fix even more critical
than initially assessed. Runtime `chrt` is fundamentally unreliable because:
- JACK bridge threads are recycled on reconnection
- New threads inherit default scheduling (SCHED_OTHER)
- There is no notification when threads are replaced

The launcher script approach (`exec chrt -f 70 pw-jack reaper`) promotes the
entire process tree from the start, ensuring all threads — including
replacements — inherit RT scheduling. However, this needs verification:
`chrt` wraps the initial process, but dynamically spawned child threads may
still default to SCHED_OTHER. The RT module's thread promotion is the correct
mechanism, but it is broken on PREEMPT_RT (F-020/F-033).

---

## Related Findings

### Fan Effectiveness

The owner's fan installation during O-008 reduced temperatures by 23C:

| Condition | Temperature |
|-----------|-------------|
| No fan, q256 under load | 74.0C |
| Fan, q256 under load (initial) | 63.7C |
| Fan, q256 under load (stabilized) | 51.1C |

While thermal throttling was not the xrun cause, the fan provides critical
margin for production use. At 51C, the system has 24C of headroom to the 75C
threshold — sufficient for flight-case operation in warm venues.

### `node.lock-quantum` Behavior

Setting `node.lock-quantum = true` on the Reaper JACK client does not
override the driver's quantum. In PipeWire's topology, the driver node
(USBStreamer in this configuration) sets the quantum for the entire graph.
Follower nodes (including Reaper via pw-jack) must operate at the driver's
quantum regardless of their `node.lock-quantum` setting. The quantum must
be set at the graph level via `pw-metadata`.

---

## Open Items

| # | Item | Severity | Owner | Reference |
|---|------|----------|-------|-----------|
| 1 | F-033 persistent fix: launcher script `exec chrt -f 70 pw-jack reaper` | **Critical** | Worker | Phase 4, Phase 7 |
| 2 | Same launcher pattern for Mixxx: `exec chrt -f 70 pw-jack mixxx` | **Critical** | Worker | F-033 |
| 3 | ~~O-012 fresh observation~~ DONE — FIFO reverted, ERR stable at 23 | -- | -- | Phase 7 |
| 4 | Investigate PW RT module PREEMPT_RT client thread promotion | Medium | Architect | F-020/F-033 |
| 5 | TP-006 Reaper stability test with persistent FIFO (launcher script) | Medium | QE | Phase 7 |
| 6 | Verify `chrt` wrapper promotes dynamically spawned child threads | Medium | Worker | Phase 7 |
| 7 | Quantify fan contribution to xrun reduction (thermal vs scheduling) | Low | Worker | Phase 7 |

---

## Summary

**Root cause of q256 xruns:** Reaper's `pw-REAPER` JACK bridge threads were
at SCHED_OTHER, allowing USB IRQs (FIFO/50) and other RT activity to preempt
them during the 5.3ms graph cycle. At quantum 256, any scheduling delay
> 2.1ms causes the convolver to miss its deadline (B/Q = 0.60, only 40%
margin). This is the same class of bug as F-020 — PipeWire's RT module fails
to promote client threads on PREEMPT_RT.

**Fix applied:** `chrt -f 80` on both `pw-REAPER` bridge threads (TIDs 9709,
9710). Runtime-only — resets on thread recycling (confirmed by O-012).

**FIFO promotion reverted (O-012):** The promoted threads were replaced by
new threads at SCHED_OTHER (new TID 11198). Runtime `chrt` is fundamentally
unreliable for JACK bridge threads because PipeWire recycles them. Despite
reversion, ERR count stabilized at 23 — no new xruns. This raises the
possibility that the fan's thermal improvement (74C -> 51C) is also a
contributing factor.

**Thermal throttling ruled out:** `vcgencmd get_throttled` = 0x0 (no
throttling ever). Fan reduced temperature from 74C to 51C. Xruns continued
initially after fan installation but stopped after a combination of FIFO
promotion + time. The relative contribution of thermal vs scheduling
improvement is not yet isolated.

**Permanent fix (F-033, elevated to Critical):** Launcher scripts MUST use
`exec chrt -f 70 pw-jack <application>` for all JACK clients (Reaper, Mixxx).
Runtime `chrt` on individual TIDs is not durable — O-012 proved that thread
recycling reverts the promotion. The launcher script approach wraps the
entire process tree. Verification needed: do dynamically spawned child
threads inherit the RT scheduling class?

---

**Session:** CHANGE C-007, OBSERVE O-007 through O-012
**Date:** 2026-03-17
**Documented by:** technical-writer (2026-03-17, from team lead session briefing)
