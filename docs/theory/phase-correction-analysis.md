# Phase Correction Analysis

Should the room correction pipeline explicitly correct for speaker phase
distortion, beyond what minimum-phase FIR inherently provides?

**Conclusion: No.** Minimum-phase FIR already provides optimal phase behavior
for the given magnitude correction. Explicit phase correction would degrade
transient fidelity — our primary design goal (D-001).

---

## What Minimum-Phase FIR Inherently Corrects

A minimum-phase filter has a unique mathematical property: its phase response
is fully determined by its magnitude response (via the Hilbert transform).
This coupling means:

1. **Magnitude-coupled phase correction comes for free.** When the correction
   filter flattens a magnitude peak (e.g., a 2kHz cone breakup resonance), the
   minimum-phase FIR simultaneously corrects the phase deviation that
   accompanied that peak. No separate phase correction step is needed.

2. **The crossover slope has minimum possible group delay.** Our combined
   minimum-phase FIR produces ~1-2ms of group delay at the 80Hz crossover
   point, compared to ~4-5ms for a traditional IIR Linkwitz-Riley crossover
   (D-001). This is one of the primary design advantages of the combined-filter
   approach.

3. **The entire correction chain is minimum-phase consistent.** As documented
   in [design-rationale.md](design-rationale.md) (section "Minimum-Phase
   Consistency"), every stage — UMIK-1 calibration, measured IR extraction,
   computed inverse, crossover shape, combined filter — maintains
   minimum-phase behavior. This consistency ensures the final filter has no
   pre-ringing.

By definition, a minimum-phase filter has the minimum possible group delay
for any given magnitude response. No causal filter can achieve less group
delay with the same frequency response shape.

---

## What Minimum-Phase FIR Does NOT Correct

**Excess phase** — the component of a speaker's phase response that is NOT
determined by its magnitude response. Our minimum-phase extraction step
(documented in design-rationale.md, "Minimum-Phase Consistency" step 2)
explicitly discards excess phase when it extracts the minimum-phase component
from the measured impulse response.

Sources of excess phase in loudspeakers:

### 1. Driver Group Delay

Every speaker driver has inherent group delay from the mechanical system
(moving mass, suspension compliance, voice coil inductance). The heavier and
more compliant the moving system, the greater the delay at low frequencies.

Typical values:
- Woofers/subwoofers: 5-15ms at low frequencies
- Midrange drivers: 1-3ms
- Tweeters: <0.5ms

This is a property of the driver's physics — a large, heavy woofer cone
physically cannot respond as quickly as a small, light tweeter diaphragm.

### 2. Acoustic Offset

A driver's acoustic center is typically 5-20mm behind the baffle face.
Different drivers in a multi-way speaker have different acoustic offsets,
creating a fixed time offset between frequency bands.

For our system this is less relevant — we use separate speaker cabinets
(mains and subs), not a single multi-way cabinet with a shared baffle.
The between-cabinet timing is handled by time alignment
([delays.yml](design-rationale.md#time-alignment)), not by the FIR filter.

### 3. Baffle Diffraction

When sound waves from the driver reach the cabinet edge, they diffract. This
produces a secondary wavelet that interferes with the direct sound, creating
a characteristic "edge diffraction dip" (typically 1-3kHz depending on baffle
width). The diffraction has both magnitude and phase effects. Our
minimum-phase correction handles the magnitude dip but not the excess phase
from diffraction.

### 4. Port Resonance Phase (Ported Subwoofers)

Near the port tuning frequency, a ported subwoofer's phase response has a
rapid rotation (~180 degrees) that is partially excess-phase. Our
minimum-phase correction captures the magnitude effect (the port's
contribution to output) but not the full phase rotation.

---

## Could We Explicitly Correct Excess Phase?

Yes, through three approaches — all of which conflict with our primary design
goal of transient fidelity.

### Approach A: Excess Group Delay Correction

1. Measure the speaker's impulse response
2. Compute the minimum-phase equivalent
3. The difference (measured minus minimum-phase) is the excess phase
4. Design an all-pass correction filter that compensates for the excess
   group delay
5. Convolve with the minimum-phase correction

**Problems:**
- Adds latency equal to the maximum excess group delay being corrected. For
  a woofer with 10ms of excess group delay at 50Hz, the correction must
  delay ALL frequencies by 10ms to "wait" for the 50Hz energy. PA path
  latency increases from ~5.3ms to ~15.3ms in live mode.
- Equivalent to making the filter partially linear-phase in the corrected
  band, reintroducing the pre-ringing that D-001 specifically avoids.
- Excess group delay is highly measurement-position-dependent. Correcting at
  one mic position may worsen it at another.

### Approach B: Full Linear-Phase Correction

Replace minimum-phase FIR with a linear-phase FIR that corrects both
magnitude and phase to a flat, zero-phase target.

**Problems:**
- Pre-ringing: ~6ms of pre-echo at 80Hz, ahead of every kick transient.
  This is the core reason linear-phase was rejected (D-001).
- Latency: half the filter length = 8,192 samples = 170ms. Catastrophic
  for live mode (singer slapback threshold ~25ms).
- CPU cost roughly doubles (the filter cannot be made causal without the
  full length).

### Approach C: Partial Excess-Phase Correction Below 200Hz

Correct excess group delay only in the sub-bass range where it is largest.
Low-frequency pre-ringing is masked by the long cycle periods, and the
correction improves sub-to-main phase alignment at the crossover.

**Problems:**
- Adds pipeline complexity for a marginal benefit (see psychoacoustic
  analysis below).
- Still adds some latency in the corrected band.
- The benefit is position-dependent and may not generalize across the
  listening area.

This is the least-damaging option if phase correction were ever desired, but
the psychoacoustic analysis shows it is not needed for our application.

---

## Psychoacoustic Analysis: Is Excess Phase Audible?

The dominant audible effect of excess phase is group delay — some frequencies
arriving later than others. Psychoacoustic research (Blauert & Laws 1978,
Moller et al. 2007) places the audibility threshold for group delay at
approximately one full cycle period of the frequency:

| Frequency | One cycle period | Typical speaker excess GD | Audible? |
|-----------|-----------------|--------------------------|----------|
| 30 Hz | 33ms | 10-15ms | No |
| 80 Hz | 12.5ms | 5-8ms | Borderline |
| 200 Hz | 5ms | 2-3ms | Possibly |
| 1 kHz | 1ms | <0.5ms | No |
| 5 kHz | 0.2ms | <0.1ms | No |

For our system:

- **Sub-bass (30-80Hz):** Speaker excess group delay is below the audibility
  threshold. The 10ms of woofer group delay at 30Hz is inaudible because one
  full cycle at 30Hz is 33ms. Correcting it adds latency for no audible
  benefit.

- **Crossover region (80Hz):** Borderline. Our minimum-phase FIR already
  achieves ~1-2ms group delay at 80Hz (vs 4-5ms for IIR LR4). The speaker's
  excess phase at 80Hz might add 5-8ms, but time alignment handles the bulk
  inter-cabinet delay, and the residual excess phase is at or below the
  audibility threshold.

- **Above 200Hz:** Excess group delay is small (<3ms) and below audibility
  thresholds in all practical speaker systems.

### Psytrance-Specific Considerations

Psytrance kick drums have fundamental energy at 40-60Hz with attack
transients spanning up to 8kHz. The concern is that excess phase smears the
kick's attack. Three counter-arguments:

1. **Minimum-phase is already optimal.** By definition, our minimum-phase FIR
   has the minimum possible group delay for the given magnitude response. No
   causal filter can do better without changing the frequency response.

2. **Excess phase correction trades frequency-dependent delay for
   frequency-independent delay.** The all-pass approach adds flat latency to
   ALL frequencies — including the transient's attack. The transient shape
   improves slightly at the cost of the entire kick arriving later.

3. **The primary transient-smearing effect was the IIR crossover.** The 4-5ms
   of group delay from a Linkwitz-Riley crossover at 80Hz affected the
   frequency region where sub and main energy overlap — exactly where
   psytrance kicks have their most critical energy. Our minimum-phase FIR
   already eliminated this (D-001).

---

## Recommendation

**Do not implement explicit phase correction.** The analysis supports five
conclusions:

1. **Minimum-phase FIR provides optimal phase behavior** for the given
   magnitude correction. The magnitude-coupled phase correction — the part
   that matters most — comes for free.

2. **Excess phase is at or below audibility thresholds** in our frequency
   range. Sub-bass group delay is masked by long cycle periods. Crossover-
   region excess phase is handled by time alignment.

3. **Any explicit phase correction degrades transient fidelity** by adding
   latency, pre-ringing, or both — directly conflicting with D-001.

4. **Time alignment handles the dominant timing issue** in a multi-cabinet PA
   system. The largest source of "phase distortion" is simply that the
   cabinets are at different distances from the listener.

5. **The combined minimum-phase FIR approach was specifically chosen** to
   avoid the phase artifacts that explicit correction would reintroduce.
   Adding phase correction would partially undo the core design decision.

### If Phase Correction Were Ever Desired

For a reference monitoring application where transient fidelity is less
critical than phase accuracy, Approach C (partial excess-phase correction
below 200Hz only) would be the least-damaging option. It could improve
sub-to-main phase coherence at the crossover for content that is less
transient-dependent than psytrance (e.g., orchestral music, speech
reinforcement).

For psytrance PA — minimum-phase with time alignment is the right
architecture.

---

## References

- D-001: Combined minimum-phase FIR filters (crossover + room correction)
- D-009: Cut-only correction (-0.5dB safety margin)
- D-011: Dual quantum strategy (1024 DJ / 256 live)
- [design-rationale.md](design-rationale.md): Full design rationale including
  minimum-phase consistency chain, group delay comparison, pre-ringing
  analysis
- [rt-audio-stack.md](../architecture/rt-audio-stack.md): PipeWire
  filter-chain convolver architecture and performance numbers
- Blauert, J. & Laws, P. (1978). "Group delay distortions in
  electroacoustical systems." JASA 63(5), 1478-1483.
- Moller, H. et al. (2007). "Audibility of group delay crossover filters."
  AES Convention Paper 7085.
