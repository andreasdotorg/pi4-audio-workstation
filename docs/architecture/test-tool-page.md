# Test Tool Page UX Specification

**Status:** UX design complete, pending implementation
**Author:** UX Specialist
**Scope:** Web UI page for manual signal generation, SPL readout, and spectrum analysis
**Dependencies:** Persistent status bar (TK-225/226), RT signal generator (architect design pending),
`/ws/monitoring` and `/ws/pcm` endpoints (existing)
**Relates to:** TK-231 (SPL computation), TK-224 (pink noise glitches), TK-229 (persistent stream),
US-047 (Path A measurement), D-036 (measurement daemon)

---

## 1. Purpose

The test tool page provides manual control over the audio system for debugging,
verification, and calibration. It replaces ad-hoc SSH commands (`jack-tone-generator.py`)
with a visual, interactive tool accessible from any browser on the venue network.

**Core use cases:**

1. **Routing verification.** Play a tone on a specific channel, confirm it comes
   out the correct speaker. "I pressed channel 3 (Sub1) and heard the sub." This
   is the first thing an engineer does after connecting speakers at a venue.

2. **SPL calibration cross-reference.** Play a known signal (pink noise at -20 dBFS)
   through a specific channel while measuring with a known-good tool (REW on
   Windows via UMIK-1) to cross-reference the Pi's SPL computation. This is the
   owner's use case for debugging TK-231.

3. **Spectrum monitoring.** View the UMIK-1 mic input spectrum in real time to
   diagnose acoustic problems: room modes, rattling objects, feedback frequencies,
   cable hum. This works even when the signal generator is not playing -- the
   operator can monitor ambient noise or a running DJ set.

4. **Channel-by-channel level verification.** Play a reference signal on each
   output channel sequentially, confirming that the mini meters and full Dashboard
   meters agree with physical output levels.

### Design Principles (inherited from TK-160)

- **Big text, high contrast.** Readable at arm's length on phone/tablet in venue lighting.
- **Minimum touch target 48x48px.** All interactive elements.
- **ABORT is always one tap.** Via the persistent status bar (not duplicated here).

### Additional Principles for Test Tool

- **Signal generator and spectrum are co-visible.** The operator must see the
  output controls (left) and the measured result (right) at the same time.
  Cause and effect on one screen.
- **No automation.** Unlike the Measure tab's wizard, the test tool does not
  sequence operations or advance steps. The operator has full manual control.
  Every action is explicit.
- **Safe defaults.** The page loads with signal generator stopped, level at
  -40 dBFS (inaudible), no channel selected. The operator must deliberately
  choose a channel and level before anything plays.

---

## 2. Page Layout

### 2.1 Desktop/Tablet (> 800px, landscape)

```
+------------------------------------------------------------------+
| Pi Audio  [Dashboard] [System] [Measure] [*Test*] [MIDI]         |
+------------------------------------------------------------------+
| [========= persistent status bar (32px) ========================]|
+------------------------------------------------------------------+
|                                                                    |
|  SIGNAL GENERATOR                    |  MEASURED SIGNAL            |
|                                      |                             |
|  Signal type                         |  +------------------------+ |
|  [Sine] [White] [Pink] [Sweep]       |  |                        | |
|                                      |  |      SPECTRUM          | |
|  Frequency (sine/sweep)              |  |      ANALYZER          | |
|  |=======================| 1000 Hz   |  |                        | |
|                                      |  |  (UMIK-1 input         | |
|  Output channel                      |  |   or main L+R)         | |
|  [SatL] [SatR] [Sub1] [Sub2]        |  |                        | |
|  [EngL] [EngR] [IEML] [IEMR]        |  +------------------------+ |
|                                      |                             |
|  Level                               |  Source: [UMIK-1 v]        |
|  |=======================| -20.0 dBFS|  SPL (A):  75.2 dB         |
|                                      |  SPL (C):  78.4 dB         |
|  Duration                            |  SPL peak: 81.1 dB         |
|  (*) Continuous  ( ) Burst: [5] sec  |                             |
|                                      |  Mic: UMIK-1 (connected)   |
|  +-------------------+ +----------+  |                             |
|  |   >>> PLAY <<<    | |   STOP   |  |                             |
|  +-------------------+ +----------+  |                             |
|                                      |                             |
+------------------------------------------------------------------+
```

The page is split into two columns: signal generator controls (left, ~50%) and
measured signal display (right, ~50%). The split is a vertical divider.

### 2.2 Phone (< 600px, portrait)

On phone screens, the layout stacks vertically: signal generator controls on
top, spectrum display below. The spectrum display is 200px minimum height.

```
+---------------------------+
| [*Test*]                  |
+---------------------------+
| [status bar]              |
+---------------------------+
| SIGNAL GENERATOR          |
|                           |
| [Sine] [Pink] [Sweep]    |
|                           |
| [SatL] [SatR] [Sub1]...  |
|                           |
| Level: -20.0 dBFS        |
| |=====================|  |
|                           |
| [>>> PLAY <<<]  [STOP]   |
+---------------------------+
| SPECTRUM ANALYZER         |
| +---------------------+  |
| |                     |  |
| |                     |  |
| +---------------------+  |
| SPL: 75.2 dBA            |
| Mic: UMIK-1 (connected)  |
+---------------------------+
```

---

## 3. Signal Generator Controls

### 3.1 Signal Type Selector

Four toggle buttons in a horizontal row. Exactly one is active at a time.

| Button | Signal | Notes |
|--------|--------|-------|
| Sine | Pure sine tone | Default. Frequency control visible. |
| White | White noise | Broadband, flat spectrum. Frequency control hidden. |
| Pink | Pink noise (1/f) | Perceptually flat. Frequency control hidden. Standard for SPL measurement. |
| Sweep | Log frequency sweep | Frequency range controls visible (start/end Hz). Used for manual IR inspection. |

**Styling:**

```css
.tt-signal-btn {
    font-size: 12px;
    font-weight: 700;
    padding: 8px 16px;
    min-height: 40px;
    min-width: 64px;
    border: 1px solid var(--border);
    border-radius: 3px;
    background: var(--bg-bar);
    color: var(--text-dim);
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.tt-signal-btn.active {
    background: rgba(66, 165, 245, 0.15);
    color: var(--blue);
    border-color: var(--blue);
}
```

### 3.2 Frequency Control

Visible only when signal type is Sine or Sweep.

**Sine mode:** Single horizontal slider + numeric readout.
- Range: 20 Hz to 20,000 Hz (logarithmic scale)
- Default: 1000 Hz
- Snap points: 20, 50, 80, 100, 200, 500, 1000, 2000, 5000, 10000, 20000 Hz
- The numeric readout is tappable to open a text input for precise entry.

**Sweep mode:** Two sliders (start frequency, end frequency) + duration.
- Start default: 20 Hz
- End default: 20,000 Hz
- Duration: uses the burst duration setting (Section 3.5)

### 3.3 Output Channel Selector

Eight toggle buttons arranged in a 4x2 grid. By default, zero channels are
selected (nothing plays). The operator must explicitly select at least one
channel before the PLAY button becomes enabled.

```
[1 SatL] [2 SatR] [3 Sub1] [4 Sub2]
[5 EngL] [6 EngR] [7 IEML] [8 IEMR]
```

**Selection behavior:**
- **Single-select mode (default):** Tapping a channel selects it and deselects
  any previously selected channel. This is the safe default for routing
  verification -- one speaker at a time.
- **Multi-select toggle:** A small "MULTI" toggle below the channel grid enables
  multi-select. When enabled, tapping a channel toggles it independently. This
  allows stereo pairs (SatL + SatR) or all channels simultaneously.
- **No "select all" button.** Selecting all 8 channels simultaneously is a
  deliberate action requiring 8 taps in multi mode. This prevents accidental
  full-power output through all speakers.

**Channel button styling:**

```css
.tt-channel-btn {
    font-size: 11px;
    font-weight: 700;
    padding: 8px 12px;
    min-height: 44px;
    min-width: 72px;
    border: 1px solid var(--border);
    border-radius: 3px;
    background: var(--bg-bar);
    color: var(--text-dim);
    cursor: pointer;
    text-align: center;
}

.tt-channel-btn.selected {
    background: rgba(46, 125, 50, 0.2);
    color: var(--green);
    border-color: rgba(46, 125, 50, 0.5);
}

/* Sub channels get a distinct tint (they are louder per watt) */
.tt-channel-btn.sub-channel.selected {
    background: rgba(255, 111, 0, 0.15);
    color: var(--orange);
    border-color: rgba(255, 111, 0, 0.4);
}
```

Sub channels (3 Sub1, 4 Sub2) use orange when selected as a visual warning that
subwoofers have high acoustic output per electrical watt. This is a subtle
safety cue, not a blocking mechanism.

### 3.4 Level Slider

Horizontal slider with numeric readout.

- Range: -60 dBFS to 0 dBFS
- Default: -40 dBFS (inaudible through any practical speaker)
- Snap detents at: -60, -40, -30, -20, -10, -6, -3, 0 dBFS
- Numeric readout shows one decimal place: "-20.0 dBFS"
- Tapping the numeric readout opens a text input for precise entry
- The slider thumb color changes with level: green < -20, yellow -20 to -6, red > -6

**Safety constraint:** The level slider has a soft warning at -6 dBFS: the
slider area above -6 dBFS turns red-tinted. This does NOT block the operator
from setting higher levels -- it is a visual cue, not a hard limit. The hard
safety limits are enforced in the RT signal generator (D-009 compliance: the
signal generator applies the same -0.5 dBFS hard cap as the measurement
pipeline).

### 3.5 Duration Control

Two radio buttons:

| Option | Behavior |
|--------|----------|
| **Continuous** (default) | Signal plays until STOP is pressed |
| **Burst** | Signal plays for N seconds, then stops automatically. N is editable (default: 5s, range: 1-60s) |

Burst mode is useful for level checks where the operator wants a known-duration
signal without needing to watch the screen to press STOP.

### 3.6 PLAY and STOP Buttons

Two buttons, side by side.

**PLAY button:**
- 64px height, accent color (blue), full-width in its column
- Text: "PLAY" when idle
- **Disabled** when: no channel selected, or signal generator not connected
- When pressed: sends RPC command to signal generator, transitions to PLAYING state
- In PLAYING state: text changes to "PLAYING", background pulses gently (CSS animation),
  button becomes functionally a no-op (pressing again does nothing)

**STOP button:**
- 64px height, secondary color (dark gray border), beside PLAY
- Text: "STOP"
- **Disabled** when: not playing
- When pressed: sends stop RPC command to signal generator
- Immediate visual feedback: STOP button briefly flashes red on press

```css
.tt-play-btn {
    font-size: 14px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 16px 24px;
    min-height: 56px;
    flex: 2;
    border: 2px solid rgba(66, 165, 245, 0.5);
    border-radius: 4px;
    background: rgba(66, 165, 245, 0.12);
    color: var(--blue);
    cursor: pointer;
}

.tt-play-btn.playing {
    background: rgba(121, 226, 91, 0.12);
    border-color: rgba(121, 226, 91, 0.5);
    color: var(--green);
    animation: pulse-play 2s ease-in-out infinite;
}

.tt-play-btn:disabled {
    opacity: 0.3;
    cursor: default;
}

@keyframes pulse-play {
    0%, 100% { background: rgba(121, 226, 91, 0.12); }
    50% { background: rgba(121, 226, 91, 0.20); }
}

.tt-stop-btn {
    font-size: 14px;
    font-weight: 700;
    text-transform: uppercase;
    padding: 16px 16px;
    min-height: 56px;
    flex: 1;
    border: 2px solid var(--border);
    border-radius: 4px;
    background: var(--bg-bar);
    color: var(--text-dim);
    cursor: pointer;
}

.tt-stop-btn:disabled {
    opacity: 0.3;
    cursor: default;
}
```

**PLAY button validation:** When the operator taps PLAY with no channel selected,
the channel selector grid briefly highlights with a red border and the button
shows "Select a channel" for 2 seconds. This is faster than a modal dialog and
does not require dismissal.

---

## 4. Measured Signal Display (Right Column)

### 4.1 Spectrum Analyzer

The spectrum analyzer shows the live FFT of the selected input source. It uses
the same JS FFT pipeline as the Dashboard spectrum (TK-115): Blackman-Harris
window, 2048-point FFT, log-frequency x-axis, dB y-axis.

**Differences from Dashboard spectrum:**
- The source is selectable (see Section 4.2), not hardcoded to main L+R.
- The display range is 20 Hz to 20 kHz (vs 30 Hz to 20 kHz on Dashboard) because
  the test tool is used for sub-bass debugging.
- The y-axis range is -80 dB to 0 dB (vs -60 to 0 on Dashboard) for better
  visibility of low-level signals during calibration.

**Canvas size:** Full width of the right column, minimum 300px wide, minimum
200px tall. Aspect ratio approximately 3:2.

**Rendering:** Shares the `SpectrumRenderer` class from `spectrum.js`. A second
instance is created with different configuration parameters (frequency range,
dB range, source channel).

### 4.2 Source Selector

A dropdown (or small toggle button group) above the spectrum display selects
the input source:

| Source | PCM channels | Use case |
|--------|-------------|----------|
| **UMIK-1** | USBStreamer capture ch 0 (mic input) | Measurement, SPL calibration |
| **Main L+R** | CamillaDSP monitor taps ch 0+1 | Monitoring the program bus |
| **Sub sum** | CamillaDSP monitor tap ch 2 | Sub-bass monitoring |

Default: UMIK-1 (the primary use case for the test tool is measurement debugging).

**Backend implication:** The current PcmStreamCollector captures 3 fixed channels
(main L, main R, sub sum) from CamillaDSP monitor taps. Adding UMIK-1 requires
the PCM stream to include the USBStreamer capture channel. This is a backend
change: the JACK client registers an additional input port connected to the
USBStreamer's capture channel 0.

When UMIK-1 is not connected (USB device not present), the source selector shows
"UMIK-1 (not connected)" in amber text and the spectrum display shows a centered
message: "Microphone not connected. Connect UMIK-1 via USB."

### 4.3 SPL Display

Below the spectrum analyzer, the SPL readout shows calibrated sound pressure
level computed from the UMIK-1 input signal.

```
SPL (A):  75.2 dB
SPL (C):  78.4 dB
SPL peak: 81.1 dB
```

| Metric | Weighting | Window | Purpose |
|--------|-----------|--------|---------|
| SPL (A) | A-weighted | 1s RMS (Leq) | Standard noise/music level |
| SPL (C) | C-weighted | 1s RMS (Leq) | Sub-bass emphasis, better for PA |
| SPL peak | C-weighted | Peak hold (3s decay) | Maximum instantaneous level |

**TK-231 handling (owner directive: test tool helps debug SPL):**

Until TK-231 is resolved and the UMIK-1 calibration chain is validated, the SPL
readout includes a persistent banner:

```
+-----------------------------------------+
| SPL UNCALIBRATED                        |
| Calibration file not verified.          |
| Values are approximate.                 |
+-----------------------------------------+
| SPL (A):  75.2 dB                       |
| SPL (C):  78.4 dB                       |
| SPL peak: 81.1 dB                       |
+-----------------------------------------+
```

The "UNCALIBRATED" banner is shown when:
- UMIK-1 calibration file is not loaded, OR
- Calibration chain has not been verified against a reference, OR
- A flag in the backend config marks the SPL pipeline as unvalidated

Once validated (future work, post-TK-231), the banner disappears and the SPL
values are shown without qualification.

Even in uncalibrated state, the SPL readout is useful for:
- Relative comparisons ("this channel is 6 dB louder than that one")
- Cross-referencing with REW (the owner's debugging approach)
- Tracking changes ("the level went up 3 dB when I adjusted the gain")

### 4.4 Microphone Status

Below the SPL readout, a mic status line shows the current microphone state:

| State | Display | Color |
|-------|---------|-------|
| Connected | `Mic: UMIK-1 (connected)` | green |
| Not connected | `Mic: not connected` | amber |
| Reconnecting | `Mic: reconnecting...` | amber, pulsing |

**USB hot-plug support (owner directive):** The backend detects UMIK-1
connect/disconnect events (via udev or periodic USB device enumeration). When
the UMIK-1 is plugged in during a test tool session:

1. Backend detects the new USB audio device
2. JACK client reconnects to the USBStreamer capture port
3. WebSocket pushes `mic_status: "connected"` to the browser
4. Spectrum display resumes showing mic input
5. SPL readout resumes updating

When the UMIK-1 is unplugged:

1. Backend detects device removal
2. JACK client loses the capture port (graceful handling, no crash)
3. WebSocket pushes `mic_status: "disconnected"` to the browser
4. Spectrum display shows "Microphone not connected" message
5. SPL readout freezes at last known value with "(stale)" suffix

The transition is seamless -- no page reload, no manual reconnection. The test
tool degrades gracefully when the mic is absent and recovers automatically when
it returns.

---

## 5. Signal Generator State Feedback

### 5.1 Confirmed State Display

The operator must see confirmed state from the signal generator, not echoed
commands. When the operator presses PLAY at -20 dBFS on channel 3:

1. Browser sends: `{ cmd: "play", channel: 3, level_dbfs: -20.0, signal: "sine", freq: 1000 }`
2. Signal generator receives command, begins outputting signal
3. Signal generator reports back: `{ state: "playing", channel: 3, level_dbfs: -20.0, signal: "sine", freq: 1000 }`
4. Browser updates PLAY button to PLAYING state only after receiving confirmation

If the signal generator fails to start (e.g., JACK client not connected), the
operator sees the PLAY button remain in idle state and an error message appears:
"Signal generator not responding. Check Pi audio services."

### 5.2 Live Parameter Changes

While playing, the operator can change parameters without stopping:

- **Channel change:** Sends new channel via RPC. Signal generator fades out
  current channel (20ms cosine ramp), fades in new channel. Operator sees the
  channel button highlight move. Mini meters confirm the routing change.
- **Level change:** Sends new level via RPC. Signal generator applies smooth
  gain ramp (50ms). Level slider tracks the confirmed level from feedback.
- **Signal type change:** Sends new signal type. Signal generator crossfades
  (50ms). Signal type buttons update on confirmation.
- **Frequency change:** Sends new frequency. Signal generator phase-continuously
  transitions. Frequency readout updates on confirmation.

These live parameter changes are the core UX advantage of the persistent RT
signal generator. With the old `sd.playrec()` model, any parameter change
required stopping and restarting the audio stream.

---

## 6. WebSocket Protocol

### 6.1 New Endpoint: `/ws/siggen`

The test tool uses a new WebSocket endpoint for bidirectional communication with
the signal generator (via the FastAPI daemon as proxy).

**Browser to server (commands):**

```json
{ "cmd": "play", "signal": "sine", "freq": 1000, "channel": 3, "level_dbfs": -20.0, "duration": null }
{ "cmd": "play", "signal": "pink", "channel": 1, "level_dbfs": -25.0, "duration": 5.0 }
{ "cmd": "stop" }
{ "cmd": "set_level", "level_dbfs": -15.0 }
{ "cmd": "set_channel", "channel": 4 }
{ "cmd": "set_signal", "signal": "white" }
{ "cmd": "set_freq", "freq": 440 }
```

**Server to browser (state updates):**

```json
{ "type": "siggen_state", "state": "playing", "signal": "sine", "freq": 1000, "channel": 3, "level_dbfs": -20.0 }
{ "type": "siggen_state", "state": "stopped" }
{ "type": "siggen_state", "state": "error", "message": "JACK client disconnected" }
{ "type": "mic_status", "connected": true, "device": "UMIK-1" }
{ "type": "mic_status", "connected": false }
```

**Update rate:** Signal generator state is pushed on every state change (not
polled). Mic status is pushed on connect/disconnect events. Typical update rate
during active use: < 1 Hz (only when operator changes parameters).

### 6.2 PCM Source Selection

The existing `/ws/pcm` endpoint currently streams 3 fixed channels. To support
the UMIK-1 source, the PCM stream needs a source selection mechanism:

**Option A (recommended):** Add UMIK-1 as a 4th channel to the existing PCM
stream. The browser selects which channel(s) to FFT. Total bandwidth increases
from ~576 KB/s to ~768 KB/s (4 channels x 256 frames x 4 bytes x 187.5 Hz).
Simple, no protocol change.

**Option B:** Separate PCM endpoint for mic input (`/ws/pcm/mic`). Cleaner
separation but more WebSocket connections.

The architect decides the mechanism. The UX spec requires only that the browser
can receive UMIK-1 PCM data for spectrum display and SPL computation. The source
selector dropdown switches which channel the JS FFT processes.

---

## 7. Error States

### 7.1 Signal Generator Not Available

If the RT signal generator process is not running (e.g., not yet deployed, or
crashed), the test tool page shows:

```
+------------------------------------------------------------------+
| SIGNAL GENERATOR                     | MEASURED SIGNAL            |
|                                      |                            |
|  Signal generator not available.     | (spectrum still works)     |
|                                      |                            |
|  The RT signal generator service     |                            |
|  is not running on the Pi.           |                            |
|                                      |                            |
|  [controls grayed out]               |                            |
+------------------------------------------------------------------+
```

The left column shows a message explaining the situation. All controls are
disabled (grayed out). The right column (spectrum + SPL) continues to work
because it depends on the PCM stream, not the signal generator. This allows the
operator to use the test tool page purely for spectrum monitoring even before the
signal generator is deployed.

### 7.2 WebSocket Disconnected

Uses the same reconnect behavior as other views: reconnect overlay with
exponential backoff. The persistent status bar's connection dot turns red.

### 7.3 CamillaDSP Not Running

If CamillaDSP is stopped, the signal generator can still produce output through
the JACK graph, but it will not reach the speakers (CamillaDSP is in the signal
path). The test tool shows a warning banner:

```
!! CamillaDSP is not running. Signal will not reach speakers. !!
```

This uses the existing DSP state data from `/ws/monitoring`.

---

## 8. Integration with Status Bar

### 8.1 ABORT Button Visibility

When the signal generator is playing (state = "playing"), the persistent status
bar's ABORT button becomes visible. Pressing ABORT sends `{ cmd: "stop" }` to
the signal generator and immediately mutes output. The ABORT button hides once
the signal generator confirms stopped state.

### 8.2 Mini Meter Feedback

When a test signal is playing on channel 3 (Sub1), the operator sees:
- The Sub1 mini meter in the status bar showing signal level
- The full Dashboard meters (if the Dashboard tab is visible) showing the same
- The spectrum display showing the signal's frequency content (if source is set
  to main L+R or sub sum -- if source is UMIK-1, the spectrum shows the acoustic
  response)

This multi-point feedback loop is the core value proposition of the persistent
status bar + test tool combination: play signal here, see levels there, see
spectrum here.

---

## 9. HTML Structure

The test tool page is added to `index.html` as a new `.view` container:

```html
<!-- VIEW: Test — Manual signal generation and spectrum analysis -->
<div class="view" id="view-test">
    <div class="tt-layout">
        <!-- Left column: signal generator controls -->
        <div class="tt-controls">
            <div class="tt-section">
                <div class="tt-section-title">SIGNAL TYPE</div>
                <div class="tt-signal-row">
                    <button class="tt-signal-btn active" data-signal="sine">Sine</button>
                    <button class="tt-signal-btn" data-signal="white">White</button>
                    <button class="tt-signal-btn" data-signal="pink">Pink</button>
                    <button class="tt-signal-btn" data-signal="sweep">Sweep</button>
                </div>
            </div>

            <!-- Frequency (visible for sine/sweep only) -->
            <div class="tt-section" id="tt-freq-section">
                <div class="tt-section-title">FREQUENCY</div>
                <div class="tt-slider-row">
                    <input type="range" class="tt-slider" id="tt-freq-slider"
                           min="1.301" max="4.301" step="0.001" value="3.0">
                    <span class="tt-slider-value" id="tt-freq-value">1000 Hz</span>
                </div>
            </div>

            <div class="tt-section">
                <div class="tt-section-title">OUTPUT CHANNEL</div>
                <div class="tt-channel-grid">
                    <button class="tt-channel-btn" data-ch="1">1 SatL</button>
                    <button class="tt-channel-btn" data-ch="2">2 SatR</button>
                    <button class="tt-channel-btn sub-channel" data-ch="3">3 Sub1</button>
                    <button class="tt-channel-btn sub-channel" data-ch="4">4 Sub2</button>
                    <button class="tt-channel-btn" data-ch="5">5 EngL</button>
                    <button class="tt-channel-btn" data-ch="6">6 EngR</button>
                    <button class="tt-channel-btn" data-ch="7">7 IEML</button>
                    <button class="tt-channel-btn" data-ch="8">8 IEMR</button>
                </div>
                <label class="tt-multi-toggle">
                    <input type="checkbox" id="tt-multi-select"> MULTI
                </label>
            </div>

            <div class="tt-section">
                <div class="tt-section-title">LEVEL</div>
                <div class="tt-slider-row">
                    <input type="range" class="tt-slider tt-level-slider" id="tt-level-slider"
                           min="-60" max="0" step="0.1" value="-40">
                    <span class="tt-slider-value" id="tt-level-value">-40.0 dBFS</span>
                </div>
            </div>

            <div class="tt-section">
                <div class="tt-section-title">DURATION</div>
                <div class="tt-duration-row">
                    <label class="tt-radio">
                        <input type="radio" name="tt-duration" value="continuous" checked> Continuous
                    </label>
                    <label class="tt-radio">
                        <input type="radio" name="tt-duration" value="burst"> Burst:
                        <input type="number" class="tt-burst-input" id="tt-burst-sec"
                               min="1" max="60" value="5" disabled> sec
                    </label>
                </div>
            </div>

            <div class="tt-action-row">
                <button class="tt-play-btn" id="tt-play-btn" disabled>PLAY</button>
                <button class="tt-stop-btn" id="tt-stop-btn" disabled>STOP</button>
            </div>

            <!-- Signal generator status -->
            <div class="tt-siggen-status" id="tt-siggen-status">
                Signal generator: <span id="tt-siggen-state">checking...</span>
            </div>
        </div>

        <!-- Right column: measured signal -->
        <div class="tt-measured">
            <div class="tt-section">
                <div class="tt-section-title-row">
                    <span class="tt-section-title">SPECTRUM ANALYZER</span>
                    <select class="tt-source-select" id="tt-spectrum-source">
                        <option value="umik1">UMIK-1</option>
                        <option value="main">Main L+R</option>
                        <option value="sub">Sub sum</option>
                    </select>
                </div>
                <div class="tt-spectrum-container">
                    <canvas class="tt-spectrum-canvas" id="tt-spectrum-canvas"></canvas>
                    <div class="tt-spectrum-overlay hidden" id="tt-spectrum-no-mic">
                        Microphone not connected.<br>Connect UMIK-1 via USB.
                    </div>
                </div>
            </div>

            <div class="tt-section tt-spl-section">
                <div class="tt-spl-uncal-banner" id="tt-spl-uncal">
                    SPL UNCALIBRATED — values are approximate
                </div>
                <div class="tt-spl-grid">
                    <div class="tt-spl-row">
                        <span class="tt-spl-label">SPL (A)</span>
                        <span class="tt-spl-value" id="tt-spl-a">--</span>
                        <span class="tt-spl-unit">dB</span>
                    </div>
                    <div class="tt-spl-row">
                        <span class="tt-spl-label">SPL (C)</span>
                        <span class="tt-spl-value" id="tt-spl-c">--</span>
                        <span class="tt-spl-unit">dB</span>
                    </div>
                    <div class="tt-spl-row">
                        <span class="tt-spl-label">SPL peak</span>
                        <span class="tt-spl-value" id="tt-spl-peak">--</span>
                        <span class="tt-spl-unit">dB</span>
                    </div>
                </div>
            </div>

            <div class="tt-mic-status" id="tt-mic-status">
                Mic: <span id="tt-mic-state">checking...</span>
            </div>
        </div>
    </div>
</div>
```

A new nav tab is added to the nav-bar:

```html
<button class="nav-tab" data-view="test">Test</button>
```

---

## 10. JavaScript Module (`test.js`)

The test tool page is implemented as a view module registered with PiAudio:

```javascript
PiAudio.registerView("test", {
    init: function() { /* set up event listeners, create spectrum renderer */ },
    onShow: function() { /* start spectrum RAF loop, connect siggen WS */ },
    onHide: function() { /* pause spectrum RAF loop */ }
});
```

Key functions:
- Signal type button click handlers (toggle active class, show/hide freq control)
- Channel button click handlers (single/multi select logic)
- Level slider input handler (send `set_level` on change, with 50ms debounce)
- Frequency slider input handler (log scale conversion, 50ms debounce)
- PLAY/STOP button handlers (send commands via `/ws/siggen`)
- Spectrum renderer (second instance of existing `SpectrumRenderer`)
- SPL computation from PCM data (A-weighting + C-weighting digital filters)
- Signal generator state updates (from `/ws/siggen` messages)
- Mic status updates (show/hide overlay, update mic status text)

---

## 11. Resource Budget

| Component | CPU (Pi) | Bandwidth | Notes |
|-----------|----------|-----------|-------|
| Signal generator WebSocket | < 0.01% | < 0.1 KB/s | Event-driven, not polled |
| PCM stream (4th channel added) | +0.02% | +192 KB/s | One additional float32 channel |
| SPL computation (browser) | 0 (browser) | 0 | JS-side A/C-weighting filter |
| Spectrum rendering (browser) | 0 (browser) | 0 | Second FFT instance, same data |
| **Total additional Pi load** | **< 0.03%** | **+192 KB/s** | Negligible |

---

## 12. Implementation Checklist

1. [ ] Add "Test" nav tab to `index.html`
2. [ ] Add `#view-test` HTML structure to `index.html`
3. [ ] Add test tool CSS to `style.css`
4. [ ] Create `test.js` view module
5. [ ] Register view with `PiAudio.registerView("test", ...)`
6. [ ] Implement signal type toggle buttons
7. [ ] Implement frequency slider (log scale)
8. [ ] Implement channel selector grid (single/multi mode)
9. [ ] Implement level slider with color-coded thumb
10. [ ] Implement duration radio buttons
11. [ ] Implement PLAY/STOP button logic with validation
12. [ ] Create second `SpectrumRenderer` instance for test tool spectrum
13. [ ] Implement source selector dropdown
14. [ ] Implement SPL computation (A-weighting + C-weighting)
15. [ ] Implement SPL uncalibrated banner logic
16. [ ] Implement mic status display with hot-plug support
17. [ ] Add `/ws/siggen` WebSocket endpoint to FastAPI backend (proxy to signal generator)
18. [ ] Add UMIK-1 PCM channel to PcmStreamCollector (4th channel)
19. [ ] Wire ABORT button in status bar to stop signal generator
20. [ ] Implement CamillaDSP-not-running warning banner
21. [ ] Implement signal-generator-not-available graceful degradation
22. [ ] Add responsive layout for phone (<600px)
23. [ ] Test: routing verification workflow (play tone on each channel)
24. [ ] Test: SPL cross-reference workflow (pink noise + REW comparison)
25. [ ] Test: spectrum monitoring without signal generator
26. [ ] Test: UMIK-1 hot-plug (connect/disconnect during session)
27. [ ] Test: ABORT from status bar stops signal generator
