# TP-006: Reaper Live-Mode Stability Test (US-059 DoD #8)

## Part 1: Test Protocol

### 1.1 Identification

| Field | Value |
|-------|-------|
| Protocol ID | TP-006 |
| Title | 30-minute Reaper live-mode stability test on PW filter-chain |
| Parent story | US-059 AC: "30-minute Reaper stability test" |
| DoD item | DoD #8 (Reaper half): "30-minute stability tests PASS (Mixxx + Reaper, separately)" |
| Author | Quality Engineer |
| Reviewer | Audio Engineer (domain), Architect (topology) |
| Status | Draft |

### 1.2 Test Objective

**Type:** Stability soak test.

**Hypothesis:** The Reaper live-mode audio path (22 PW links: 4ch playback
through filter-chain convolver, headphone bypass, singer IEM bypass, 8ch
ADA8200 capture, all managed by GraphManager) runs for 30 continuous minutes
at production quantum (256) with zero xruns and no spurious disconnections.

**Context:** GM-12 validated DJ stability (Mixxx, 40+ min + 11-hour overnight
soak, zero xruns). C-005 validated the Reaper 22-link topology at quantum 1024
with 0 ERR on both USBStreamer and ADA8200 devices. This test extends that to
the production live-mode quantum (256) and formal 30-minute duration per US-059
AC.

**What this test covers:**
- Reaper audio path stability at production quantum (256)
- Full 22-link topology integrity over 30 minutes
- ADA8200 capture path stability (8ch simultaneous in + out)
- Thermal behavior under sustained Reaper + convolver + capture load
- Spectral verification that convolver is actively processing (crossover rolloff)

**What this test does NOT cover:**
- GraphManager automated routing (links are created manually with `pw-link` per
  current state -- reconciler bugs block automated routing)
- Mode transition testing (separate test, DoD #7)
- Latency measurement (separate test, DoD #9)

### 1.3 System Under Test

| Component | Required state | How achieved |
|-----------|---------------|--------------|
| Git commit | TBD (record at execution) | Deployed via CM session |
| Kernel | `6.12.62+rpt-rpi-v8-rt` (PREEMPT_RT) | Pre-flight: `uname -r` |
| PipeWire | 1.4.9 (trixie-backports), SCHED_FIFO/88 | Pre-flight: `pipewire --version`, `chrt -p $(pidof pipewire)` |
| Production quantum | 256 | `pw-metadata -n settings 0 clock.force-quantum 256` |
| Filter-chain convolver | 4x 16k-tap FIR (production WAV files) | `30-filter-chain-convolver.conf` loaded |
| Reaper | Running via `pw-jack reaper` with a test project | Manually launched, 8ch output configured |
| USBStreamer | Connected, `node.group = pi4audio.usbstreamer` | Pre-flight: `aplay -l`, verify config |
| ADA8200 capture | Connected, `node.group = pi4audio.usbstreamer` | Pre-flight: `22-ada8200-in.conf` loaded |
| CamillaDSP | Stopped | Pre-flight: `systemctl is-active camilladsp` |
| Convolver volume | -30 dB workaround applied | `pw-cli s <node-id> Props '{ volume: 0.0316 }'` on convolver capture node |
| PA system | OFF (headphone monitoring only) | Safety: no powered speakers |
| WirePlumber | Running (current state -- not yet removed) | Note: WP may create duplicate links. Record WP state. |

**Reaper test project requirements:**
- 8 output channels configured matching live-mode routing table
- Ch 1-2: Master L/R (PA stereo with backing tracks playing)
- Ch 5-6: Headphone L/R
- Ch 7-8: Singer IEM L/R
- At least one backing track playing continuously for the full 30 minutes
- At least one input armed for capture (ADA8200 ch 1: vocal mic)

### 1.4 Controlled Variables

| Variable | Controlled value | Control mechanism | Drift response |
|----------|-----------------|-------------------|----------------|
| Kernel | `6.12.62+rpt-rpi-v8-rt` | Pre-flight: `uname -r` | ABORT |
| PipeWire scheduling | SCHED_FIFO/88 | Pre-flight: `chrt -p $(pidof pipewire)` | ABORT |
| Quantum | 256 | Pre-flight: `pw-metadata -n settings` | ABORT |
| CamillaDSP | Stopped | Pre-flight: `systemctl is-active camilladsp` | ABORT |
| Link count | 22 | Verified after manual link creation with `pw-link -l \| wc -l` | ABORT if < 22 required links |
| Convolver volume | -30 dB (0.0316) | Applied before test, verified with `pw-cli e <node-id> Props` | Note and continue if different; record actual volume |
| Thermal start | < 60C | Pre-flight: CPU temp check | Wait until < 60C |

### 1.5 Pass/Fail Criteria

| # | Criterion | Measurement method | Pass | Fail | Source |
|---|-----------|-------------------|------|------|--------|
| R-1 | Zero xruns for 30 minutes | `pw-top -b` xrun field + PW journal | 0 xruns | Any xrun | US-059 AC: "zero xruns" |
| R-2 | No spurious disconnections | `pw-link -l` count at start and end + PW journal for link remove events | Link count stable (22 required) | Any required link lost during test | US-059 AC: "no spurious disconnections" |
| R-3 | Correct graph topology | `pw-link -l` output matches Live mode routing table (22 links) | All 22 links present and correct | Missing links, wrong endpoint | US-059 AC: "correct graph topology" |
| R-4 | Spectral verification — crossover rolloff | pcm-bridge or `pw-top` spectral analysis of convolver output: mains should show highpass rolloff below ~80Hz, subs should show lowpass rolloff above ~80Hz | Crossover rolloff visible in at least one measurement during the 30 min | No rolloff visible (convolver passthrough or not processing) | US-059 AC: "spectral analysis confirms filter-chain actively processing" |
| R-5 | Channel separation | Verify mains (ch 1-2) do not contain sub-only content and subs (ch 3-4) do not contain full-range content | Distinct spectral profile per channel group | Mains and subs have identical spectrum (no crossover active) | US-059 AC: "correct channel separation between mains and subs" |
| R-6 | CPU within thermal budget | Max CPU temperature during 30 min | < 80C | > 85C | Thermal safety (A4 threshold). 80-85C = MARGINAL. |
| R-7 | Capture path active | ADA8200 ch 1 (vocal mic) shows non-zero input in Reaper meters when mic receives signal | Signal visible in Reaper input meters | No input signal despite mic present | Live mode requires capture path functional |
| R-8 | IEM bypass path active | USBStreamer ch 7-8 carry Reaper output ch 7-8 signal | Signal measurable on USBStreamer ch 7-8 (or verified via test tone in Reaper) | No signal on IEM channels | IEM is optional equipment but the path must work when connected |

### 1.6 Execution Procedure

#### Phase 0: Pre-flight (10 minutes)

```
Step 0.1: Record system state
    Command: uname -r && pipewire --version && date -Iseconds
    Expected: 6.12.62+rpt-rpi-v8-rt, PipeWire 1.4.9

Step 0.2: Verify PipeWire scheduling
    Command: chrt -p $(pidof pipewire)
    Expected: SCHED_FIFO, priority 88

Step 0.3: Verify CamillaDSP stopped
    Command: systemctl is-active camilladsp
    Expected: "inactive"

Step 0.4: Set quantum to 256
    Command: pw-metadata -n settings 0 clock.force-quantum 256
    Verify:  pw-metadata -n settings | grep clock.quantum
    Expected: "256"

Step 0.5: Verify thermal state
    Command: awk '{print $1/1000}' /sys/class/thermal/thermal_zone0/temp
    Expected: < 60.0

Step 0.6: Verify USBStreamer and ADA8200 connected
    Command: aplay -l | grep USBStreamer && pw-cli list-objects Node | grep ada8200
    Expected: Both devices listed

Step 0.7: Apply convolver volume workaround
    Command: pw-cli s <convolver-capture-node-id> Props '{ volume: 0.0316 }'
    SAFETY: Confirm PA is OFF before this step.
    NOTE: Do NOT increase volume beyond -30 dB without owner confirmation (S-012).

Step 0.8: Record WirePlumber state
    Command: systemctl --user is-active wireplumber
    Note: Record whether WP is running. If running, note that it may create
    duplicate links (TK-240).
```

#### Phase 1: Reaper setup and link creation (10 minutes)

```
Step 1.1: Launch Reaper
    Command: pw-jack reaper <test-project-path> &
    Expected: Reaper starts, 8 output channels visible

Step 1.2: Wait for Reaper PW node registration (10s)
    Command: pw-cli list-objects Node | grep REAPER
    Expected: REAPER node appears with correct port count

Step 1.3: Create all 22 live-mode links manually
    Use pw-link to create each link per the live-mode routing table:
    - Reaper out1,out2 → convolver playback_AUX0,AUX1 (mains, 2 links)
    - Reaper out1,out2 → convolver playback_AUX2 (sub1 mono sum, 2 links)
    - Reaper out1,out2 → convolver playback_AUX3 (sub2 mono sum, 2 links)
    - convolver output_AUX0..3 → USBStreamer playback_AUX0..3 (4 links)
    - Reaper out5,out6 → USBStreamer playback_AUX4,AUX5 (HP, 2 links)
    - Reaper out7,out8 → USBStreamer playback_AUX6,AUX7 (IEM, 2 links)
    - ada8200-in capture_AUX0..7 → Reaper in1..in8 (capture, 8 links)

Step 1.4: Verify link count
    Command: pw-link -l | grep -c '^\s'  (or equivalent count method)
    Expected: >= 22 (our links; may include PW-internal links)
    Record: Exact link count and full pw-link -l output.

Step 1.5: Start backing track playback in Reaper
    Action: Press play on a backing track that runs >= 30 minutes
    Verify: Audio audible in headphones (ch 5-6)

Step 1.6: Record baseline state
    Command: pw-top -b -n 1
    Record: CPU%, ERR count, node list
```

#### Phase 2: Stability soak (30 minutes)

```
Step 2.1: Record start time
    Command: date -Iseconds

Step 2.2: Start monitoring script
    The monitoring script (or manual checks) must sample every 60 seconds:
    - pw-top -b -n 1 (CPU%, ERR count per node)
    - awk '{print $1/1000}' /sys/class/thermal/thermal_zone0/temp
    - pw-link -l | wc -l (link count — detect disconnections)

Step 2.3: Run for 30 minutes uninterrupted
    Do NOT interact with the system during this period except for
    monitoring samples (step 2.2). No tab switching, no web UI, no SSH
    commands other than monitoring.

Step 2.4: Spectral verification (at ~15 minute mark)
    Method: Use pcm-bridge capture or web UI spectrum view to check:
    - Mains (ch 1-2): highpass rolloff visible below ~80Hz
    - Subs (ch 3-4): lowpass rolloff visible above ~80Hz
    Record: Screenshot or spectral data snapshot

Step 2.5: Capture path verification (at ~20 minute mark)
    Method: Tap or speak into the vocal mic (ADA8200 ch 1)
    Verify: Signal appears in Reaper input meter for ch 1
    Record: Screenshot or note

Step 2.6: Record end time
    Command: date -Iseconds

Step 2.7: Record final state
    Command: pw-top -b -n 1
    Command: pw-link -l
    Command: journalctl --user -u pipewire --since "<start-time>" --no-pager
    Record: Final CPU%, ERR count, link count, any PW warnings
```

#### Phase 3: Teardown (5 minutes)

```
Step 3.1: Stop Reaper
    Action: Close Reaper (do not kill -9)
    Verify: REAPER node disappears from pw-cli list-objects

Step 3.2: Remove manual links (if any persist)
    Command: pw-link -d <links> (if cleanup needed)

Step 3.3: Restore system
    If quantum was changed, restore production default.
```

### 1.7 Evidence Capture

| Evidence | Format | Location |
|----------|--------|----------|
| Pre-flight system state | Text | Inline in execution record |
| Full pw-link -l output (start) | Text | `data/US-059/reaper-stability-links-start.txt` |
| Full pw-link -l output (end) | Text | `data/US-059/reaper-stability-links-end.txt` |
| Monitoring samples (30x @60s) | JSON or text | `data/US-059/reaper-stability-samples.json` |
| Spectral screenshot/data | Image or JSON | `data/US-059/reaper-spectral-verify.png` |
| PipeWire journal (test window) | Text | `data/US-059/reaper-stability-journal.txt` |
| pw-top final snapshot | Text | Inline in execution record |

### 1.8 Relationship to C-005

C-005 (CHANGE session, 2026-03-17) demonstrated:
- 22-link topology validated at quantum 1024
- 0 ERR on both USBStreamer and ADA8200 with `node.group` fix
- Compositor smooth under full topology

**C-005 data does NOT count as the DoD #8 Reaper stability test because:**
1. C-005 was at quantum 1024, not the production quantum 256. The US-059 AC
   requires "production quantum" which is 256 for live mode.
2. C-005 did not run for a formal 30-minute continuous period with monitoring
   samples. The lab note records topology validation, not a timed soak.
3. C-005 did not include spectral verification of convolver active processing.
4. C-005 had a safety incident (S-012) that disrupted the session flow.

**However, C-005 data is valuable context:**
- Confirms the 22-link topology works and is stable at quantum 1024.
- Confirms the `node.group` fix resolves compositor starvation.
- Confirms Reaper's PW node name is "REAPER" (prefix match) and port names
  are `out1..out8`, `in1..in8`.
- These findings de-risk this protocol. The primary question is whether
  quantum 256 (higher scheduling pressure) introduces xruns under sustained load.

### 1.9 Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| WirePlumber creates duplicate links | High (TK-240) | False link count, possible audio routing confusion | Record WP state. Document duplicate links separately. Count only our 22 links. |
| Quantum 256 causes xruns due to higher RT pressure | Medium | Test FAIL | Compare xrun pattern with GM-12 (which ran at quantum 1024). If xruns are scheduling-related (not convolver), document and assess whether quantum 512 is an acceptable compromise. |
| Reaper test project not available | Medium | Cannot execute | Operator must prepare a Reaper project with 8ch output + backing track before the test session. |
| Thermal throttling at quantum 256 (higher CPU) | Low | CPU measurement invalid | Monitor temperature continuously. If > 85C, note and stop early. |
| `pw-top` monitoring adds CPU overhead | Low | Slightly inflated CPU readings | Accept small overhead. pw-top at 1/60s sampling is negligible. |

### 1.10 Approval

| Role | Name | Date | Verdict |
|------|------|------|---------|
| QE (author) | quality-engineer | 2026-03-17 | Draft |
| Audio Engineer | | | Required — validates spectral verification method, capture path test |
| Architect | | | Required — validates topology, quantum 256 rationale |

---

## Part 2: Test Execution Record

*To be completed during execution.*

### 2.1 Execution Metadata

| Field | Value |
|-------|-------|
| Protocol ID | TP-006 |
| Execution date | |
| Operator | |
| Git commit | |
| CM session ID | |

### 2.2 Pre-flight Verification

| Component | Expected | Observed | Pass/Fail |
|-----------|----------|----------|-----------|
| Kernel | `6.12.62+rpt-rpi-v8-rt` | | |
| PipeWire | 1.4.9, SCHED_FIFO/88 | | |
| Quantum | 256 | | |
| CamillaDSP | inactive | | |
| Starting temperature | < 60C | | |
| USBStreamer | connected | | |
| ADA8200 | connected | | |
| WirePlumber | (record state) | | |
| Link count after setup | 22 | | |

### 2.3 Monitoring Samples

| Time (min) | CPU% (PW) | CPU% (Reaper) | Temp (C) | Link count | ERR (USB) | ERR (ADA) | Notes |
|-----------|-----------|---------------|----------|------------|-----------|-----------|-------|
| 0 | | | | | | | Baseline |
| 1 | | | | | | | |
| 2 | | | | | | | |
| ... | | | | | | | |
| 30 | | | | | | | Final |

### 2.4 Results

| # | Criterion | Measured Value | Result | Evidence |
|---|-----------|---------------|--------|----------|
| R-1 | Xruns (30 min) | | | |
| R-2 | Link stability | | | |
| R-3 | Topology correct | | | |
| R-4 | Spectral — crossover | | | |
| R-5 | Channel separation | | | |
| R-6 | Thermal | | | |
| R-7 | Capture path | | | |
| R-8 | IEM bypass path | | | |

### 2.5 Outcome

**Reaper 30-minute stability:** PASS / FAIL
**Combined with GM-12 DJ result:** Both halves of DoD #8: PASS / FAIL

### 2.6 Sign-off

| Role | Name | Date | Verdict |
|------|------|------|---------|
| QE | | | |
| AE | | | |
