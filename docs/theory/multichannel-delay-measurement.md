# Multichannel Delay Measurement via Uncorrelated Noise

Simultaneous measurement of propagation delays for all speaker channels
using per-channel uncorrelated noise and cross-correlation. Extends the
real-time transfer function capability described in
[realtime-transfer-function.md](realtime-transfer-function.md).

**Status:** Analysis complete, approved for future implementation
**Date:** 2026-04-03

---

## 1. Mathematical Basis

The technique exploits a fundamental property of uncorrelated signals:
the cross-correlation of two uncorrelated random signals converges to
zero, while the cross-correlation of a signal with itself produces a
sharp peak at the time offset.

Given 4 output channels, each playing a different noise signal `s1(t)`
through `s4(t)`, all mutually uncorrelated:

```
E[si(t) * sj(t + tau)] = 0   for i != j
```

The mic captures the sum with different propagation delays:

```
m(t) = sum_i(ai * si(t - di)) + n(t)
```

where `di` is the delay for channel i, `ai` is the attenuation, and
`n(t)` is ambient noise.

Cross-correlating `m(t)` with reference `si(t)`:

```
Rmi(tau) = E[m(t) * si(t + tau)]
         = ai * Rii(tau - di) + 0 + 0 + ... + 0
```

The uncorrelated terms vanish. Only the matching channel's autocorrelation
survives, peaked at `tau = di`. The peak position directly gives the
propagation delay for channel i. The peak height `ai` gives the relative
level at the mic position.

---

## 2. Noise Signal Selection

### Recommended: White Noise with Different PRNG Seeds

Each channel gets a `WhiteNoiseGenerator` (Xoshiro256++) initialized with
a different seed. Statistically independent sequences — cross-correlation
converges to zero as the averaging window grows.

| Option | Separation quality | Implementation | Notes |
|--------|-------------------|----------------|-------|
| **Different PRNG seeds (white)** | Good: O(1/sqrt(N)) residual | Simplest | Best for our system |
| MLS | Excellent: mathematically orthogonal | Needs MLS generator | Overkill for 4 channels |
| Gold codes | Excellent: CDMA-grade | Complex | GPS satellite separation |
| Different PRNG seeds (pink) | Moderate: broader autocorrelation | Same as white + pink filter | Worse delay resolution |

**Why white noise is optimal for delay measurement:** White noise
autocorrelation is a sharp delta function. The cross-correlation peak is
narrow, giving precise delay estimates — resolution of ~1 sample = 20.8
microseconds at 48kHz. Pink noise has a broader autocorrelation (more low-
frequency energy = longer correlation tail), which broadens the peak and
reduces delay precision.

### Separation SNR

With N samples of averaging:
- Signal peak height: proportional to N
- Residual cross-talk: proportional to sqrt(N)
- Separation SNR: `10 * log10(N)` dB

| Averaging duration | N (at 48kHz) | Separation SNR |
|-------------------|-------------|----------------|
| 1 second | 48,000 | 47 dB |
| 4 seconds | 192,000 | 53 dB |
| 10 seconds | 480,000 | 57 dB |

47+ dB is more than enough to identify each channel's delay peak
unambiguously with 4 channels playing simultaneously.

---

## 3. Acoustic Crosstalk

**Acoustic crosstalk does not degrade the correlation peaks.** It adds
secondary peaks that are useful.

When the left main plays `s1(t)`, the mic hears:
1. Direct sound: `a1 * s1(t - d1_direct)` — primary peak
2. Wall reflection: `a1_r * s1(t - d1_reflect)` — secondary peak
3. Right main's signal: `a2 * s2(t - d2)` — does NOT correlate with s1

Cross-correlating with `s1(t)` reveals:
- Primary peak at `d1_direct` (the delay we want)
- Secondary peaks at reflection delays (early reflections for channel 1)
- Zero contribution from channels 2, 3, 4

This is better than sequential measurement in one way: sequential
measurement captures reflections from ALL surfaces in the IR.
Simultaneous uncorrelated measurement isolates each channel's acoustic
signature, rejecting cross-channel reflections.

**Caveat:** Very long reverberation (RT60 > 1 second) adds a diffuse
floor under the cross-correlation, reducing direct-sound peak clarity.
Mitigated by using a short cross-correlation window focused on the
direct sound arrival — same solution as for sweep/IR measurement.

---

## 4. Signal-Gen Changes Required

### Current Architecture

From `src/signal-gen/src/generator.rs` and `command.rs`:
- Single generator instance per signal-gen process
- `active_channels` bitmask selects output channels
- **Same signal** goes to all active channels
- `CommandKind::Play` has one signal type, one channel bitmask

### Required: Per-Channel Multi-Noise Mode

**Option A: Multiple generator instances (recommended)**

Maintain up to 8 WhiteNoiseGenerator instances, one per channel, each
with a different PRNG seed. The process callback generates independently
for each channel.

New RPC command:
```json
{
  "command": "play_multi_noise",
  "channels": [1, 2, 3, 4],
  "level_dbfs": -20.0,
  "noise_type": "white"
}
```

Seeds derived deterministically from channel number (e.g.,
`seed = base_seed XOR channel_index`) so the reference signal can be
reconstructed from the channel number alone.

**Changes required:**
- `command.rs`: Add `PlayMultiNoise` variant to `CommandKind`
- `main.rs`: Process callback changes from single generator to per-channel
  generator array (~50 lines)
- `rpc.rs`: Add `play_multi_noise` RPC handler (~30 lines)
- `generator.rs`: No changes (generators already work per-channel)
- Safety: Each per-channel generator goes through `SafetyLimits` clipper

Estimated scope: ~100-150 lines of Rust.

**Option B: Sequential reference recording**

Play noise on each channel one at a time (current capability), record
what was sent, cross-correlate offline.

- Pro: zero signal-gen changes
- Con: not simultaneous — loses the key advantage

**Recommendation: Option A.** Simultaneous measurement is the point.

---

## 5. Integration with Real-Time Transfer Function

The per-channel uncorrelated noise integrates naturally with the dual-FFT
transfer function analysis:

### Reference Tap Point: Post-Convolver

For delay measurement, the reference must be tapped **post-convolver** —
the signal as it leaves the filter-chain convolver toward the speakers.
The convolver's FIR processing adds its own group delay (~1-2ms at the
crossover frequency). To measure the true acoustic propagation delay
(convolver output to mic), we need the post-convolver signal as reference.

This differs from transfer function measurement (see
[realtime-transfer-function.md](realtime-transfer-function.md)), which
uses a **pre-convolver** reference to capture the complete system response
including the convolver itself.

In our architecture:
- **Delay reference**: pcm-bridge-monitor taps the convolver output
  (post-convolver, what the speaker actually plays)
- **Delay measurement**: pcm-bridge-capture reads the UMIK-1

### Unified Workflow

1. Signal-gen plays uncorrelated white noise on all 4 speaker channels
2. pcm-bridge-monitor captures per-channel reference (post-convolver, 4ch)
3. pcm-bridge-capture captures UMIK-1 measurement (1-2 channels)
4. Transfer function engine computes:
   - **Cross-correlation**: mic vs each reference -> 4 delay values
   - **Cross-spectrum**: mic vs each time-aligned reference -> 4 TFs
   - **Coherence**: per channel -> confidence metric
   - **Combined display**: magnitude, phase, coherence, delay for all channels

### Display

- 4 overlaid transfer function traces (L main, R main, sub1, sub2),
  color-coded
- 4 coherence traces underneath
- 4 delay values in sidebar with confidence indicator (see below)
- All updating in real time

The operator places the mic, hits "measure all," and immediately sees
the complete system state for every channel.

### Delay Confidence Indicator

Each delay value should display a confidence level based on the quality
of the cross-correlation peak relative to the noise floor:

| Confidence | Indicator | Criteria |
|------------|-----------|----------|
| **High** | Green | Peak-to-floor ratio > 20 dB, single unambiguous peak |
| **Medium** | Yellow | Peak-to-floor ratio 10-20 dB, or secondary peak within 6 dB |
| **Low** | Red | Peak-to-floor ratio < 10 dB, or no clear peak |

The peak-to-floor ratio is computed from the cross-correlation output:
ratio of the primary peak amplitude to the RMS of the correlation outside
the peak region. A low ratio indicates insufficient averaging time,
excessive ambient noise, or a disconnected/muted channel.

The UI should NOT display delay values with "Low" confidence as
actionable — they should be visually distinguished (grayed out, struck
through, or flagged) to prevent the operator from trusting unreliable
measurements.

---

## 6. Comparison with Sequential Sweep

| Aspect | Sequential sweep | Simultaneous uncorrelated noise |
|--------|-----------------|--------------------------------|
| Channels measured | 1 at a time | All 4 simultaneously |
| Total time | 4 x (5-15s) = 20-60s | Delays in ~1s, TF in ~4s |
| Room must be quiet | Yes | No (coherence shows contamination) |
| Delay precision | Sub-sample (IR peak) | Sub-sample (cross-corr peak) |
| Impulse response | Direct output | Via IFFT of cross-spectrum |
| Reflections | All surfaces in IR | Per-channel isolated |
| signal-gen changes | None | Multi-noise mode needed |
| Speaker movement | Must re-measure | Tracks in real time |

---

## 7. Practical Workflow Improvement

### Current Venue Setup

1. Place mic
2. Mute all except L main, sweep L main (10s)
3. Mute L main, unmute R main, sweep (10s)
4. Repeat for sub1, sub2
5. Compute delays from 4 IRs
6. Compute correction filters
7. Deploy, listen, maybe repeat

### Proposed Venue Setup

1. Place mic
2. Hit "Measure All" — all channels play uncorrelated noise
3. Within 2s: delay values for all 4 channels, updating live
4. Within 5s: transfer functions and coherence for all channels
5. Adjust speaker positions — watch delays update in real time
6. Capture snapshot for FIR filter generation
7. Or: let system iteratively converge on correction

Steps 2-5 replace steps 2-5 of the current workflow. The positioning and
delay phase becomes interactive instead of batch.

---

## 8. Limitations

1. **SNR per channel is lower.** 4 channels at -20 dBFS each produce a
   combined signal ~6 dB louder. Each channel's correlation has ~6 dB
   less SNR than sequential. Compensated by 4x longer averaging (4s
   simultaneous vs 10s sequential for similar total SNR).

2. **Nonlinear distortion cross-talk.** Speaker distortion products may
   weakly correlate with other channels' references. At -20 dBFS,
   distortion is negligible. At higher levels, spurious secondary peaks
   could appear.

3. **Filter design SNR.** For final FIR filter generation requiring
   precise per-frequency magnitude, sequential sweep's superior SNR may
   be preferred. Recommendation: simultaneous noise for positioning +
   delay + verification, optional sequential sweep for highest-fidelity
   filter generation.

4. **Temperature-dependent delay drift.** The speed of sound changes
   ~0.6 m/s per degree Celsius (approximately +0.17% per degree C). For
   a speaker 10 meters from the mic, a 10C temperature change (common
   during an outdoor evening gig) shifts the propagation delay by
   ~0.17 ms — roughly 8 samples at 48kHz. This is well above the
   sub-sample measurement resolution.

   Mitigation: periodic re-alignment. The real-time delay display
   already supports continuous updates (section 7, step 5). For long
   outdoor gigs, the system should re-compute delay values at a
   configurable interval (default: every 5 minutes) and flag any drift
   exceeding a threshold (e.g., > 0.1 ms) to the operator. This is a
   nice-to-have for Phase 2 — indoor venues with stable temperature
   will not need it.

---

## 9. Safety

- signal-gen's -20 dBFS cap applies per-channel (S-2 defense-in-depth)
- All per-channel generators go through the SafetyLimits hard clipper
- D-009 gain constraints unchanged

### Multi-Channel Combined Level

4 uncorrelated channels at -20 dBFS each produce a combined acoustic
level approximately 6 dB higher than a single channel at the mic
position (incoherent power sum: `10*log10(4) = 6 dB`). The measurement
gain profile must account for this:

- Combined level at mic: approximately **-14 dBFS** (acoustic sum)
- If the measurement system applies any automatic gain (AGC, mic preamp
  adjustment), it must be calibrated for the 4-channel combined level,
  not the single-channel level
- The `play_multi_noise` RPC command should document the expected
  combined level in its response so the UI can display a warning
- For venues where -14 dBFS acoustic level is too loud (small rooms,
  late night), a `level_dbfs` parameter lower than -20 dBFS can be used
  per-channel — separation SNR is unchanged since all channels attenuate
  equally

---

## 10. References

- [realtime-transfer-function.md](realtime-transfer-function.md):
  SMAART-style dual-FFT analysis (prerequisite)
- [design-rationale.md](design-rationale.md): Time alignment section
- [phase-correction-analysis.md](phase-correction-analysis.md): Why
  minimum-phase FIR handles phase optimally
- D-009: Cut-only correction, gain safety
- `src/signal-gen/src/generator.rs`: WhiteNoiseGenerator (Xoshiro256++)
- `src/signal-gen/src/command.rs`: CommandKind, channel bitmask
