# Demo Smoke Test Script

**Purpose:** Manual browser walkthrough of the mugge web UI running on local-demo,
validating all demo-critical paths before a live stage presentation.

**Environment:** `nix run .#local-demo` on the dev machine (not the Pi).
Open `http://localhost:8080` in a browser.

**Notation:**
- CLICK = mouse click on the named element
- VERIFY = visual assertion (must be true to pass)
- WAIT = pause for the stated condition
- SKIP-IF = conditional — skip the step if the condition applies

---

## Pre-conditions

1. `nix run .#local-demo` running and showing "Local demo stack is running!"
2. Console shows ~26 links active
3. No ERROR lines in console output (warnings about UMIK-1 optional links are OK)

---

## T-SMOKE-1: Page Load and Status Bar

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Navigate to `http://localhost:8080` | Page loads without JS errors in console |
| 1.2 | VERIFY nav bar | Logo (SVG), title "Pi Audio", 7 tabs visible: Dashboard, System, Graph, Config, Measure, Test, MIDI |
| 1.3 | VERIFY connection dot (`#conn-dot`) | Green (class `c-safe`) — WebSocket connected |
| 1.4 | VERIFY status bar | All items visible: mini meter canvases, DSP, Clip, Xr, Q, Rate, Links, FIFO, CPU gauge, Temp gauge, MUTE button, mode badge |
| 1.5 | VERIFY status bar values populate | Within 3 seconds: CPU shows a percentage, Temp shows degrees, Q shows a number (e.g. 256 or 1024), mode badge shows "MEASUREMENT" |
| 1.6 | VERIFY no reconnect overlay | `#reconnect-overlay` is NOT visible |
| 1.7 | VERIFY no JS console errors | Open DevTools Console — no red errors |

**Pass criteria:** All 7 items green.

---

## T-SMOKE-2: Dashboard Tab

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Dashboard tab is active by default | `#view-dashboard` visible |
| 2.2 | VERIFY meter groups exist | Four groups visible with labels: MAIN, APP>CONV, CONV>OUT, PHYS IN |
| 2.3 | VERIFY meters are animating | At least one meter bar is non-zero (signal-gen plays 440 Hz sine at startup) |
| 2.4 | VERIFY spectrum canvas | `#spectrum-canvas` is rendered, shows frequency content (a peak near 440 Hz from the sine wave) |
| 2.5 | VERIFY right panel — SPL | `#spl-value` shows a number or "--" (depends on UMIK-1 presence) |
| 2.6 | VERIFY right panel — LUFS | ST, INT, MOM sections visible with values or "--" |
| 2.7 | VERIFY right panel — THERMAL | `#thermal-panel` visible with header "THERMAL" |
| 2.8 | Change FFT size | CLICK the spectrum FFT dropdown `#spectrum-fft-size`, select "Analysis (8192)". Spectrum re-renders with finer resolution. |
| 2.9 | VERIFY spectrum responds | Spectrum display updates within 1 second of FFT change |

**Pass criteria:** All meters animate, spectrum renders, layout is not broken.

---

## T-SMOKE-3: System Tab

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | CLICK "System" tab | `#view-system` becomes visible, `#view-dashboard` hides |
| 3.2 | VERIFY header strip | Mode, Quantum, Sample Rate, Temperature — all show values (not "--") within 3 seconds |
| 3.3 | VERIFY CPU section | `#sys-cpu-bars` shows per-core bar charts |
| 3.4 | VERIFY Filter Chain section | State, Links, Health show values (not all "--") |
| 3.5 | VERIFY Scheduling section | PipeWire, GraphMgr show scheduling info |
| 3.6 | VERIFY Processes section | Mixxx/Reaper may show "--" (not running in local-demo). GraphMgr and PipeWire should show running |
| 3.7 | VERIFY Events section | EVENTS header visible with W, E filter buttons and CLEAR button |

**Pass criteria:** System health data populates. No layout overflow.

---

## T-SMOKE-4: Graph Tab

| Step | Action | Expected |
|------|--------|----------|
| 4.1 | CLICK "Graph" tab | `#view-graph` becomes visible |
| 4.2 | WAIT 3 seconds | SVG topology renders nodes and links |
| 4.3 | VERIFY nodes visible | At minimum: convolver node, USBStreamer sink, signal-gen node. Node rectangles with labels. |
| 4.4 | VERIFY links visible | Lines connecting nodes (representing pw-link connections) |
| 4.5 | CLICK "FIT" button (`#gv-fit-btn`) | Graph zooms to fit all nodes in view |
| 4.6 | Mouse drag on SVG | Graph pans (viewport moves) |
| 4.7 | Mouse wheel on SVG | Graph zooms in/out |

**Pass criteria:** Graph renders with nodes and links. Pan/zoom functional.

---

## T-SMOKE-5: Config Tab — Gains and Quantum

| Step | Action | Expected |
|------|--------|----------|
| 5.1 | CLICK "Config" tab | `#view-config` becomes visible |
| 5.2 | VERIFY Channel Gains section | `#cfg-gain-list` shows gain sliders/inputs for channels. APPLY and RESET buttons visible (may be disabled). |
| 5.3 | VERIFY Quantum section | Three buttons: 256, 512, 1024. One is highlighted as active. Latency display shows "Latency: X ms". |
| 5.4 | VERIFY Filter Chain section | Node, ID, Description show values |

**Pass criteria:** Config controls render correctly.

---

## T-SMOKE-6: Config Tab — Speaker Profiles

| Step | Action | Expected |
|------|--------|----------|
| 6.1 | Scroll down to "SPEAKER PROFILES" section | `#spk-profile-list` visible |
| 6.2 | VERIFY profile list loads | At least "bose-home" and "bose-home-chn50p" appear (seeded from repo configs) |
| 6.3 | CLICK "bose-home" in the profile list | Right panel shows profile detail: name, topology, crossover frequency/slope, speakers list with channel assignments |
| 6.4 | VERIFY detail content | Name: "bose-home". Topology shown. Crossover section shows frequency and slope. Speakers section shows speaker chips with identity/channel/role. |
| 6.5 | VERIFY identity list loads | `#spk-identity-list` shows identities (e.g. "bose-jewel-double-cube", "bose-ps28-iii-sub") |
| 6.6 | CLICK an identity in the list | Right panel shows identity detail: name, type, impedance, max boost, HPF, sensitivity |
| 6.7 | CLICK "+ NEW PROFILE" button | Form appears with fields: Name, Topology dropdown, Description, Crossover, Speakers area with "+ ADD SPEAKER", Monitoring, Gain Staging, Filter Settings |
| 6.8 | CLICK "CANCEL" | Form closes, returns to detail or empty panel |

**Pass criteria:** Profile and identity CRUD UI renders. List loads from seeded data.

---

## T-SMOKE-7: Config Tab — FIR Filter Generation

| Step | Action | Expected |
|------|--------|----------|
| 7.1 | Scroll to "FIR FILTER GENERATION" section | `#cfg-fir-gen` visible |
| 7.2 | VERIFY profile dropdown | `#fir-profile` shows loaded profiles (not "Loading...") |
| 7.3 | Select "bose-home" profile | Dropdown changes to "bose-home" |
| 7.4 | VERIFY mode toggle | "Crossover Only" selected by default. "Crossover + Correction" also available. |
| 7.5 | VERIFY Target SPL presets | Four buttons: Quiet 70, Normal 85 (active), Loud 95, Full 105 |
| 7.6 | CLICK "GENERATE FILTERS" (`#fir-generate-btn`) | Spinner appears. Status updates. After a few seconds, results panel shows: generation summary, per-channel cards with filter details, D-009 verification results. |
| 7.7 | VERIFY results | `#fir-results-content` visible. Channel cards show filter info. All D-009 checks pass (green). |
| 7.8 | VERIFY deploy section | "DEPLOY TO PI" button (`#fir-deploy-btn`) becomes enabled after generation completes. Active filters display shows current state. |

**Pass criteria:** Filter generation runs to completion. Results display correctly.

---

## T-SMOKE-8: Config Tab — Hardware

| Step | Action | Expected |
|------|--------|----------|
| 8.1 | Scroll to "AMPLIFIERS" and "DACs" sections | `#cfg-hardware` visible |
| 8.2 | VERIFY amplifier list | Shows seeded amplifier configs (if any) or "No amplifiers found." |
| 8.3 | VERIFY DAC list | Shows seeded DAC configs (if any) or "No dacs found." |
| 8.4 | CLICK "+ NEW AMPLIFIER" | Form appears with amplifier configuration fields |
| 8.5 | CLICK "CANCEL" | Form closes |

**Pass criteria:** Hardware config section renders without errors.

---

## T-SMOKE-9: Measure Tab — Idle State

| Step | Action | Expected |
|------|--------|----------|
| 9.1 | CLICK "Measure" tab | `#view-measure` becomes visible |
| 9.2 | VERIFY wizard header | "MEASUREMENT" title, state badge shows "IDLE", progress bar with PRE/SWEEP/POST segments (all inactive) |
| 9.3 | VERIFY idle screen | `#mw-idle` visible. "ROOM MEASUREMENT" title. "START NEW MEASUREMENT" hero button visible and enabled. |
| 9.4 | VERIFY abort button hidden | `#mw-abort-btn` has class "hidden" (not visible in idle state) |

**Pass criteria:** Measurement wizard loads in idle state.

---

## T-SMOKE-10: Measure Tab — Start Measurement Flow

| Step | Action | Expected |
|------|--------|----------|
| 10.1 | CLICK "START NEW MEASUREMENT" (`#mw-start-btn`) | Screen transitions from idle. Either: (a) setup screen appears with profile selector, position count, pre-flight checks, OR (b) session starts directly showing gain_cal screen. |
| 10.2 | VERIFY setup screen (if shown) | `#mw-setup` visible. Profile dropdown populated. Positions input defaults to 5. Pre-flight checks section shows 4 items: UMIK-1, speaker profile, GraphManager mode, amplifiers. |
| 10.3 | VERIFY pre-flight checks | `#rc-pf-mic` shows pass/fail indicator. `#rc-pf-gm` should show pass (GM is in measurement mode in local-demo). `#rc-pf-profile` shows status based on profile selection. |
| 10.4 | VERIFY state badge updates | `#mw-state-text` changes from "IDLE" to current state (e.g. "SETUP" or "GAIN CAL") |
| 10.5 | VERIFY progress bar updates | PRE segment becomes active (highlighted) |
| 10.6 | VERIFY abort button appears | `#mw-abort-btn` becomes visible during active phases |

**Pass criteria:** Measurement session starts. State transitions work. Pre-flight checks render.

---

## T-SMOKE-11: Measure Tab — Abort Flow

| Step | Action | Expected |
|------|--------|----------|
| 11.1 | CLICK "ABORT" (`#mw-abort-btn`) during any active phase | Screen transitions to aborted state |
| 11.2 | VERIFY aborted screen | `#mw-aborted` visible. Title shows "MEASUREMENT ABORTED" in warning color. Abort reason shown. "RETURN" button visible. |
| 11.3 | CLICK "RETURN" button | Returns to idle screen. Start button re-enabled. Progress bar reset. |

**Pass criteria:** Abort flow works cleanly. Return to idle is clean.

---

## T-SMOKE-12: Test Tab — Signal Generator

| Step | Action | Expected |
|------|--------|----------|
| 12.1 | CLICK "Test" tab | `#view-test` becomes visible |
| 12.2 | VERIFY signal type buttons | 5 buttons visible: Sine (active), White, Pink, Sweep, File |
| 12.3 | VERIFY frequency slider | `#tt-freq-slider` visible, value shows "1000 Hz" |
| 12.4 | VERIFY channel grid | 8 channel buttons: 1 SatL, 2 SatR, 3 Sub1, 4 Sub2, 5 EngL, 6 EngR, 7 IEML, 8 IEMR |
| 12.5 | VERIFY level slider | `#tt-level-slider` visible, value shows "-40.0 dBFS" |
| 12.6 | VERIFY signal generator status | `#tt-siggen-state` shows "connected" or "stopped" or "playing" (not "checking...") within 3 seconds |
| 12.7 | VERIFY spectrum analyzer | `#tt-spectrum-canvas` renders. If signal-gen is playing, shows frequency peak. |
| 12.8 | VERIFY SPL section | SPL (A), SPL (C), SPL peak rows visible. May show "--" if no mic. |
| 12.9 | CLICK channel "1 SatL" | Button highlights. Channel selected. |
| 12.10 | VERIFY PLAY button enables | `#tt-play-btn` becomes enabled when channel is selected and siggen is connected |
| 12.11 | CLICK "PLAY" | Confirmation dialog appears (first play per session triggers safety confirmation). Accept it. Signal starts. Status changes to "playing". |
| 12.12 | VERIFY spectrum shows signal | Test tab spectrum shows the signal being played (sine peak at the slider frequency) |
| 12.13 | CLICK "PK HOLD" (`#tt-peak-hold`) | Button toggles active state. Peak hold overlay appears on spectrum. "RESET" button appears. |
| 12.14 | CLICK "STOP" | Signal stops. Status changes to "stopped". |

**Pass criteria:** Signal generator connects, plays, stops. Spectrum renders signal.

---

## T-SMOKE-13: Test Tab — Sweep Mode

| Step | Action | Expected |
|------|--------|----------|
| 13.1 | CLICK "Sweep" signal type button | Sweep button becomes active. Sweep end frequency section appears (`#tt-sweep-end-section`). Frequency title changes to include sweep context. |
| 13.2 | VERIFY sweep end slider | `#tt-sweep-end-slider` visible with value "20000 Hz" |
| 13.3 | Select a channel and CLICK PLAY | Signal sweeps from start to end frequency. Spectrum shows moving peak. |
| 13.4 | CLICK "STOP" | Sweep stops |

**Pass criteria:** Sweep mode UI toggles correctly and sweep plays.

---

## T-SMOKE-14: Test Tab — Target Curve Overlay

| Step | Action | Expected |
|------|--------|----------|
| 14.1 | VERIFY target curve row | `#tt-target-curve-row` visible with TARGET button, curve selector (Flat/Harman/PA), phon input |
| 14.2 | CLICK "TARGET" (`#tt-target-toggle`) | Target curve overlay toggles on spectrum. A reference line appears on the spectrum canvas. |
| 14.3 | Change curve selector to "PA" | Target curve shape changes on the spectrum |
| 14.4 | Enter "70" in phon input | Target curve adjusts for 70 phon equal-loudness compensation |

**Pass criteria:** Target curve overlay renders and responds to selection changes.

---

## T-SMOKE-15: MIDI Tab

| Step | Action | Expected |
|------|--------|----------|
| 15.1 | CLICK "MIDI" tab | `#view-midi` becomes visible |
| 15.2 | VERIFY stub content | Shows "MIDI" title and "Coming in Stage 2" message |

**Pass criteria:** Tab renders without error.

---

## T-SMOKE-16: Tab Switching Resilience

| Step | Action | Expected |
|------|--------|----------|
| 16.1 | Rapidly click through all 7 tabs in sequence | Each tab shows/hides correctly. No flash of wrong content. No JS errors. |
| 16.2 | Return to Dashboard | Meters resume animation. Spectrum resumes rendering. Status bar values continue updating. |
| 16.3 | VERIFY status bar persists | Status bar remains visible and updating throughout all tab switches |

**Pass criteria:** Tab switching is clean. No state corruption.

---

## T-SMOKE-17: MUTE Button

| Step | Action | Expected |
|------|--------|----------|
| 17.1 | CLICK "MUTE" button (`#sb-panic-btn`) | Button visual changes (e.g. highlighted/pressed state). Mute command sent. Meters should drop to zero or near-zero if audio was flowing. |
| 17.2 | CLICK "MUTE" again (toggle) | Audio resumes. Meters show signal levels again. |

**Pass criteria:** Panic mute toggles audio output.

---

## T-SMOKE-18: Connection Loss Recovery

| Step | Action | Expected |
|------|--------|----------|
| 18.1 | In the local-demo terminal, press Ctrl+Z to suspend the web-ui process | Connection lost. `#reconnect-overlay` appears with "Connection lost" and "Reconnecting..." messages. Connection dot turns red/grey. |
| 18.2 | In terminal, run `fg` to resume the process | WebSocket reconnects automatically. Overlay disappears. Connection dot turns green. Status bar resumes updating. |

**Pass criteria:** Reconnection overlay appears and clears. Auto-reconnect works.

---

## T-SMOKE-19: Browser Resize

| Step | Action | Expected |
|------|--------|----------|
| 19.1 | With Dashboard active, resize browser to narrow width (~800px) | Layout adapts. Meters may compress. Some status bar items with class `sb-collapse-narrow` may hide. No horizontal scrollbar on main content. |
| 19.2 | Resize to very narrow (~400px, mobile-ish) | Layout degrades gracefully — no overlapping elements, no clipped text that hides critical info. |
| 19.3 | Resize back to full width | Layout returns to normal |

**Pass criteria:** No layout breakage at common widths.

---

## Summary Checklist

| Test | Description | Pass? |
|------|-------------|-------|
| T-SMOKE-1 | Page load + status bar | |
| T-SMOKE-2 | Dashboard (meters, spectrum) | |
| T-SMOKE-3 | System tab | |
| T-SMOKE-4 | Graph tab (topology, pan/zoom) | |
| T-SMOKE-5 | Config: gains + quantum | |
| T-SMOKE-6 | Config: speaker profiles | |
| T-SMOKE-7 | Config: FIR filter generation | |
| T-SMOKE-8 | Config: hardware | |
| T-SMOKE-9 | Measure: idle state | |
| T-SMOKE-10 | Measure: start flow | |
| T-SMOKE-11 | Measure: abort flow | |
| T-SMOKE-12 | Test: signal generator | |
| T-SMOKE-13 | Test: sweep mode | |
| T-SMOKE-14 | Test: target curve overlay | |
| T-SMOKE-15 | MIDI tab | |
| T-SMOKE-16 | Tab switching resilience | |
| T-SMOKE-17 | MUTE button | |
| T-SMOKE-18 | Connection loss recovery | |
| T-SMOKE-19 | Browser resize | |

**Total: 19 tests, ~85 individual verification steps.**

Estimated execution time: 15-20 minutes for a thorough pass.

---

## Known Limitations in Local-Demo

- **No real audio hardware:** Meters show simulated levels from null sinks.
  UMIK-1 SPL values will show "--" unless a real UMIK-1 is USB-connected.
- **GM in measurement mode only:** Mode badge shows "MEASUREMENT".
  DJ/Live mode transitions not testable in local-demo.
- **Reconciler workaround:** Links are created by manual `pw-link`, not
  by GM's reconciler. Graph tab shows the manual links.
- **No PipeWire restart:** The "RELOAD PIPEWIRE" button in deploy will
  restart the local-demo PipeWire, which may require restarting the full
  local-demo stack.
