# Persistent Status Bar UX Specification (TK-225/TK-226)

**Status:** UX design complete, pending implementation
**Author:** UX Specialist
**Scope:** Cross-tab persistent status bar with mini level meters and system health
**Dependencies:** `/ws/monitoring` endpoint (existing), `/ws/system` endpoint (existing)
**Relates to:** TK-225 (persistent status bar), TK-226 (mini 24-channel meters),
TK-160 (measurement workflow, ABORT button relocation)

---

## 1. Design Rationale

The current web UI provides system health and level meters only on the Dashboard
tab. When the operator navigates to the Measure, System, Test, or MIDI tabs,
they lose all peripheral awareness of audio state. This is the opposite of what
live audio work requires: the operator must always see whether audio is flowing,
whether anything is clipping, and whether the system is healthy -- regardless of
which page they are on.

The persistent status bar is a fixed chrome element that appears below the
navigation bar and above all tab content, on every page, at all times. It is
never hidden, never collapsed, and never scrolled off screen.

### Design Principles

1. **Always visible.** The status bar is rendered outside the `.view` container.
   Tab switching does not affect it. It survives all page state transitions.
2. **Glanceable.** All information is readable at arm's length (1.5m) under
   stage lighting. Uses color + shape (not color alone) for status encoding.
3. **Non-interactive by default.** The status bar is a read-only display surface
   except for the ABORT button. No sliders, no dropdowns, no hover menus. The
   operator never needs to interact with the status bar during normal operation.
4. **Mode-aware.** The content adapts to the current operational mode
   (DJ/Live/Measurement) but the layout does not shift. Elements that are not
   applicable to the current mode show "--" rather than disappearing (spatial
   memory preservation).
5. **Zero additional Pi CPU.** The status bar consumes only data already being
   streamed via existing WebSocket endpoints. No new backend polling, no new
   collectors, no new endpoints.

---

## 2. Layout

### 2.1 Structural Position

```
+------------------------------------------------------------------+
| nav-bar (28px)   [Dashboard] [System] [Measure] [Test] [MIDI]    |
+------------------------------------------------------------------+
| STATUS BAR (32px) — ALWAYS VISIBLE, ALL TABS                     |
+------------------------------------------------------------------+
| .view content (tab-specific, fills remaining viewport height)     |
|                                                                    |
+------------------------------------------------------------------+
```

The status bar sits between the nav-bar and the view content. The view container
height becomes `calc(100vh - 28px - 32px)` = `calc(100vh - 60px)`.

### 2.2 Status Bar Internal Layout

The status bar is divided into three zones: left (mini meters), center (system
health), and right (mode + alerts + ABORT).

```
+------------------------------------------------------------------+
| [mini meters: 24 channels]  | DSP:Run Q:256 | 45C 38% | DJ [!!] |
+------------------------------------------------------------------+
 ^-- left zone (flex: 1)       ^-- center       ^-- right zone
```

**Left zone — Mini Level Meters (flex: 1, min-width: 0)**

24 channel meters in a single horizontal row, grouped with subtle separators.
Each meter is a 4px-wide vertical bar, 20px tall. Groups:

| Group | Channels | Count | Color | Separator after |
|-------|----------|-------|-------|-----------------|
| MAIN | Capture ch 0-1 (ML, MR) | 2 | blue-silver #8a94a4 | 4px gap |
| APP>DSP | Capture ch 2-7 | 6 | dark cyan #00838f | 4px gap |
| DSP>OUT | Playback ch 0-7 | 8 | forest green #2e7d32 | 4px gap |
| PHYS IN | USBStreamer capture ch 0-7 | 8 | dark amber #c17900 | -- |

Total width: 24 bars x 4px + 23 gaps x 1px + 3 group gaps x 4px = 131px.
This fits comfortably in the left zone even on phone screens.

Each mini meter bar:
- Height: 20px (within the 32px status bar, vertically centered)
- Width: 4px (MAIN meters are 6px for emphasis)
- Background: `var(--bg-bar)` (#1f2229)
- Fill color: group color at < -12 dB, yellow at -12 to -3 dB, red at > -3 dB
- Fill direction: bottom to top (same as full meters)
- Peak hold: 1px white line at peak position, decays over 1.5s
- Clip indicator: entire bar flashes red for 3s when peak >= -0.5 dBFS
- Silent state: bar at 0% fill, no dimming (too small for dimming to be useful)

No labels on mini meters. Labels would not be readable at 4px width. The
spatial grouping and color coding provide identification. For precise
identification, the operator looks at the full meters on the Dashboard tab.

**Center zone — System Health (flex-shrink: 0, ~200px)**

Condensed single-line system health indicators:

```
DSP:Run  Q:256  Clip:0  Xr:0
```

| Element | Source | Color logic | Format |
|---------|--------|-------------|--------|
| DSP state | `/ws/monitoring` `cdsp_state` | green=Running, red=other | `DSP:Run` / `DSP:Stop` / `DSP:--` |
| Quantum | `/ws/system` `pw_quantum` | white (informational) | `Q:256` / `Q:1024` |
| Clipped | `/ws/monitoring` `cdsp_clipped` | green=0, red>0 | `Clip:0` / `Clip:14` |
| Xruns | `/ws/system` `pw_xruns` | green=0, yellow=1-5, red>5 | `Xr:0` / `Xr:3` |

Font: 9px, monospace (`var(--font-numeric)`), tabular-nums.

**Right zone — Mode + Alerts + ABORT (flex-shrink: 0, ~200px)**

```
45C  38%  | DJ | [ABORT]
```

| Element | Source | Color logic | Format |
|---------|--------|-------------|--------|
| Temperature | `/ws/system` `cpu_temp` | green<65, yellow 65-75, red>75 | `45C` |
| CPU usage | `/ws/system` `cpu_usage` | green<60, yellow 60-80, red>80 | `38%` |
| Mode badge | `/ws/system` or app state | blue background, white text | `DJ` / `LIVE` / `MEAS` |
| ABORT button | always rendered, visibility controlled | see Section 3 | `ABORT` |

### 2.3 Responsive Behavior

**Desktop/tablet (> 800px):** Full layout as described above. All three zones visible.

**Phone (< 600px):** Center zone collapses to show only xrun counter (most
critical single metric). Mini meters compress: PHYS IN group hidden (placeholder
channels), APP>DSP group hidden (usually silent). Only MAIN (2) + DSP>OUT (8) =
10 meters shown. The ABORT button grows to 48px minimum touch target.

**Phone (< 400px):** Mini meters show only MAIN (2) + DSP>OUT first 4 (SatL,
SatR, S1, S2) = 6 meters. This is the minimum viable set for live monitoring.

---

## 3. ABORT Button

### 3.1 Rationale

TK-160 Section 5 specifies "Abort is always one tap." Currently, the ABORT
button exists only in the Measure tab's wizard header (`mw-abort-btn`). If the
operator navigates to the Dashboard to check levels during a measurement, they
must navigate back to the Measure tab to abort. This defeats the purpose.

Moving ABORT to the persistent status bar makes it truly accessible from any
page. This is the correct implementation of the TK-160 requirement.

### 3.2 Visibility Rules

| System mode | ABORT visible | ABORT action |
|-------------|---------------|--------------|
| STANDBY (idle) | Hidden (not rendered) | n/a |
| MEASUREMENT (any active step) | Visible | Aborts measurement, mutes output, restores CamillaDSP config |
| TEST TOOL (signal playing) | Visible | Stops signal generator, mutes output |
| TEST TOOL (idle) | Hidden | n/a |

The ABORT button appears only when there is an active audio-producing operation
that needs an emergency stop. It is not shown during normal monitoring.

### 3.3 Styling

```css
.status-bar-abort {
    font-family: inherit;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 4px 12px;
    border: 2px solid var(--red);
    border-radius: 3px;
    background: rgba(229, 69, 58, 0.15);
    color: var(--red);
    cursor: pointer;
    min-width: 48px;
    min-height: 28px;
    /* Must be visible at arm's length */
}

.status-bar-abort:hover {
    background: rgba(229, 69, 58, 0.3);
}

.status-bar-abort:active {
    background: rgba(229, 69, 58, 0.5);
}
```

The button is styled identically to the existing `mw-abort-btn` but smaller to
fit within the 32px status bar height. No confirmation dialog -- single tap
aborts immediately (TK-160 design principle #5).

### 3.4 ABORT Button Coordination

When the ABORT button is pressed:

1. The status bar sends the abort command to the backend (same WebSocket message
   as the Measure tab's abort: `{"cmd": "abort"}`).
2. The backend handles the abort (stop audio, restore config, mute output).
3. The status bar receives the state update via WebSocket and hides the ABORT
   button once the operation is fully stopped.
4. If the operator is on the Measure tab, the wizard also receives the state
   update and transitions to the ABORTED screen.
5. If the operator is on any other tab, no navigation occurs. The ABORT button
   simply disappears, confirming the operation was stopped.

The Measure tab's existing `mw-abort-btn` is removed from the wizard header.
There is now exactly one ABORT button, in the status bar, visible from all tabs.
This eliminates the possibility of two ABORT buttons being visible simultaneously
(which would be confusing).

---

## 4. Measurement Progress in Status Bar

When a measurement is in progress, the center zone of the status bar shifts to
show measurement progress alongside system health. The system health indicators
compress; the measurement progress appears as an additional element.

### 4.1 Layout During Measurement

```
+------------------------------------------------------------------+
| [mini meters]  | DSP:Run Xr:0 | Gain Cal ch3 [====  ] 60% | [ABORT] |
+------------------------------------------------------------------+
```

| Element | Content | Example |
|---------|---------|---------|
| Step name | Current measurement phase | `Gain Cal ch3`, `Sweep 3/20 pos2`, `Generating...` |
| Progress bar | Inline progress | `[====  ] 60%` — 60px wide, same styling as `mw-progress-fill` |

The step name uses the same state labels as the measurement wizard:
- `Pre-flight` (during SETUP)
- `Gain Cal ch{N}` (during GAIN_CAL)
- `Sweep {n}/{total} pos{p}` (during MEASURING)
- `Generating...` (during FILTER_GEN)
- `Deploying...` (during DEPLOY)
- `Verifying...` (during VERIFY)

This allows the operator to monitor measurement progress while looking at the
Dashboard tab's full meters or the Test tool's spectrum display.

### 4.2 Data Source

The measurement progress data comes from the same `/ws/monitoring` endpoint that
already pushes measurement state to the Measure tab. The status bar JavaScript
listens to the same messages. No new backend endpoint is needed.

---

## 5. Data Flow

### 5.1 Existing WebSocket Endpoints (no changes needed)

| Endpoint | Data used by status bar | Update rate |
|----------|------------------------|-------------|
| `/ws/monitoring` | `capture_rms[0-7]`, `capture_peak[0-7]`, `playback_rms[0-7]`, `playback_peak[0-7]`, `cdsp_state`, `cdsp_clipped` | 10 Hz (levels), 2 Hz (DSP health) |
| `/ws/system` | `cpu_temp`, `cpu_usage`, `pw_quantum`, `pw_xruns` | 1 Hz |

The status bar subscribes to the same WebSocket connections that the Dashboard
and System views already use. The connections are managed by `app.js`
(`PiAudio.connectWebSocket`). The status bar registers as an additional consumer
of these messages -- it does not create new connections.

### 5.2 Implementation Architecture

The status bar is implemented as a new module (`statusbar.js`) that registers
itself as a global message consumer, not as a view. Unlike views (which have
`onShow`/`onHide` lifecycle), the status bar is always active.

```javascript
// statusbar.js — registers as a global consumer
PiAudio.registerGlobalConsumer("statusbar", {
    onMonitoring: function(data) { /* update mini meters + DSP health */ },
    onSystem: function(data) { /* update temp, CPU, quantum, xruns */ },
    onMeasurement: function(data) { /* update progress indicator */ }
});
```

This requires a small addition to `app.js`: the `connectWebSocket` message
handler calls registered global consumers in addition to the active view's
handler. This is a ~10 line change.

---

## 6. Mini Meter Rendering

### 6.1 Canvas vs DOM

Each group of mini meters is rendered on a single shared `<canvas>` element
(not individual canvases per meter). This minimizes DOM nodes and rendering
overhead. Four canvases total:

| Canvas | Width | Height | Channels |
|--------|-------|--------|----------|
| `mini-main` | 14px (2x6px + 2px gap) | 20px | ML, MR |
| `mini-app` | 29px (6x4px + 5x1px gap) | 20px | A3-A8 |
| `mini-dspout` | 39px (8x4px + 7x1px gap) | 20px | SatL-IR |
| `mini-physin` | 39px (8x4px + 7x1px gap) | 20px | Mic-P8 |

Total canvas pixels: ~2,400 pixels (trivial rendering cost).

### 6.2 Rendering Algorithm

Each meter bar is rendered as a filled rectangle from the bottom of the canvas.
The fill height is `dbToFraction(peak_db) * canvas_height`. The color is
determined by the peak level:

```
peak >= -3 dB   -> red   (#e5453a)
peak >= -12 dB  -> yellow (#e2c039)
peak < -12 dB   -> group base color
peak <= -60 dB  -> no fill (transparent)
```

The peak hold indicator is a 1px horizontal line at the peak hold position,
drawn in white (#ffffff) with 0.8 opacity.

Rendering runs on `requestAnimationFrame` only when the status bar is in the
viewport (always, since it is fixed). It piggybacks on the existing animation
loop in `dashboard.js` when the Dashboard tab is active, and runs its own
minimal RAF loop when other tabs are active.

### 6.3 Update Rate

Mini meters update at the same rate as the full meters: 10 Hz (from
`/ws/monitoring` levels data). The `requestAnimationFrame` loop interpolates
between updates for smooth visual decay. Peak hold decay: 1.5s. Clip latch: 3s.
These match the full meter behavior exactly.

---

## 7. Alert Indicators

### 7.1 Critical Alerts

When a critical condition is detected, the status bar provides a visual alert
that is visible from any tab:

| Condition | Indicator | Duration |
|-----------|-----------|----------|
| Clip detected (peak >= -0.5 dBFS) | Affected mini meter bar flashes red | 3s (matches CLIP_LATCH_MS) |
| Xrun detected (xrun count increases) | `Xr:N` text turns red, pulses once | 2s |
| CamillaDSP disconnected | `DSP:--` in red, mini meters freeze | Until reconnection |
| Temperature > 75C | Temperature text turns red, pulses | Until temperature drops |
| WebSocket disconnected | Connection dot in nav-bar turns red (existing behavior) | Until reconnection |

### 7.2 Alert Priority

If multiple alerts are active simultaneously, all are shown. The status bar
does not suppress alerts. The operator decides which to address first. This is
standard live audio monitoring behavior -- a mixing console does not hide
clip indicators because the temperature is also high.

---

## 8. HTML Structure

The status bar is added to `index.html` between the `<nav>` and the first
`.view` container:

```html
<!-- Persistent status bar (32px) — visible on ALL tabs -->
<div class="status-bar" id="status-bar">
    <!-- Left: mini level meters -->
    <div class="sb-meters">
        <canvas class="sb-meter-canvas" id="sb-mini-main"
                width="14" height="20" title="MAIN (ML, MR)"></canvas>
        <div class="sb-meter-sep"></div>
        <canvas class="sb-meter-canvas" id="sb-mini-app"
                width="29" height="20" title="APP>DSP (A3-A8)"></canvas>
        <div class="sb-meter-sep"></div>
        <canvas class="sb-meter-canvas" id="sb-mini-dspout"
                width="39" height="20" title="DSP>OUT (SatL-IR)"></canvas>
        <div class="sb-meter-sep"></div>
        <canvas class="sb-meter-canvas" id="sb-mini-physin"
                width="39" height="20" title="PHYS IN (Mic-P8)"></canvas>
    </div>

    <!-- Center: system health -->
    <div class="sb-health">
        <span class="sb-health-item">
            <span class="sb-label">DSP:</span><span class="sb-value" id="sb-dsp-state">--</span>
        </span>
        <span class="sb-health-item">
            <span class="sb-label">Q:</span><span class="sb-value" id="sb-quantum">--</span>
        </span>
        <span class="sb-health-item">
            <span class="sb-label">Clip:</span><span class="sb-value" id="sb-clip">0</span>
        </span>
        <span class="sb-health-item">
            <span class="sb-label">Xr:</span><span class="sb-value" id="sb-xruns">0</span>
        </span>
    </div>

    <!-- Center: measurement progress (hidden when not measuring) -->
    <div class="sb-measure-progress hidden" id="sb-measure-progress">
        <span class="sb-measure-step" id="sb-measure-step">--</span>
        <div class="sb-measure-bar">
            <div class="sb-measure-bar-fill" id="sb-measure-bar-fill"></div>
        </div>
        <span class="sb-measure-pct" id="sb-measure-pct">--%</span>
    </div>

    <!-- Right: temp, CPU, mode, ABORT -->
    <div class="sb-right">
        <span class="sb-value sb-temp" id="sb-temp">--</span>
        <span class="sb-value sb-cpu" id="sb-cpu">--</span>
        <div class="sb-sep"></div>
        <span class="sb-mode-badge" id="sb-mode">--</span>
        <button class="sb-abort-btn hidden" id="sb-abort-btn">ABORT</button>
    </div>
</div>
```

---

## 9. CSS

```css
/* -- Persistent status bar (32px) ---------------------------------------- */

:root {
    --status-bar-height: 32px;
}

.status-bar {
    display: flex;
    align-items: center;
    height: var(--status-bar-height);
    padding: 0 8px;
    background: var(--bg-panel);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    gap: 8px;
    font-size: 9px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    font-family: var(--font-numeric);
}

/* View container must account for status bar */
.view {
    height: calc(100vh - var(--nav-height) - var(--status-bar-height));
}

/* -- Mini meters --------------------------------------------------------- */

.sb-meters {
    display: flex;
    align-items: center;
    gap: 2px;
    flex-shrink: 0;
}

.sb-meter-canvas {
    display: block;
    image-rendering: pixelated;
}

.sb-meter-sep {
    width: 1px;
    height: 12px;
    background: var(--border);
    margin: 0 2px;
}

/* -- System health (center) ---------------------------------------------- */

.sb-health {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
}

.sb-health-item {
    display: flex;
    align-items: center;
    gap: 2px;
}

.sb-label {
    color: var(--text-dim);
}

.sb-value {
    color: var(--text);
}

/* -- Measurement progress ------------------------------------------------ */

.sb-measure-progress {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
    padding: 0 8px;
    border-left: 1px solid var(--border);
}

.sb-measure-step {
    font-size: 9px;
    font-weight: 700;
    color: var(--yellow);
    white-space: nowrap;
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
}

.sb-measure-bar {
    width: 60px;
    height: 8px;
    background: var(--bg-bar);
    border-radius: 2px;
    overflow: hidden;
}

.sb-measure-bar-fill {
    height: 100%;
    background: var(--cyan);
    border-radius: 2px;
    transition: width 0.4s ease;
}

.sb-measure-pct {
    font-size: 8px;
    color: var(--text-dim);
    width: 24px;
    text-align: right;
}

/* -- Right zone ---------------------------------------------------------- */

.sb-right {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-left: auto;
    flex-shrink: 0;
}

.sb-temp {
    font-size: 9px;
}

.sb-cpu {
    font-size: 9px;
}

.sb-sep {
    width: 1px;
    height: 12px;
    background: var(--border);
}

.sb-mode-badge {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background: var(--blue);
    color: #fff;
    padding: 1px 6px;
    border-radius: 8px;
    line-height: 1.4;
}

/* -- ABORT button -------------------------------------------------------- */

.sb-abort-btn {
    font-family: inherit;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 4px 12px;
    border: 2px solid var(--red);
    border-radius: 3px;
    background: rgba(229, 69, 58, 0.15);
    color: var(--red);
    cursor: pointer;
    min-width: 48px;
    min-height: 28px;
    transition: background 0.15s;
}

.sb-abort-btn:hover {
    background: rgba(229, 69, 58, 0.3);
}

.sb-abort-btn:active {
    background: rgba(229, 69, 58, 0.5);
}

/* -- Responsive ---------------------------------------------------------- */

@media (max-width: 600px) {
    /* Hide APP>DSP and PHYS IN mini meters on phone */
    #sb-mini-app,
    #sb-mini-physin,
    .sb-meters .sb-meter-sep:nth-child(2),
    .sb-meters .sb-meter-sep:nth-child(6) {
        display: none;
    }

    /* Compress center zone to xruns only */
    .sb-health-item:not(:last-child) {
        display: none;
    }

    .sb-abort-btn {
        min-height: 40px;
        min-width: 56px;
        font-size: 11px;
    }

    .sb-measure-step {
        max-width: 80px;
    }
}

@media (max-width: 400px) {
    /* Ultra-compact: MAIN + first 4 DSP>OUT only */
    .sb-meters {
        max-width: 80px;
        overflow: hidden;
    }

    .sb-measure-progress {
        display: none;
    }
}
```

---

## 10. JavaScript Module (`statusbar.js`)

### 10.1 Module Structure

```javascript
/**
 * Persistent status bar module.
 *
 * Unlike view modules, this runs on all tabs. It registers as a global
 * consumer of WebSocket data rather than using view lifecycle hooks.
 */
"use strict";

(function () {
    // Canvas contexts for mini meters
    var canvases = {
        main: null,    // 2 channels
        app: null,     // 6 channels
        dspout: null,  // 8 channels
        physin: null   // 8 channels
    };

    // Per-channel state (mirrors dashboard.js structure)
    var captureState = [];  // 8 channels
    var playbackState = []; // 8 channels
    var physinState = [];   // 8 channels

    // Group rendering configs
    var groups = {
        main:   { canvas: "sb-mini-main",   channels: [0, 1], state: "capture",  barW: 6, gap: 2, color: "#8a94a4" },
        app:    { canvas: "sb-mini-app",    channels: [2, 3, 4, 5, 6, 7], state: "capture",  barW: 4, gap: 1, color: "#00838f" },
        dspout: { canvas: "sb-mini-dspout", channels: [0, 1, 2, 3, 4, 5, 6, 7], state: "playback", barW: 4, gap: 1, color: "#2e7d32" },
        physin: { canvas: "sb-mini-physin", channels: [0, 1, 2, 3, 4, 5, 6, 7], state: "physin",   barW: 4, gap: 1, color: "#c17900" }
    };

    function init() { /* get canvas contexts, init state arrays */ }
    function onMonitoring(data) { /* update meter state from levels data */ }
    function onSystem(data) { /* update temp, CPU, quantum, xruns */ }
    function onMeasurement(data) { /* update progress bar and step label */ }
    function renderMeters() { /* RAF loop: draw all mini meter canvases */ }

    PiAudio.registerGlobalConsumer("statusbar", {
        init: init,
        onMonitoring: onMonitoring,
        onSystem: onSystem,
        onMeasurement: onMeasurement
    });
})();
```

### 10.2 Required Change to `app.js`

The `PiAudio` module needs a new `registerGlobalConsumer` API and a dispatch
mechanism. Currently, WebSocket messages are dispatched only to the active view.
The change:

```javascript
var globalConsumers = {};  // { name: { onMonitoring, onSystem, onMeasurement } }

function registerGlobalConsumer(name, consumer) {
    globalConsumers[name] = consumer;
    if (initialized && consumer.init) consumer.init();
}

// In connectWebSocket's onMessage handler, after dispatching to the active view:
for (var key in globalConsumers) {
    var gc = globalConsumers[key];
    if (data.type === "levels" && gc.onMonitoring) gc.onMonitoring(data);
    if (data.type === "system_health" && gc.onSystem) gc.onSystem(data);
    if (data.type === "measurement_state" && gc.onMeasurement) gc.onMeasurement(data);
}
```

This is approximately 15 lines of code added to `app.js`.

---

## 11. Interaction with Existing Health Bar

The current Dashboard view has a health bar (`health-bar`, 20px) that shows
DSP load, buffer level, clip count, xruns, CPU, temp, mem, and uptime. This
health bar is ONLY visible on the Dashboard tab (it is inside `#view-dashboard`).

With the persistent status bar in place, the Dashboard health bar becomes
partially redundant. The recommended approach:

**Keep the Dashboard health bar.** It shows more detail (DSP load gauge, buffer
level, memory, uptime) than the status bar's compressed view. The status bar is
a glanceable summary; the Dashboard health bar is the detailed view. No
information is lost, and the operator has two levels of detail available.

The Dashboard view height decreases by 32px (the status bar height). This is
acceptable because the current layout already has generous vertical space in the
spectrum zone (min-height: 200px). The spectrum zone absorbs the 32px reduction.

---

## 12. Migration of Existing Nav-Bar Elements

The current nav-bar (28px) contains:
- Mode badge (`#mode-badge`)
- Temperature (`#nav-temp`)
- Connection dot (`#conn-dot`)

With the status bar providing mode badge and temperature, these become redundant
in the nav-bar. The recommended migration:

| Element | Current location | New location | Notes |
|---------|-----------------|--------------|-------|
| Mode badge | nav-bar right | status bar right (`#sb-mode`) | Remove from nav-bar |
| Temperature | nav-bar right | status bar right (`#sb-temp`) | Remove from nav-bar |
| Connection dot | nav-bar right | nav-bar right (KEEP) | Remains as the simplest "connected/disconnected" indicator |

The connection dot stays in the nav-bar because it is the first thing the
operator looks for when the page loads ("am I connected?"). It occupies 8px
and does not need to move.

---

## 13. Implementation Checklist

1. [ ] Add `--status-bar-height: 32px` to `:root` CSS variables
2. [ ] Add status bar HTML between `</nav>` and first `.view` in `index.html`
3. [ ] Update `.view` height calc to subtract status bar height
4. [ ] Create `statusbar.js` module
5. [ ] Add `registerGlobalConsumer` API to `app.js`
6. [ ] Wire status bar as global consumer of `/ws/monitoring` and `/ws/system`
7. [ ] Implement mini meter canvas rendering (4 canvases, RAF loop)
8. [ ] Implement system health text updates
9. [ ] Implement ABORT button with show/hide logic tied to measurement state
10. [ ] Remove mode badge and temperature from nav-bar right zone
11. [ ] Remove `mw-abort-btn` from Measure tab wizard header
12. [ ] Wire ABORT button to send abort command via WebSocket
13. [ ] Add responsive breakpoints for phone/tablet
14. [ ] Add `<script src="/static/js/statusbar.js"></script>` to index.html
15. [ ] Test: verify status bar visible on all tabs
16. [ ] Test: verify mini meters track levels correctly against full meters
17. [ ] Test: verify ABORT button visible during measurement, hidden otherwise
18. [ ] Test: verify ABORT from non-Measure tab stops the measurement
19. [ ] Test: verify responsive behavior at 600px and 400px breakpoints

---

## 14. Resource Budget

| Component | CPU (Pi) | Bandwidth | Notes |
|-----------|----------|-----------|-------|
| Mini meter rendering | < 0.01% | 0 | Trivial canvas draws, ~2400 pixels total |
| Status bar text updates | < 0.005% | 0 | DOM text node updates, 1-10 Hz |
| Additional WebSocket messages | 0 | 0 | Consumes existing streams, no new subscriptions |
| **Total additional load** | **< 0.015%** | **0** | Negligible |

The status bar adds zero network traffic and negligible CPU. It is purely a
client-side rendering change that consumes data already being streamed.
