# US-053 Safety Controls Summary — AD Sign-off Evidence

**Prepared by:** worker-measure
**Date:** 2026-03-22
**Story:** US-053 (Manual Test Tool Page)
**DoD item:** #6 — AD sign-off: safety controls (hard cap, pre-action warning, emergency stop) verified

---

## 1. Hard Level Cap (D-009 Compliance)

### Requirement
D-009: All output must be <= -0.5 dBFS at every frequency. The manual test tool
must enforce this hard cap so that the operator cannot produce output exceeding
-0.5 dBFS through any UI interaction.

### Defense-in-Depth Implementation (4 layers)

**Layer 1 — Client-side HTML attribute (test.js:297)**
The level slider's `max` attribute is set to `-0.5` at initialization:
```javascript
slider.max = HARD_CAP_DBFS;  // HARD_CAP_DBFS = -0.5
```
This prevents the HTML range input from producing values above -0.5.

**Layer 2 — Client-side JavaScript clamping (test.js:279)**
On every `input` event, the value is clamped:
```javascript
if (val > HARD_CAP_DBFS) {
    val = HARD_CAP_DBFS;
    this.value = val;
}
```

**Layer 3 — Client-side play command clamping (test.js:450)**
When the `play` command is constructed, the level is clamped again:
```javascript
level_dbfs: Math.min(currentLevel, HARD_CAP_DBFS),
```

**Layer 4a — Server-side REST validation (routes.py:90-95)**
The FastAPI `PlayRequest` and `LevelRequest` Pydantic models clamp `level_dbfs`:
```python
if v > HARD_CAP_DBFS:    # HARD_CAP_DBFS = -0.5
    v = HARD_CAP_DBFS
```

**Layer 4b — Signal generator RPC REJECTION (rpc.rs:194-208)**
The Rust signal generator **rejects** (not clamps) levels above the cap:
```rust
fn validate_level(level_dbfs: f64, max_level_dbfs: f64) -> Result<(), String> {
    if level_dbfs > max_level_dbfs {
        return Err(format!("level {:.1} exceeds cap {:.1}", level_dbfs, max_level_dbfs));
    }
}
```
This is per AD-D037-3: levels above cap are REJECTED, not silently clamped.
The `--max-level-dbfs` flag defaults to -20.0 and is immutable after startup.
SEC-D037-04 validates it is within [-120.0, -0.5] at process start.

**Layer 5 — Per-sample hard clip (safety.rs:53-58)**
After all generation and fade ramp processing, every output sample is clamped:
```rust
pub fn hard_clip(&self, buffer: &mut [f32]) {
    let limit = self.max_level_linear;
    for sample in buffer.iter_mut() {
        *sample = sample.clamp(-limit, limit);
    }
}
```
This is the absolute last step before samples enter PipeWire. The
`SafetyLimits` struct is immutable after construction — no RPC command,
no code path can modify `max_level_linear` at runtime.

### Test Evidence — Unit Tests (Rust)
- `safety.rs`: 9 unit tests covering `from_dbfs`, `hard_clip` at boundaries,
  above/below limit, exact boundary, one-ULP-above boundary, empty buffer, zero
  preservation.
- `rpc.rs`: `level_above_cap_rejected`, `level_at_exactly_cap_accepted`,
  `level_below_cap_accepted`, `play_level_above_cap_rejected` — 4 tests
  verifying rejection semantics.

### Test Evidence — Unit Tests (Python)
- `routes.py` Pydantic validators enforce HARD_CAP_DBFS = -0.5 server-side.
- Channel validation: 1-8 only. Frequency validation: 20-20000 Hz.

### Verdict
**5-layer defense-in-depth.** Even if layers 1-4 are bypassed (e.g., crafted
WebSocket message), layer 5 (per-sample hard clip in Rust RT thread) prevents
any sample from exceeding the cap. The RT hard clip is immutable — set from
CLI args at startup, validated by SEC-D037-04.

---

## 2. Pre-Action Warning (Confirm Dialog)

### Requirement
AC-14 / DoD-5.2: Confirm dialog on first signal play per session. "Audio will
be generated on [channel]. Confirm?"

### Implementation (test.js:432-444)
```javascript
if (!hasConfirmedThisSession) {
    var ok = confirm(
        "This will play audio through the selected speaker channel(s).\n\n" +
        "Level: " + currentLevel.toFixed(1) + " dBFS\n" +
        "Channel(s): " + selectedChannels.map(...).join(", ") + "\n\n" +
        "Proceed?");
    if (!ok) return;
    hasConfirmedThisSession = true;
}
```

### Behavior
- First play per session: native browser `confirm()` dialog with level and
  channel info. User must click OK to proceed.
- Cancel returns without sending any RPC command — no audio output.
- Subsequent plays in the same session: dialog skipped (per AC requirement).
- Session reset: `hasConfirmedThisSession` is a module-scoped variable, reset
  on page reload.
- The dialog names the target channel(s) with human-readable labels
  (e.g., "3 Sub1").

### Test Evidence
- TP-004 Phase B test 12.1-12.3 covers this (pending execution).
- Code review confirms: no code path from PLAY button to `sendCmd` bypasses
  the confirmation check on first play.

### Verdict
**Compliant.** Uses native browser `confirm()` — cannot be suppressed by CSS
or JS without modifying the code. Channel and level are displayed in the dialog.

---

## 3. Emergency Stop

### Requirement
AC-15 / DoD-5.3: Prominent STOP button that immediately silences all output.
Status bar ABORT button also stops the signal generator.

### Implementation

**STOP button (test.js:461-469)**
```javascript
stopBtn.addEventListener("click", function () {
    sendCmd({ cmd: "stop" });
    stopBtn.classList.add("flash-stop");
    setTimeout(function () {
        stopBtn.classList.remove("flash-stop");
    }, 300);
});
```
- Sends `{ cmd: "stop" }` via WebSocket immediately on click.
- Visual feedback: red flash on button (300ms).
- STOP button is always visible when signal generator is connected (not hidden).

**ABORT integration (test.js:489-496)**
```javascript
PiAudio.emergencyStop = function () {
    sendCmd({ cmd: "stop" });
};
```
- The persistent status bar's ABORT button calls `PiAudio.emergencyStop`.
- This sends the same `stop` command to the signal generator.

**Signal generator stop behavior (Rust RT thread)**
- The `Stop` command is pushed to the lock-free SPSC queue.
- The PipeWire process callback drains all pending commands per quantum
  (AD-D037-6 multi-command-per-quantum semantics).
- Stop initiates a 20ms cosine fade-out ramp (configurable via `--ramp-ms`).
- After fade-out, output is silence (0.0).
- At quantum 1024 (DJ mode), worst-case latency to silence: 1 quantum
  (~21ms) + 20ms ramp = ~41ms.

**Button prominence**
- STOP button: `min-height: 56px` (UX spec Section 3.6).
- Positioned directly beside PLAY button in the action row.
- Always visible when signal generator controls are shown.

### Test Evidence
- `rpc.rs::stop_pushes_to_queue` unit test: verifies stop command reaches
  the command queue.
- `command.rs::command_stop_round_trip`: verifies Stop command survives
  SPSC queue transfer.
- STOP button DOM presence verified in scaffold tests.

### Verdict
**Compliant.** Two independent stop paths (STOP button + ABORT in status bar)
both send the same `stop` RPC command. The signal generator processes stop
within one quantum cycle and applies a 20ms fade-out to prevent click artifacts.

---

## 4. Additional Safety Controls

### Safe Defaults (test.js)
- Level slider defaults to **-40 dBFS** (inaudible through any practical speaker).
- No channel selected at page load — PLAY button is disabled.
- Signal type defaults to Sine (lowest risk — single frequency, easy to identify).

### Level Visual Warning (test.js:300-312)
- Slider above -6 dBFS: `danger` class (red tint per UX spec).
- Slider -20 to -6 dBFS: `warning` class (yellow tint).
- Below -20 dBFS: no visual warning.

### Channel Validation
- Channels validated to [1..8] at all layers (JS, Python, Rust).
- Empty channel list rejected at all layers.
- "Select all" button deliberately omitted (UX spec Section 3.3) — operator
  must tap each channel individually in multi-select mode.

### Command Allowlisting (rpc.rs:245-261)
Only these commands are accepted: `play`, `playrec`, `stop`, `set_level`,
`set_signal`, `set_channel`, `set_freq`, `status`, `capture_level`,
`get_recording`. All others return an error. Unit test
`unknown_command_rejected` verifies this.

### RPC Security (SEC-D037-01, SEC-D037-03)
- Signal generator listens on **loopback only** (127.0.0.1:4001).
  Non-loopback addresses are rejected at startup.
- Maximum line length: 4096 bytes (SEC-D037-03). Lines exceeding this are
  rejected. Unit test `line_exceeding_limit_rejected` verifies this.

---

## 5. Summary of Safety Layer Coverage

| Safety control | Client (JS) | Server (Python) | Signal gen (Rust) | RT thread |
|---|---|---|---|---|
| Hard cap -0.5 dBFS | Slider max + clamp | Pydantic clamp | RPC rejection | Per-sample hard clip |
| Channel validation | UI enforces 1-8 | Pydantic validates | RPC validates | Bitmask ignores OOB |
| Frequency validation | Slider range 20-20k | Pydantic validates | RPC validates | N/A |
| Pre-action warning | confirm() dialog | N/A | N/A | N/A |
| Emergency stop | STOP + ABORT buttons | WebSocket proxy | Stop command | 20ms fade-out |
| Safe defaults | -40 dBFS, no channel | N/A | Starts silent | Output = 0.0 |
| Command allowlist | N/A | Known endpoints only | Allowlist check | N/A |
| Loopback-only binding | N/A | N/A | SEC-D037-01 | N/A |

---

## 6. Remaining Items (Need Pi Access)

The following require Pi hardware access and cannot be verified locally:

- **D5.1 (TP-004):** Runtime verification that signal gen enforces -0.5 dBFS
  cap on actual audio output (Phase C test).
- **D5.3 (TP-004):** Emergency stop timing measurement — verify silence within
  100ms of pressing STOP (Phase C test).
- **AC-13.3:** Status bar ABORT stops signal gen on Pi (Phase C test).

All code-level safety mechanisms are verified via unit tests and code review.
The above Phase C items confirm the mechanisms work end-to-end on real hardware.
