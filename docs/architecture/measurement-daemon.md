# Measurement Daemon Architecture (D-036)

**Status:** Architecture stable, implementation in progress
**Decision:** D-036 — Central daemon replaces subprocess model
**Supersedes:** `measurement-workflow-ux.md` Section 10 (subprocess backend)
**Dependencies:** D-035 (measurement safety), US-047 (Path A measurement),
US-048 (post-measurement viz), US-049 (real-time websocket feed)
**D-040 update:** Section 3 documents the post-D-040 RPC client architecture
(GraphManager + signal-gen). CamillaDSP references in Sections 1-2 are
historical context explaining the original subprocess model that was replaced.

---

## 1. Overview

The measurement workflow has been redesigned from a subprocess model to a
central daemon model. The FastAPI web UI backend IS the measurement
controller -- it is not a thin proxy spawning an external measurement
script.

### Why the Change

The original architecture (documented in `measurement-workflow-ux.md`
Section 10) had the FastAPI backend spawn `measure_nearfield.py` as a
subprocess, proxying its websocket feed to the browser. This created
problems:

- **Two processes competing for system resources:** The measurement script
  and the web UI backend both needed DSP engine access, PipeWire state,
  and audio device handles. Coordinating ownership across process
  boundaries was fragile.
- **Abort coordination:** Sending abort signals across a process boundary
  (signal/websocket hybrid) had unclear semantics for partial completion
  and state restoration.
- **State synchronization:** The FastAPI backend had to reconstruct the
  subprocess's internal state for browser reconnection, duplicating the
  state machine.

### The Daemon Model

The FastAPI backend manages all system state directly:

- GraphManager RPC client for mode switching and routing topology (D-040, US-061)
- Signal generator RPC client for measurement audio playback/capture
- PipeWire quantum and device state
- Measurement session state machine
- Safety enforcement (thermal ceiling, hard cap, HPF verification)

The browser is a pure view layer. It renders state pushed from the daemon
via WebSocket and sends user commands (start, abort, confirm) back. The
measurement script (`measure_nearfield.py`) remains as a standalone CLI
tool for SSH-based measurement but is not used by the web UI.

```
Browser (Measure tab)                FastAPI Daemon
       |                                    |
       |-- WS: start measurement ---------->|
       |                                    |-- acquire mode lock
       |                                    |-- GM: set_mode("measurement")
       |                                    |-- signal-gen: play sweep (threaded)
       |<-- WS: state updates (5 Hz) -------|
       |<-- WS: sweep progress -------------|
       |<-- WS: per-sweep results ----------|
       |                                    |
       |-- WS: abort ---------------------->|
       |                                    |-- signal-gen: stop + GM: restore_production_mode()
       |<-- WS: session aborted ------------|
```

---

## 2. Mode Manager

The daemon operates in two mutually exclusive modes:

| Mode | Purpose | Active Subsystems |
|------|---------|-------------------|
| STANDBY | Normal dashboard operation | All collectors running, GraphManager in standby mode |
| MEASUREMENT | Measurement wizard | Collectors paused (except pcm-bridge), GraphManager in measurement mode, signal-gen active |

### Mode Transitions

```
STANDBY ──── enter_measurement() ───> MEASUREMENT
     ^                                        |
     |                                        |
     └───── exit_measurement() ──────────────-┘
```

**`enter_measurement()`:**
1. Pause non-essential collectors (system, PipeWire polling)
2. Acquire exclusive mode lock
3. Verify pre-flight conditions (see Section 7)
4. Transition UI to measurement wizard

**`exit_measurement()`:**
1. GraphManager: `restore_production_mode()` (set_mode("standby"))
2. Release mode lock
3. Resume all collectors
4. Transition UI back to dashboard

The mode lock prevents concurrent measurement sessions. If a measurement
is in progress and a second browser connects, it joins the existing
session as an observer (receives the same state updates) rather than
starting a new one.

### Collector Lifecycle

Collectors (FilterChainCollector, PipeWire status, system stats) are paused
during measurement to avoid interference. The pcm-bridge collector is the
exception -- it uses a passive PipeWire client that cannot interfere with
the audio pipeline (see Section 8).

---

## 3. RPC Client Architecture (D-040, US-061)

Post-D-040, the daemon communicates with two RPC servers instead of a
single CamillaDSP websocket connection. Both use JSON-over-TCP with
newline-delimited messages.

### GraphManager Client (`src/measurement/graph_manager_client.py`)

- **Server:** `127.0.0.1:4002` (GraphManager TCP RPC)
- **Purpose:** Mode switching and routing topology verification
- **Lifetime:** Created at measurement start, destroyed at measurement end
- **Key commands:**
  - `set_mode("measurement")`: switches to measurement routing (signal-gen
    to convolver, UMIK-1 capture active, all non-measurement links torn down)
  - `set_mode("standby")`: restores production routing
  - `get_state()`: returns `{mode, nodes[], links[], devices{}}`
  - `get_mode()`: returns current mode string
- **Safety:** `verify_measurement_mode()` confirms GM is in measurement
  mode before any audio output. Raises `GraphManagerError` if not.
- **Mock:** `MockGraphManagerClient` provides in-memory state tracking
  for tests without a running GraphManager.
- **Reconnection:** Exponential backoff (1s -> 2s -> ... -> 30s), max
  5 attempts. Raises `ConnectionError` on failure.

### Signal Generator Client (`src/measurement/signal_gen_client.py`)

- **Server:** `127.0.0.1:4001` (signal-gen TCP RPC)
- **Purpose:** Sweep playback, capture control, per-channel level setting
- **Lifetime:** Created at measurement start, destroyed at measurement end
- **Key commands:** `play`, `stop`, `set_level`, `set_signal`, `set_channel`,
  `capture_start`, `capture_stop`, `capture_read`
- **Safety:** Hard output level cap of -20 dBFS enforced at signal-gen level
  (immutable `--max-level-dbfs` CLI argument, SEC-D037-04)

### Why Separate Clients (vs Previous Two-CamillaDSP Model)

The pre-D-040 architecture used two pycamilladsp connections to avoid
contention between monitoring polls and measurement config swaps on a
single CamillaDSP websocket. Post-D-040, this contention does not exist:

- **GraphManager** handles routing (mode switching) -- no polling needed
  during measurement. The measurement session calls `set_mode()` once at
  start and once at end.
- **Signal generator** handles audio I/O -- the session sends play/stop/capture
  commands. No shared state with the FilterChainCollector.
- **FilterChainCollector** (monitoring) is paused during measurement, so
  its GM RPC polls do not interleave with the session's GM calls.

The two clients serve fundamentally different purposes (routing vs audio I/O)
and connect to different servers, so there is no contention by design.

---

## 4. Threaded Audio I/O

All audio I/O uses `sounddevice.playrec()` which blocks for the duration
of the recording. In an async FastAPI application, a blocking call on the
event loop would freeze all WebSocket broadcasts, HTTP request handling,
and abort processing.

### Solution: `asyncio.to_thread()`

```python
# Audio I/O runs in a thread pool, event loop stays responsive
recording = await asyncio.to_thread(
    sd.playrec,
    stimulus,
    samplerate=48000,
    input_mapping=[mic_channel],
    output_mapping=[output_channel],
    device=(input_device, output_device),
)
```

This keeps the event loop free for:
- WebSocket broadcasts (state updates at 5 Hz)
- Abort command reception and processing
- HTTP API requests (browser reconnection, status queries)
- Watchdog heartbeats

### Emergency Abort During Blocked Audio

If an abort command arrives while `sd.playrec()` is blocked in the thread
pool, the event loop calls `sd.stop()` from the main thread. This
interrupts the blocked `playrec()` call, which returns a truncated
recording. The measurement session then enters its cleanup path (GM
`restore_production_mode()`, release mode lock).

---

## 5. Session State Machine

The measurement session progresses through a fixed sequence of states.
Session state lives on the daemon (not in the browser), so it survives
browser disconnects, reconnects, and page refreshes.

```
IDLE ─> SETUP ─> GAIN_CAL ─> MEASURING ─> RESULTS ─> FILTER_GEN ─> DEPLOY ─> VERIFY
  ^                                                                              |
  └──────────────────────── session complete ────────────────────────────────────-┘
```

| State | Description | Operator Action |
|-------|-------------|-----------------|
| IDLE | No measurement in progress | "Start New Measurement" button |
| SETUP | Speaker/profile selection, mic check, pre-flight | Confirm configuration |
| GAIN_CAL | Automated gain calibration (Phase 1) | Monitor levels, approve |
| MEASURING | Per-channel sweeps across mic positions | Confirm mic repositioning between positions |
| RESULTS | Post-measurement summary, FR display | Review results |
| FILTER_GEN | FIR filter generation (automated) | Wait for completion |
| DEPLOY | Deploy filters to PW filter-chain | Approve deployment |
| VERIFY | Post-deployment verification sweep | Review before/after comparison |

### State Persistence

The daemon holds the full session state in memory:

- Current state in the state machine
- All per-sweep results (FR data, SNR, peak levels)
- Gain calibration results
- Generated filter paths
- Error/warning log

On browser reconnect, the daemon sends the full session snapshot. The
browser reconstructs its wizard view from this snapshot, resuming at the
correct step. No measurement data is lost on browser disconnect.

### Abort from Any State

Abort is valid from any state except IDLE. The abort path:

1. Cancel current operation (see Section 6)
2. GraphManager: `restore_production_mode()` (set_mode("standby"))
3. Transition to IDLE
4. Broadcast abort confirmation to all connected browsers

---

## 6. Cancellation Contract

The measurement session defines 7 named cancellation points where abort
is checked. Abort is processed between discrete operations, not mid-operation.
This ensures each operation either completes fully or does not start.

### Cancellation Points

| ID | Location | Between | Cleanup Required |
|----|----------|---------|------------------|
| CP-1 | Before GM mode switch | SETUP and mode switch | None (no state changed) |
| CP-2 | After mode switch, before gain cal | Mode switch and audio | GM: restore_production_mode() |
| CP-3 | Between gain cal blocks | Pink noise blocks | GM: restore_production_mode() |
| CP-4 | Before each sweep | Previous sweep and next sweep | GM: restore_production_mode() |
| CP-5 | Between sweeps (mic repositioning) | Operator confirmation wait | GM: restore_production_mode() |
| CP-6 | Before filter deployment | FILTER_GEN and DEPLOY | GM: restore_production_mode(), delete temp filters |
| CP-7 | Before verification sweep | DEPLOY and VERIFY | GM: restore_production_mode() (verification uses measurement mode) |

### Abort During Blocked Audio I/O

If `sd.playrec()` is blocked (mid-sweep or mid-calibration), the event
loop cannot reach a cancellation point. In this case:

1. `sd.stop()` is called from the event loop thread
2. `playrec()` returns immediately with a truncated recording
3. The measurement session detects the truncation and enters its cleanup
   path at the next cancellation point
4. GraphManager routing is restored to production mode

This is an emergency mechanism. Normal abort waits for the current
operation to complete (sweeps are 5-10 seconds, so the maximum wait is
bounded).

---

## 7. Safety Layers

The daemon enforces multiple independent safety layers. These supplement
the signal-gen hard cap and GraphManager measurement mode isolation
described in [`docs/operations/safety.md`](../operations/safety.md).

### 7.1 Startup Recovery Check

On daemon startup, the daemon checks whether GraphManager is in measurement
mode (orphaned from a prior crash or abort failure). If detected:

1. Log a warning with the orphaned mode
2. GraphManager: `restore_production_mode()` (set_mode("standby"))
3. Report the recovery in the dashboard status

This handles the edge case where the daemon crashes mid-measurement
(power loss, OOM kill, unhandled exception) and restarts with GraphManager
still in measurement mode. Implemented in `ModeManager.check_and_recover_gm_state()`
(see `app/main.py` lifespan startup).

### 7.2 Two-Tier Watchdog

| Tier | Timeout | Mechanism | Action |
|------|---------|-----------|--------|
| Software | 10 seconds | asyncio task checks heartbeat from audio thread | Abort measurement, restore config |
| systemd | 30 seconds | `WatchdogSec=30` in service unit | systemd kills and restarts daemon |

The software watchdog detects hung audio I/O (e.g., signal-gen capture blocks
indefinitely due to a device error). If the audio thread does not report
progress within 10 seconds, the watchdog triggers an abort.

The systemd watchdog is the last resort. If the entire daemon hangs (event
loop blocked, Python deadlock), systemd kills and restarts the process.
The startup recovery check (7.1) then detects the orphaned measurement
config and restores it.

### 7.3 Thermal Ceiling

The thermal ceiling module (WP-1) computes the maximum safe power output
for each speaker channel based on the speaker identity's thermal and
excursion limits. The measurement daemon enforces this ceiling:

- Before each sweep, the stimulus level is checked against the thermal
  ceiling for the target channel
- If the requested level would exceed the ceiling, the sweep is rejected
  with an error (not silently clamped)

### 7.4 Hard Cap

The measurement daemon enforces a hard cap of -20 dBFS on all audio output.
This is independent of GraphManager routing -- it is enforced at the
signal generator level via the immutable `--max-level-dbfs` CLI argument
(SEC-D037-04). Even if the routing topology is misconfigured, the hard cap
prevents excessive power delivery. The web UI's signal-gen proxy also
enforces D-009 (hard cap at -0.5 dBFS) on all browser-originated commands.

### 7.5 HPF Verification

Before the first sweep, the daemon verifies that GraphManager is in
measurement mode via `gm_client.verify_measurement_mode()` (GC-07/11,
D-040). In measurement mode, GraphManager establishes measurement-specific
routing: only the test channel emits signal, all other channels are silent.
This replaces the pre-D-040 CamillaDSP config swap that applied -20 dB
attenuation and per-channel HPF via filter definitions. The HPF verification
is deferred to signal-gen configuration (the signal generator does not
produce subsonic content).

---

## 8. pcm-bridge Integration

The pcm-bridge (WP-7) replaces the JACK-based PCM collector (`PcmStreamCollector`
in `web-ui.md` Section 13) with a passive PipeWire monitor tap.

### Why the Change

The original PCM collector used a JACK client to tap the audio stream.
JACK clients are active participants in the RT audio graph -- they receive
scheduling deadlines from PipeWire and must complete processing within
the quantum period. A JACK client running at SCHED_OTHER (as the web UI
does) cannot reliably meet these deadlines under CPU pressure, causing
xruns in the entire audio graph (F-030).

### The pcm-bridge Architecture

pcm-bridge is a Rust binary that:

1. Registers as a PipeWire client targeting a specific node (configured
   via env files in `configs/pcm-bridge/`)
2. Reads PCM samples into a lock-free ring buffer from the PW process
   callback (SCHED_FIFO)
3. Serves framed binary PCM over TCP to web UI clients
4. Computes lock-free per-channel peak/RMS levels via atomic operations
   (US060-3) and broadcasts JSON at 10 Hz to level metering clients

Because the monitor tap is passive, pcm-bridge:

- **Cannot cause xruns.** It is not in the scheduling graph. If it falls
  behind, it simply drops samples -- the audio pipeline is unaffected.
- **Can run during measurement.** Unlike the JACK collector, pcm-bridge
  does not interfere with the measurement audio path.
- **Uses minimal CPU.** Estimated ~1% CPU for level computation at 48kHz
  8-channel.

### Integration with Mode Manager

In STANDBY mode, pcm-bridge feeds the dashboard's level meters and
SPL display. In MEASUREMENT mode, pcm-bridge continues running and can
provide real-time level feedback for the measurement wizard (gain
calibration display, sweep progress visualization) without interfering
with the measurement audio path.

This is a key architectural advantage of the daemon model: the level
display works in both modes because the data source (pcm-bridge) is
safe to run during measurement.

---

## 9. Cross-References

### Decisions

| ID | Summary | Relevance |
|----|---------|-----------|
| D-035 | Measurement safety rules | Safety constraints enforced by the daemon |
| D-036 | Central daemon replaces subprocess model | This document |
| D-037 | Signal generator safety | SEC-D037-01 loopback-only, SEC-D037-04 hard cap |
| D-040 | CamillaDSP abandoned, pure PW filter-chain | Drives RPC client architecture change (Section 3) |

### User Stories

| ID | Summary | Relevance |
|----|---------|-----------|
| US-047 | Path A: listening-position measurement | Primary measurement workflow |
| US-048 | Post-measurement visualization | Results display in RESULTS state |
| US-049 | Real-time websocket feed | WS broadcast architecture |
| US-012 | Gain calibration | GAIN_CAL state implementation |
| US-061 | Measurement pipeline adaptation | D-040 migration (Section 3 RPC clients) |
| US-052 | Signal generator D-040 adaptation | Managed mode, node.group, no loopback target |

### Architecture Documents

| Document | Relationship |
|----------|-------------|
| `measurement-workflow-ux.md` | UX/wizard design. Section 10 (subprocess backend) is **superseded** by this document. |
| `web-ui.md` | Web UI architecture. FilterChainCollector replaces CamillaDSPCollector (US060-1). pcm-bridge replaces JACK PCM collector. |
| `web-ui-monitoring-plan.md` | SPL metering design. SPL collector integrates with pcm-bridge. |
| `rt-audio-stack.md` | RT audio stack. Daemon operates within the scheduling hierarchy documented there. |

### Safety

All safety constraints: [`docs/operations/safety.md`](../operations/safety.md).
The daemon enforces Sections 1-5 of the safety manual programmatically.

### Lab Notes

| Lab Note | Relevance |
|----------|-----------|
| `change-S-010-measurement-test-failed.md` | Safety incident that motivated D-035/D-036 safety layers |
| `change-S-013-chn50p-nearfield-measurement.md` | First successful TK-143 measurement (CLI path) |

### Work Packages

| WP | Summary | Relevance |
|----|---------|-----------|
| WP-1 | Thermal ceiling | Section 7.3 thermal enforcement |
| WP-7 | pcm-bridge | Section 8 passive monitor tap |
| WP-8 | Power validation | Complements thermal ceiling with electrical limits |
