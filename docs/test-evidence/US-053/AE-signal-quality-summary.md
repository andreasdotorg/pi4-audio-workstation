# US-053 Signal Quality Summary — AE Sign-off Evidence

**Prepared by:** worker-measure
**Date:** 2026-03-22
**Story:** US-053 (Manual Test Tool Page)
**DoD item:** #7 — AE sign-off: signal quality and SPL readout accuracy

---

## 1. Signal Generation Architecture

The test tool page does NOT generate audio itself (AC-6.5 verified by code
review — no Web Audio API, no AudioContext in test.js). All audio is generated
by `pi4audio-signal-gen`, a dedicated Rust process running on the PipeWire
data thread at SCHED_FIFO priority.

### Signal Path
```
Browser UI  --[/ws/siggen JSON]--> FastAPI proxy --[TCP RPC]--> signal-gen (Rust)
                                                                    |
                                                              PipeWire graph
                                                                    |
                                                              USBStreamer --> ADA8200 --> Speakers
```

The web UI sends RPC commands; the signal generator produces the actual audio
samples in its PipeWire process callback.

---

## 2. Signal Types and Quality

### 2.1 Sine Generator (generator.rs)
- **Implementation:** Phase-continuous sine using f64 phase accumulator.
- **Phase continuity:** Frequency changes update `phase_increment` without
  resetting `phase` — no discontinuity on frequency change (phase-continuous
  transition per UX spec Section 5.2).
- **Precision:** f64 phase accumulator prevents phase drift over long
  playback durations. Output samples are f32.
- **Frequency range:** 20 Hz to 20,000 Hz (validated by RPC, AE-MF-2).

### 2.2 White Noise Generator
- **Implementation:** `Xoshiro256PlusPlus` PRNG (rand_xoshiro crate).
- **Quality:** Statistically flat spectrum. Xoshiro256++ has good spectral
  properties — no periodic artifacts within measurement-relevant durations.
- **RT-safe:** No allocation, no syscalls. PRNG state is stack-local.

### 2.3 Pink Noise Generator (1/f)
- **Implementation:** Voss-McCartney algorithm (octave-band summation).
- **Quality:** -3 dB/octave rolloff. Standard for SPL measurement per
  IEC 61672 practice.

### 2.4 Log Sweep Generator
- **Implementation:** Instantaneous frequency computed as exponential chirp.
- **Frequency range:** Configurable start/end (default 20 Hz to 20,000 Hz).
- **Duration:** Linked to burst duration setting (1-60s).
- **Validation:** `sweep_end` must be > `freq` (rpc.rs test:
  `sweep_end_must_be_greater_than_freq`).

### 2.5 Silence Generator
- **Implementation:** `buffer.fill(0.0)` — mathematically zero output.

---

## 3. Level Accuracy

### dBFS to Linear Conversion
Signal generator converts dBFS to linear amplitude:
```rust
let max_level_linear = 10.0f64.powf(max_level_dbfs / 20.0) as f32;
```

Unit tests verify conversion accuracy:
- `-20 dBFS` -> `0.1` linear (error < 1e-6)
- `-0.5 dBFS` -> `~0.9441` linear (error < 1e-5)
- `-120 dBFS` -> `1e-6` linear (error < 1e-10)

### Level Application
The generator's `generate()` method receives `level_linear` as a parameter.
Each sample is scaled by this value. After generation, the safety hard clip
(safety.rs) ensures no sample exceeds the immutable cap.

### Level Transitions
Level changes use a 20ms cosine fade ramp (ramp.rs):
- Cosine shape: `0.5 * (1 - cos(pi * t))` — zero derivative at both endpoints.
- No discontinuity in signal or first derivative.
- Duration: configurable via `--ramp-ms` (default 20ms = 960 samples at 48 kHz).
- Prevents audible clicks during level adjustment.

---

## 4. Channel Routing

### Channel Mapping
Channels 1-8 map to the CLAUDE.md channel assignment table:
| Ch | Output | Label |
|----|--------|-------|
| 1 | Left wideband speaker | SatL |
| 2 | Right wideband speaker | SatR |
| 3 | Subwoofer 1 | Sub1 |
| 4 | Subwoofer 2 | Sub2 |
| 5 | Engineer headphone L | EngL |
| 6 | Engineer headphone R | EngR |
| 7 | Singer IEM L | IEML |
| 8 | Singer IEM R | IEMR |

### Channel Selection
- Channels encoded as bitmask (command.rs): channel N -> bit (N-1).
- Only active channels receive signal; others receive silence (0.0).
- Channel changes use sequential fade: 20ms fade-out on old channel, 20ms
  fade-in on new channel (AE-SF-3 per ramp.rs).
- Multi-channel simultaneous output supported (multi-select mode in UI).

### Unit Test Coverage
- `channels_1_3_5_encode_to_bitmask`: verifies [1,3,5] -> 0b00010101
- `channels_all_eight_encode_to_0xff`: verifies [1-8] -> 0xFF
- `bitmask_roundtrip`: verifies encode/decode cycle preserves channel list
- `channel_array_to_bitmask_in_play`: verifies play command carries correct
  bitmask through RPC -> command queue

---

## 5. Spectrum Display

### FFT Pipeline (test.js, client-side)
- **Window function:** Blackman-Harris (4-term), matching Dashboard spectrum.
- **FFT size:** 2048 points (same as Dashboard).
- **Sample rate:** 48,000 Hz.
- **Frequency resolution:** 48000 / 2048 = 23.4 Hz per bin.
- **Display range:** 20 Hz to 20,000 Hz (logarithmic x-axis).
  - Note: This is wider than Dashboard (30 Hz to 20 kHz) — intentional for
    sub-bass debugging.
- **dB range:** -80 dB to 0 dB (wider than Dashboard's -60 to 0 dB).
- **Smoothing:** Exponential moving average with alpha = 0.3.

### PCM Source Selection
The spectrum analyzer can display:
- **UMIK-1** (USB capture) — for acoustic measurement
- **Main L+R** (monitor taps) — for program bus monitoring
- **Sub sum** (monitor tap) — for sub-bass monitoring

Source selection triggers WebSocket reconnection to `/ws/pcm/{source}`.

### E2E Test Evidence
`test_capture_spectrum.py` (11 tests, all passing):
- Canvas visibility and 2D context validation
- Non-blank canvas after mock PCM data flows (screenshot: `pcm3-spectrum-with-data.png`)
- Source selector population from `/api/v1/pcm-sources`
- WebSocket connection on tab show
- Source switching reconnection
- Tab lifecycle (stop on hide, restart on show)
- No-mic overlay hidden when connected
- REST endpoint returns valid source list

---

## 6. SPL Readout

### Implementation (test.js DOM elements)
Three SPL readout elements:
- `#tt-spl-a` — SPL (A-weighted)
- `#tt-spl-c` — SPL (C-weighted)
- `#tt-spl-peak` — SPL peak (C-weighted, 3s peak hold)

### Uncalibrated Banner
The `#tt-spl-uncal` banner ("SPL UNCALIBRATED -- values are approximate") is
shown by default. Per UX spec Section 4.3, this remains visible until:
- UMIK-1 calibration file is loaded AND
- Calibration chain is verified against a reference

This is appropriate given TK-231 (SPL computation) is still open.

### UMIK-1 Hot-Plug Support
The signal generator includes a PipeWire registry watcher (registry.rs) that:
- Monitors for device connect/disconnect events matching `--device-watch`
  pattern (default: "UMIK-1")
- Sends `capture_device_connected` / `capture_device_disconnected` events
  to all connected RPC clients
- The web UI updates mic status indicator accordingly

Unit test coverage in registry.rs (10+ tests):
- `capture_connection_state_initially_disconnected`
- `capture_connection_state_connect_disconnect`
- Event JSON format verification

---

## 7. Remaining Items (Need Pi Access)

The following require Pi hardware and real audio output:

- **D6.1 (TP-004):** Signal quality THD measurement — play 1 kHz sine,
  check spectrum for harmonics. Target: THD < -40 dB.
- **D6.2 (TP-004):** SPL readout cross-reference — play pink noise, compare
  Pi SPL reading with REW on Windows. Target: within +/- 3 dB.
- **AC-7.4:** SPL update rate >= 4 Hz with real signal.
- **AC-10.3:** Spectrum update rate >= 4 Hz with real signal.
- **AC-9.1-9.3:** UMIK-1 USB hot-plug test with physical device.

These are Phase C tests per TP-004. All code-level signal quality mechanisms
are verified via unit tests, E2E tests, and code review.

---

## 8. Test Counts

| Component | Test file | Test count | Status |
|-----------|-----------|------------|--------|
| Signal gen safety | safety.rs | 9 | All pass |
| Signal gen RPC | rpc.rs | 25+ | All pass |
| Signal gen commands | command.rs | 20+ | All pass |
| Signal gen ramp | ramp.rs | (see crate tests) | All pass |
| Signal gen registry | registry.rs | 10+ | All pass |
| Web UI test tool REST | routes.py | (Pydantic validation) | Structural |
| E2E capture spectrum | test_capture_spectrum.py | 11 | All pass |
