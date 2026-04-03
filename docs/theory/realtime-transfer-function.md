# Real-Time Transfer Function Measurement with Coherence

SMAART-style dual-FFT measurement for live venue tuning. Complements the
existing sweep/impulse-response pipeline — does not replace it.

**Status:** Analysis complete, approved for future implementation
**Date:** 2026-04-03

---

## 1. Coherence: The Math

Magnitude-squared coherence (MSC) measures how well the measurement signal
is linearly related to the reference signal at each frequency:

```
Cxy(f) = |Gxy(f)|^2 / (Gxx(f) * Gyy(f))
```

Where:
- `Gxy(f)` = cross-spectral density between reference (x) and measurement (y)
- `Gxx(f)` = auto-spectral density of the reference
- `Gyy(f)` = auto-spectral density of the measurement

Cxy ranges from 0 to 1:
- **1.0** — all measured energy at this frequency came from the excitation
  signal. The transfer function is fully deterministic.
- **0.0** — no linear relationship. Energy is entirely noise, nonlinear
  distortion, or uncorrelated sources (audience, HVAC).

### Practical Interpretation

| Cxy range | Confidence | Action |
|-----------|-----------|--------|
| > 0.85 | High | Transfer function is trustworthy. Correct aggressively. |
| 0.5 - 0.85 | Moderate | Some ambient contamination. Correct conservatively. |
| < 0.5 | Low | More noise than signal. Do not correct at this frequency. |

### Computation (Welch's Method)

SMAART and similar tools use overlapping, windowed FFT blocks averaged
over time:

1. Capture N blocks of reference and measurement (each = one FFT window)
2. Apply Hann window to each block
3. Compute FFT: `X_k(f)` and `Y_k(f)` for block k
4. Accumulate cross-spectrum: `Gxy(f) = (1/N) * sum(X_k * conj(Y_k))`
5. Accumulate auto-spectra: `Gxx(f) = (1/N) * sum(|X_k|^2)`, same for Gyy
6. Compute coherence: `Cxy(f) = |Gxy|^2 / (Gxx * Gyy)`
7. Transfer function: `H(f) = Gxy(f) / Gxx(f)` (magnitude and phase)

A single FFT block trivially gives Cxy = 1.0. Coherence only becomes
meaningful with multiple averaged blocks (typically 8-32).

**Exponential averaging** (as SMAART uses) weights recent blocks more
heavily for a continuously updating display:

```
Gxy_new = alpha * X_k * conj(Y_k) + (1 - alpha) * Gxy_old
```

The `alpha` parameter controls how quickly old data fades — adjustable
"memory" for the display.

### Low-Frequency Resolution Limit

At 48kHz sample rate, a 4096-point FFT gives frequency bins of 11.7 Hz.
Below ~50 Hz, there are only ~4 bins, and coherence tends to drop not
because of noise but because of **insufficient frequency resolution** —
the room's modal behavior changes rapidly within each wide bin, reducing
the apparent linear relationship.

For sub-bass work (below 50 Hz), use a larger FFT:
- 8192 points → 5.9 Hz bins (adequate for most sub tuning)
- 16384 points → 2.9 Hz bins (matches our FIR filter resolution)

The tradeoff is temporal resolution: 16384 points at 48kHz = 341ms per
block, so the display updates more slowly. A practical compromise is to
run two parallel FFT engines — 4096-point for mid/high frequencies with
fast updates, 16384-point for sub-bass with slower but more accurate
coherence.

---

## 2. Dual-FFT Transfer Function Measurement

### How It Differs from Sweep/IR

**Sweep/IR (our current approach):**
```
signal-gen (sweep) -> speaker -> room -> UMIK-1 -> pw-record
-> deconvolution -> impulse response -> FIR filter design
```
- One-shot: play sweep, record, done
- Complete impulse response (time domain)
- High SNR (energy concentrated at each frequency sequentially)
- 5-15 seconds per channel, room must be quiet
- Result is a static snapshot

**Dual-FFT transfer function:**
```
signal-gen (pink noise) -> speaker -> room -> UMIK-1
                    \                            |
                     \-> reference signal -----> |
                                                 v
                            cross-spectrum + coherence
                                     |
                                     v
                          real-time transfer function H(f)
```
- Continuous: noise plays constantly, display updates in real time
- Transfer function (frequency domain): magnitude and phase vs frequency
- Moderate SNR (energy spread across all frequencies simultaneously)
- Updates every few hundred milliseconds
- Coherence shows which frequencies have reliable data
- Result is live, continuously updating

### Reference Tap Point: Design Mode vs Verify Mode

The reference tap point depends on **what you want to measure**. Both
pre-convolver and post-convolver references are needed for different
phases of the calibration workflow:

**Design mode (pre-convolver reference):**
- Measures: `room x speaker x crossover` — the raw acoustic response
  with crossover slopes applied but no room correction
- Reference tapped before the convolver (signal-gen output)
- Transfer function shows what needs correcting
- Used when: designing correction filters for a new venue
- Convolver loads Dirac (identity) room correction coefficients but
  retains crossover slopes and sub HPF

**Verify mode (post-convolver reference):**
- Measures: `room x speaker x crossover x correction` — the complete
  processed response
- Reference tapped after the convolver (convolver output)
- Transfer function should be flat if correction is working
- Used when: verifying that loaded correction filters produce the
  desired response
- Standard SMAART practice: tap after the processor to see the result

The UI should offer a "Design" / "Verify" toggle (or equivalently
"Pre-convolver" / "Post-convolver" reference). The GraphManager
reconfigures the pcm-bridge-monitor tap point accordingly.

**Note on Design mode startup:** When the convolver loads Dirac (identity)
room correction, the crossover slopes and sub HPF are still active — these
are baked into the combined FIR coefficients. To measure the raw
`room x speaker` response without crossover, a separate set of Dirac-only
coefficients (no crossover) would be needed. In practice, measuring
through the crossover is what you want for room correction design, since
the correction operates within each band.

This also applies to delay measurement (see
[multichannel-delay-measurement.md](multichannel-delay-measurement.md)),
which always uses a **post-convolver** reference because it needs to
measure the actual acoustic propagation delay of what the speaker
physically plays.

In our architecture:
- **Design mode**: pcm-bridge-monitor taps signal-gen output (pre-convolver)
- **Verify mode**: pcm-bridge-monitor taps convolver output (post-convolver)
- **Both modes**: pcm-bridge-capture reads the UMIK-1 (post-room)

### Time Alignment Requirement

The cross-spectrum requires time-aligned reference and measurement signals
(same FFT block boundaries). The approach:

1. Split the signal: one copy to speakers, one to analyzer as reference
2. Measure propagation delay via cross-correlation peak
3. Delay the reference by this amount for aligned FFT windows

Without time alignment, the phase of Gxy is meaningless and Cxy drops.

---

## 3. Architecture Mapping

### Existing Components

| SMAART component | Our equivalent | Status |
|---|---|---|
| Reference signal source | signal-gen (pink/white noise) | READY |
| Reference channel capture | pcm-bridge (monitor mode, port 9100) — tap point switchable | READY |
| Measurement mic | UMIK-1 via USBStreamer ch 1-2 | READY |
| Measurement capture | pcm-bridge (capture mode, port 9101) | READY |
| Dual-channel FFT + cross-spectrum | — | NEEDS IMPLEMENTATION |
| Coherence computation | — | NEEDS IMPLEMENTATION |
| Transfer function display | Web UI spectrum.js (partial) | NEEDS EXTENSION |
| Time alignment (delay finder) | — | NEEDS IMPLEMENTATION |

signal-gen already has `PinkNoiseGenerator` (Voss-McCartney, +/-0.5 dB
slope accuracy) and `WhiteNoiseGenerator` (Xoshiro256++). Both are RT-safe
with no allocation in the generate path.

pcm-bridge streams v2 wire format with graph clock timestamps (monotonic
nanoseconds) — usable for bootstrapping time alignment.

Web UI has a 4096-point FFT pipeline with Hann window and spectrum renderer.

### Where to Compute the Dual-FFT

**Option A: Browser-side (JavaScript/WebAssembly)**
- Both pcm-bridge streams via WebSocket, JS computes cross-spectrum
- Pro: zero server changes
- Con: two real-time PCM WebSocket streams (~384 KB/s each) heavy on Pi

**Option B: Server-side Python (web-ui backend) — RECOMMENDED FOR PROTOTYPE**
- New `/ws/transfer-function` WebSocket endpoint
- Python reads both pcm-bridge TCP streams, computes with numpy
- Pro: browser renders pre-computed data (lightweight)
- Con: Python GIL awkward for real-time audio; adds CPU load

**Option C: New Rust service — RECOMMENDED FOR PRODUCTION**
- `transfer-function-bridge` reads two pcm-bridge streams, computes in Rust
- Pro: most CPU-efficient, lock-free, integrates with existing Rust services
- Con: most implementation effort

Recommendation: Option B for prototype (validate concept quickly), Option C
if CPU cost exceeds ~5-10% of one core.

---

## 4. Implementation Phases

### Phase 1: Minimal Viable Real-Time Analyzer

1. **signal-gen**: No changes (pink noise already exists)

2. **pcm-bridge**: No changes (both instances already run in production —
   monitor on port 9100, capture on port 9101)

3. **GraphManager**: New link topology for measurement-with-noise mode:
   - signal-gen -> convolver input (excitation)
   - signal-gen output -> pcm-bridge-monitor (TF reference, pre-convolver)
   - USBStreamer capture -> pcm-bridge-capture (measurement)
   - Note: for delay measurement, pcm-bridge-monitor taps post-convolver
     instead — see [multichannel-delay-measurement.md](multichannel-delay-measurement.md)

4. **Web UI backend** — new endpoint:
   ```
   /ws/transfer-function
   ```
   - Reads both pcm-bridge TCP streams
   - Computes time-aligned cross-spectrum (Welch's method)
   - Outputs JSON: `{magnitude_db, phase_deg, coherence, freq_axis}`
   - Parameters: FFT size (4096), averaging (16), overlap (50%)

5. **Web UI frontend** — new component:
   - Transfer function: magnitude (dB) and phase (degrees) vs frequency
   - Coherence overlay: color-coded (green > 0.85, yellow 0.5-0.85, red < 0.5)
   - Optional target curve overlay
   - Controls: start/stop, channel select, averaging speed

6. **Time alignment** — automatic delay finder:
   - Cross-correlate reference and measurement on startup
   - Apply delay to reference before computing cross-spectrum
   - Re-compute periodically (tracks speaker movement)

### Phase 2: Production Integration

7. **Auto-correction**: Use real-time TF to iteratively adjust correction
   filters while playing noise — convergence without dedicated silent
   measurement.

8. **Coherence-weighted correction**: Only correct where Cxy > threshold.
   Naturally avoids correcting noise-contaminated frequencies.

9. **Program material as reference**: During live performance, use the
   actual music signal (Mixxx or Reaper output) as the reference instead
   of noise excitation. The pre-convolver tap captures the program
   material; the UMIK-1 captures the room response. Coherence naturally
   indicates which frequencies have sufficient excitation energy at any
   moment — a psytrance kick provides excellent sub-bass coherence, while
   a vocal passage gives good mid-range data. Over time, a full-bandwidth
   picture emerges. This enables continuous drift monitoring during a
   performance without any audible measurement signal.

---

## 5. Comparison: Sweep/IR vs Real-Time TF

| Aspect | Sweep/IR | Real-time TF |
|--------|----------|-------------|
| Feedback speed | Minutes (sweep + compute + deploy) | Seconds |
| Ambient noise tolerance | Poor (room must be quiet) | Good (coherence shows contamination) |
| Iterative tuning | Full re-measurement cycle | Continuous |
| Audience present | Impossible (sweep is annoying) | Possible (pink noise at moderate level) |
| Filter design | Offline | Could be real-time (Phase 2) |
| Time alignment verification | Post-hoc (IR analysis) | Live |
| SNR per frequency | High (concentrated energy) | Lower (compensated by coherence) |
| Impulse response | Direct output | Via IFFT of transfer function |
| Phase information | From IR extraction | Direct from cross-spectrum |

### Workflow Roles

**Keep sweep/IR for:**
- Generating production FIR filters (combined crossover + room correction)
- High-SNR baseline measurement in quiet room
- Impulse response analysis (reflections, decay, precise alignment)
- Automated one-button venue calibration

**Add real-time TF for:**
- Live verification during soundcheck
- Quick iterative EQ tweaks
- Monitoring during performance (drift detection)
- Pre-measurement site survey
- Teaching: visual feedback of what correction does

**Combined workflow:** sweep/IR for initial calibration -> real-time TF for
verification and fine-tuning -> real-time TF during soundcheck with
audience noise present.

---

## 6. Safety Considerations

- signal-gen's -20 dBFS cap applies to continuous noise (S-2)
- Pink noise at -20 dBFS through PA is audible but not dangerous
- D-009 gain constraints unchanged — real-time TF is read-only measurement
- Phase 2 automated correction must gate updates through D-009 safety checks

---

## 7. References

- D-040: PipeWire filter-chain architecture
- D-009: Cut-only correction, -0.5 dB safety margin
- [rt-audio-stack.md](../architecture/rt-audio-stack.md): PipeWire convolver config
- [design-rationale.md](design-rationale.md): Sweep/IR pipeline design
- [multichannel-delay-measurement.md](multichannel-delay-measurement.md):
  Per-channel uncorrelated noise extension
