# Room Simulation and Compensation

This document explains how the mugge audio workstation measures a room's
acoustic behavior and computes correction filters that make the speakers
sound better in that room. It covers two topics: the room simulator that
allows testing the correction pipeline without physical hardware, and the
compensation pipeline itself -- the full chain from microphone measurement
through signal processing to a deployable FIR filter file.

The audience is someone who understands what sampling and filtering are at
an intuitive level but does not have DSP or acoustics training. Concepts
are explained when they first appear, and the reasoning behind design
choices is given alongside the mechanics.

For the strategic *why* behind the design decisions (why FIR instead of
IIR, why cut-only correction, why minimum-phase), see
[design-rationale.md](../theory/design-rationale.md). This document
focuses on the *how*.


## Part 1: The Room Simulator

### Why simulate a room?

The room correction pipeline needs a room impulse response to work with --
a recording of how a room transforms sound from a speaker to a microphone.
Getting a real impulse response requires real speakers, a real room, a real
microphone, and a quiet environment. That is impractical during software
development. A room simulator generates synthetic impulse responses that
exhibit the same acoustic phenomena as real rooms, allowing the entire
correction pipeline to be tested and validated without any hardware at all.

The simulator lives at `src/room-correction/mock/room_simulator.py` and is
configured via `src/room-correction/mock/room_config.yml`. It is used
exclusively for testing -- production measurements always come from the
UMIK-1 microphone in an actual venue.


### What a room does to sound

When a speaker produces sound in a room, the microphone receives not one
signal but many. The first arrival is the *direct sound* -- a straight
line from speaker to microphone, attenuated only by distance. Milliseconds
later, reflections begin arriving: sound that bounced off the floor, the
ceiling, the side walls, the back wall. Each reflection is quieter than the
direct sound (walls absorb some energy on each bounce) and arrives later
(it traveled a longer path). The combination of direct sound and
reflections creates the room's acoustic signature.

Two phenomena dominate what the microphone measures. The first is
*reflections*: discrete echo paths off surfaces, each with a specific
delay and attenuation. These create comb filtering -- interference patterns
where some frequencies are reinforced and others are canceled, depending on
the exact path lengths involved. The second is *room modes*: standing waves
that form between parallel surfaces at specific frequencies.


### Room modes: standing waves between walls

A room mode is a resonance. Imagine clapping your hands in a small room
with hard parallel walls. The sound bounces back and forth between the
walls. At certain frequencies, the round-trip distance between two walls
is exactly a whole number of wavelengths. At those frequencies, the
reflected waves line up perfectly with the outgoing waves, reinforcing each
other. This is a standing wave -- the sound builds up at that frequency far
beyond what it would in open air.

The simplest room modes are *axial* modes, which bounce between two
parallel surfaces. The frequency of the fundamental axial mode between two
walls separated by distance L is:

    f = c / (2L)

where c is the speed of sound (about 343 m/s at 20 degrees C). For a room
that is 8 meters long, the fundamental axial mode is at 343 / (2 * 8) =
21.4 Hz. Higher-order modes occur at integer multiples: 42.9 Hz, 64.3 Hz,
and so on. A 6-meter-wide room has modes at 28.6 Hz, 57.2 Hz, 85.8 Hz.
A 3-meter-high room has modes at 57.2 Hz, 114.3 Hz. Each pair of parallel
surfaces creates its own series of resonances.

In practice, a typical small venue might have a strong mode at 42 Hz that
adds 12 dB of boom to every kick drum, making the bass muddy and
overwhelming at certain positions in the room. Meanwhile, at other
positions, the same standing wave creates a null -- the positive and
negative pressure peaks cancel out, and the bass nearly vanishes. This is
the central problem that room correction addresses.

*Tangential* modes involve four surfaces (bouncing diagonally across two
pairs of walls) and *oblique* modes involve all six surfaces. These are
weaker than axial modes but contribute to the overall low-frequency
character of the room.


### The image source method

The simulator computes reflections using the *image source method*, a
classical technique in acoustics. The idea is elegant: instead of tracing
sound rays as they bounce off walls, you create a virtual copy of the
speaker on the other side of each wall -- a mirror image, as if the wall
were a mirror and the speaker's reflection were a real source.

The distance from a mirror image to the microphone equals the total path
length of the corresponding reflection. If the speaker is at position
(2, 5, 1.5) in a room 8 meters long, its mirror image across the x=0
wall is at (-2, 5, 1.5). The distance from that image to the microphone
is the same as the distance the sound actually travels: from the speaker
to the wall to the microphone. This geometric trick turns a complex ray
tracing problem into simple distance calculations.

For a rectangular room with six walls (floor, ceiling, four side walls),
there are six first-order image sources -- one reflection off each surface.
Each first-order image can itself be reflected across the remaining five
walls, producing 30 second-order image sources. The simulator computes all
37 discrete arrivals: 1 direct path + 6 first-order reflections + 30
second-order reflections.

For each arrival, the simulator computes two things:

**Delay.** The time it takes sound to travel from the image source to the
microphone. At 343 m/s, a path of 5 meters takes about 14.6 milliseconds.
The simulator converts this to a sample offset at 48 kHz (in this case,
700 samples) and places an impulse at that position in the impulse
response.

**Attenuation.** Two factors reduce the level of each reflection. First,
the inverse distance law: sound level drops as 1/distance. A reflection
that travels twice as far as the direct sound is 6 dB quieter. Second,
wall absorption: each surface absorbs some fraction of the sound energy on
each bounce. With an absorption coefficient of 0.3 (a lightly treated
room), each bounce reduces the reflection by a factor of (1 - 0.3) = 0.7.
A second-order reflection (two bounces) is reduced by 0.7 * 0.7 = 0.49 --
roughly half the energy, before distance attenuation.

The speed of sound depends on temperature:

    v = 331.3 + 0.606 * T

where T is in degrees Celsius. At 22 degrees C (a typical indoor
temperature), v = 344.6 m/s. At 30 degrees C (a warm venue), v = 349.5
m/s. This 1.4% difference shifts arrival times by a fraction of a
millisecond per meter of path length -- small, but the simulator accounts
for it because real measurements capture it implicitly.


### Room mode simulation

The image source method models discrete reflections well but does not
naturally produce the resonant buildup of room modes. The simulator
addresses this by adding biquad peak filters (a standard IIR filter
topology) tuned to the expected mode frequencies. Each mode is defined by
three parameters: its frequency, its Q factor (how narrow the resonance
is -- a higher Q means a sharper peak), and its gain in decibels (how much
it amplifies that frequency).

The default test room (8 x 6 x 3 meters) has three configured modes:

| Frequency | Q | Gain | Origin |
|-----------|---|------|--------|
| 42.5 Hz | 8.0 | +12 dB | Strong axial mode (length dimension) |
| 28.7 Hz | 6.0 | +8 dB | Deep bass mode (approaching length + width interaction) |
| 57.2 Hz | 5.0 | +6 dB | Tangential mode (width dimension) |

These values are representative of what one might measure in a small club.
The 42.5 Hz mode at +12 dB is particularly problematic -- it would make
the bass uncomfortably boomy at some positions while barely audible at
others. This is exactly the kind of distortion the correction pipeline is
designed to fix.


### Predefined room scenarios

The simulator supports three scenarios via configuration files:

**Small club** (8 x 6 x 3 meters, absorption 0.3). Represents a typical
small venue with moderate acoustic treatment. Strong room modes below 60
Hz. Speakers near the front wall, microphone at the center of the
audience area. This is the default test configuration.

**Large hall** (20 x 15 x 5 meters). Higher ceiling, larger floor area.
Room modes are more closely spaced (more modes per octave, because mode
spacing decreases with room size) but individually weaker (the larger
volume means less energy buildup per mode). Reflections arrive later and
more spread out in time.

**Outdoor tent.** Open sides provide minimal reflection (high absorption
coefficient). Few significant room modes. The impulse response is
dominated by the direct sound with weak ground reflections. This scenario
tests how the correction pipeline behaves when there is little to correct.


### From simulation to testing

A simulated measurement works exactly like a real one. The test harness
generates a log sweep (the same sweep the production pipeline uses),
convolves it with the synthetic room impulse response (simulating what
the microphone would record), and feeds the result into the correction
pipeline. The pipeline does not know or care whether the impulse response
came from a real room or a simulated one -- the math is the same.

This allows the test suite to validate the entire correction chain end to
end: sweep generation, deconvolution, frequency analysis, correction
filter computation, crossover integration, and D-009 safety enforcement.
If the pipeline produces a correction filter that successfully flattens
a synthetic room with a known 12 dB mode at 42.5 Hz, there is high
confidence it will handle a similar mode in a real room.


---


## Part 2: The Room Compensation Pipeline

The compensation pipeline transforms a microphone measurement into a
correction filter that can be loaded by PipeWire's filter-chain convolver.
The pipeline runs once per speaker per venue -- four speakers means four
passes, producing four independent FIR filter files. The entire process is
automated: arrive at the venue, place the microphone, run the pipeline,
remove the microphone, ready to perform.


### Step 1: Measurement with a log sweep

The pipeline begins by playing a known signal through each speaker and
recording what the microphone hears. The signal is a *logarithmic sine
sweep* -- a tone that starts at 20 Hz and rises smoothly to 20 kHz over
several seconds. The frequency increases exponentially, spending more time
at low frequencies than high ones. This is deliberate: low frequencies
carry less energy per cycle, so dwelling longer at low frequencies gives
them more total energy, improving the signal-to-noise ratio in the bass
where room modes are strongest and correction matters most.

The sweep includes gentle fade-in and fade-out ramps (Hann windows, about
50 ms each) to prevent the speaker from producing a sharp transient at the
start and end. Without these ramps, the sudden onset would excite all
frequencies simultaneously, contaminating the measurement with a burst of
broadband energy that blurs the time resolution of the resulting impulse
response.

Each speaker is measured individually. During measurement of the left
main, the right main and both subs are silent. This ensures the impulse
response captures only the acoustic path from that specific speaker to the
microphone, without interference from other sources.

The microphone is a miniDSP UMIK-1, a calibrated USB measurement
microphone. Its calibration file contains the frequency-dependent
sensitivity correction that accounts for the microphone's own frequency
response deviations. The calibration is a magnitude-only correction --
it adjusts the level at each frequency but does not alter the phase. This
is important: a phase-altering calibration would contaminate the
minimum-phase chain that the rest of the pipeline maintains.


### Step 2: Deconvolution -- extracting the room's impulse response

The microphone recording contains the sweep convolved with the room's
impulse response: the room has smeared, delayed, and colored the original
sweep. *Deconvolution* reverses this, extracting the room's impulse
response from the recorded signal.

The mathematical idea is straightforward. Convolution in the time domain
is multiplication in the frequency domain. If the recorded signal R(f) =
Sweep(f) * Room(f), then Room(f) = R(f) / Sweep(f). Dividing the
spectrum of the recording by the spectrum of the original sweep yields the
room's transfer function, and an inverse FFT converts that back to the
time-domain impulse response.

In practice, the division is slightly more nuanced. At frequencies where
the sweep has very little energy (near DC and near the Nyquist frequency),
the division would amplify noise. The pipeline uses Wiener deconvolution,
which adds a small regularization term to the denominator that prevents
the division from blowing up at low-energy frequencies. The result is a
clean impulse response that faithfully represents the room's acoustic
behavior within the sweep's frequency range.

The deconvolved impulse response is a complete record of the room: the
initial spike of the direct sound, followed by early reflections arriving
within the first 10-20 milliseconds, followed by a decaying tail of late
reverberation. Everything the room does to sound from that speaker at that
microphone position is encoded in this single waveform.


### Step 3: Frequency-dependent windowing

Not all parts of the impulse response are equally useful for correction.
The direct sound and early reflections represent the consistent acoustic
behavior of the room -- they do not change much if the microphone moves a
few centimeters. Late reflections are a different story. They arrive from
many directions after bouncing off multiple surfaces, and their exact
pattern is extremely position-dependent. A reflection that arrives at
exactly the right time to cancel a specific frequency at the microphone
position might reinforce that same frequency half a meter away.

If the correction filter tries to compensate for these late, position-
dependent reflections, it creates a correction that is perfect at the
measurement position and worse than no correction everywhere else. The
correction filter would be chasing narrow interference patterns that
shift with any movement of the listener's head.

The solution is to apply different amounts of the impulse response at
different frequencies:

**Below about 500 Hz**, the pipeline uses a long window that captures most
of the impulse response. Room modes -- standing waves between walls --
operate at these frequencies. They are temporally long phenomena (a
standing wave at 42 Hz takes 24 milliseconds per cycle and may ring for
hundreds of milliseconds) and spatially broad (the same mode affects a
large area of the room). The long window captures the mode's full
resonant behavior, allowing the correction to target it precisely.

**Above about 500 Hz**, the pipeline applies a short window of roughly 5
milliseconds. This retains the direct sound and the very earliest
reflections but discards everything later. At high frequencies, individual
reflections create comb filtering -- alternating peaks and nulls spaced
very closely in frequency -- that shifts dramatically with position. The
short window prevents the correction from seeing (and trying to fix) these
position-dependent artifacts. Instead, the correction addresses only the
broad spectral shape of the speaker itself, which is consistent regardless
of where in the room the listener stands.

The implementation splits the impulse response into low-frequency and
high-frequency bands using a fourth-order Butterworth crossover at the
transition frequency, applies a different window to each band, and
recombines them. The result is an impulse response that has been
selectively trimmed: detailed at low frequencies where room modes dominate,
brief at high frequencies where position-dependent reflections dominate.


### Step 4: Psychoacoustic smoothing

After windowing, the pipeline computes the magnitude spectrum of the
processed impulse response and smooths it. The smoothing prevents the
correction from chasing narrow-band artifacts that the human ear cannot
perceive.

Human hearing does not resolve individual frequencies with the precision
of an FFT. Instead, the auditory system integrates energy within
frequency bands called *critical bands*, whose width increases with
frequency. At 100 Hz, the ear can distinguish tones about 15 Hz apart.
At 4,000 Hz, the critical band is roughly 400 Hz wide. A sharp 3 dB
notch at 4,137 Hz is inaudible -- the ear averages it with the
surrounding energy. A broad 3 dB tilt across the 2-8 kHz range is
obvious.

The pipeline applies *fractional-octave smoothing* at three different
widths, matched to the ear's resolution:

**1/6 octave below 200 Hz.** Room modes are narrow peaks -- a mode at 42
Hz might be only 5 Hz wide. The fine smoothing preserves these narrow
features so the correction can target them precisely. This is where
correction matters most.

**1/3 octave from 200 Hz to 1 kHz.** A transition region. Moderate
smoothing balances detail against spatial robustness. Features narrower
than 1/3 octave at these frequencies are likely position-dependent
reflections rather than consistent room behavior.

**1/2 octave above 1 kHz.** Coarse smoothing that only preserves the
broad spectral shape. Any feature narrower than half an octave at these
frequencies is almost certainly a reflection artifact. Correcting it would
make things worse at every position except the measurement point.

The smoothing operates in the logarithmic domain (geometric mean of
magnitudes within each window), consistent with how the ear perceives
loudness. This ensures that the smoothed spectrum represents what a
listener actually hears, not what a linear-scale measurement shows.

Smoothing also improves the correction's *spatial robustness*. A
correction filter that matches every narrow peak and dip at the
measurement position is fragile -- it becomes wrong as soon as the
listener moves. A smoothed correction targets only broad spectral
trends, which are more consistent across the listening area.


### Step 5: Target curves

A perfectly flat frequency response is not the goal. The ear's sensitivity
varies with frequency and with overall loudness, and listening in a room
is perceptually different from listening on headphones. Research (notably
by Harman International) has shown that listeners consistently prefer a
response with slightly more bass and a gently sloping treble rolloff when
listening to speakers in rooms.

The pipeline supports three target curves:

**Flat.** Uniform response at all frequencies. Useful as a baseline
reference, but it tends to sound thin at moderate playback levels because
the ear is less sensitive to bass at lower SPL (the Fletcher-Munson effect).

**Harman.** Based on Harman International's preference research. A gentle
bass shelf (+3 dB below 80 Hz), flat through the midrange, and a gradual
treble rolloff (-1 dB per octave above 2 kHz). This curve sounds natural
at moderate listening levels (75-85 dB SPL) and matches what trained
listeners consistently prefer in controlled tests.

**PA / Psytrance.** Tuned for high-SPL playback (95-105 dB SPL) of
bass-heavy electronic music. At high SPL, the ear's sensitivity curve
flattens -- the Fletcher-Munson effect diminishes -- so less bass boost is
needed. A subtle sub-bass shelf (+1.5 dB below 60 Hz) provides the extra
kick impact that psytrance demands, while a gentle treble rolloff (-0.5
dB/octave above 4 kHz) protects the high-frequency drivers from sustained
high-power operation.

An optional layer of *ISO 226 equal-loudness compensation* can be applied
on top of any target curve. This adjusts the target based on the actual
playback level relative to the level the music was mixed at (typically 80
phon). If the music was mixed at 80 phon but will be played at 60 phon
(a quieter house party), the compensation adds bass and treble to
counteract the ear's reduced sensitivity at lower levels. At PA levels
(100+ phon), the compensation reduces the bass shelf because the ear's
response is already relatively flat.

Crucially, target curves are implemented as *relative attenuation*, not
boost. Instead of "boost bass by 3 dB," the pipeline cuts midrange and
treble by 3 dB relative to bass. The perceptual result is identical, but
the signal level stays safely below digital full scale. The lost loudness
is recovered by turning up the analog amplifier gain, which has headroom
to spare. This is a direct consequence of the cut-only correction policy
(D-009).


### Step 6: Computing the inverse filter

With the smoothed room measurement and the target curve in hand, the
pipeline computes the correction: what filter, when applied to the room's
output, would make it match the target?

The math is simple division. At each frequency, the correction is:

    correction = target / measured

Where the room has a peak (measured > target), the correction is less than
unity -- it cuts. Where the room matches the target, the correction is
unity -- no change. Where the room has a null (measured < target), the
naive correction would be greater than unity -- a boost.

But the pipeline never boosts. This is the D-009 safety policy, and it
deserves explanation.

Psytrance is among the loudest-mastered genres in electronic music. Tracks
routinely arrive at -0.5 LUFS -- within half a decibel of digital full
scale. If a correction filter boosts any frequency by even 1 dB, the
signal exceeds 0 dBFS and clips. Digital clipping is not the gentle
saturation of an analog amplifier; it truncates the waveform, producing
harsh distortion that is immediately painful on a PA system at volume.

The pipeline enforces a hard ceiling: every frequency bin in the
correction filter must have a gain of -0.5 dB or less. Room peaks are
cut; room nulls are left alone. The -0.5 dB margin accounts for
numerical artifacts (FIR truncation ripple, the Gibbs phenomenon at
filter edges) and the possibility that some tracks are mastered even
louder than -0.5 LUFS.

This is less of a compromise than it might seem. Room peaks are the
dominant audible problem -- a 12 dB peak at 42 Hz makes every kick drum
sound bloated and muddy. Cutting that peak is what makes the system sound
clean. Room nulls, by contrast, are position-dependent: a null at the
measurement position may be a peak two meters away. Boosting into a null
wastes amplifier power to fix a problem that exists only at one spot in
the room, while making that same frequency louder everywhere else.


### Step 7: Minimum-phase FIR synthesis

The correction so far exists as a magnitude spectrum -- a description of
how much to cut at each frequency. To apply it in real time, the pipeline
must convert it into a finite impulse response: a list of numerical
coefficients that PipeWire's convolver can multiply against the audio
stream sample by sample.

The conversion uses the *cepstral method*, which produces a
*minimum-phase* FIR filter. Understanding why minimum-phase matters
requires a brief detour into what phase means for audio.

**What is phase?** Every filter changes two things about the signal: the
magnitude (how loud each frequency is) and the phase (the timing
relationship between frequencies). A minimum-phase filter introduces the
smallest possible timing distortion for a given magnitude response. It
concentrates all its energy at the beginning of the impulse response --
the filter responds immediately and decays forward in time.

**Why not linear-phase?** The alternative is a linear-phase filter, which
introduces zero relative timing distortion between frequencies. This
sounds ideal, but it achieves this by adding equal delay at all
frequencies. For a long filter at low frequencies, this delay manifests
as *pre-ringing*: a faint copy of the signal that arrives *before* the
signal itself. At 80 Hz (a typical crossover frequency), a linear-phase
filter produces about 6 milliseconds of pre-echo -- a ghostly anticipation
of each kick drum. Human hearing is remarkably sensitive to sounds that
precede their cause, and pre-ringing is audible in critical listening even
when it is 30-40 dB below the main signal.

**Minimum-phase avoids this.** A minimum-phase filter has no pre-ringing
at all. It does introduce group delay -- about 1-2 milliseconds at 80 Hz
-- meaning low frequencies arrive slightly later than high frequencies.
But group delay is far less perceptible than pre-ringing. A constant delay
is inaudible; a sound that arrives before its cause is not.

**The cepstral method** converts a magnitude spectrum to a minimum-phase
impulse response in four steps:

1. Take the logarithm of the magnitude spectrum. This transforms the
   multiplicative relationship between magnitude values into an additive
   one, which is necessary for the cepstral decomposition.

2. Compute the inverse FFT of the log magnitude. The result is the *real
   cepstrum* -- a representation in the "quefrency" domain (a deliberate
   anagram of "frequency"). The cepstrum separates the minimum-phase
   component of a signal from its excess-phase component.

3. Apply a *causal window*: keep the DC component as-is, double the
   positive-quefrency (causal) half, and zero the negative-quefrency
   (anti-causal) half. This is the step that enforces minimum-phase: by
   discarding the anti-causal part of the cepstrum, the result is
   guaranteed to be causal (no energy before time zero) and minimum-phase
   (minimum possible group delay for the given magnitude).

4. Compute the FFT of the windowed cepstrum and exponentiate. The result
   is the minimum-phase spectrum. An inverse FFT converts it to the time-
   domain impulse response.

The output is truncated to 16,384 taps (the project's standard filter
length) with a gentle fade-out window over the last 5% of taps to avoid
spectral splatter from abrupt truncation.


### Step 8: Crossover integration

The correction filter from step 7 only addresses room response. It does
not yet include the crossover -- the frequency split that sends bass to
the subwoofers and mid-to-high frequencies to the main speakers. The
crossover is generated separately as its own minimum-phase FIR filter
(a highpass for the mains, a lowpass for the subs) and then combined
with the correction.

The combination is done by multiplying the two filters' spectra in the
frequency domain -- mathematically equivalent to convolving them in the
time domain, but much faster computationally. If a ported subwoofer
requires subsonic protection (a highpass below the port tuning frequency
to prevent the driver from over-excursing), that protection filter is
multiplied in as well.

After multiplication, the D-009 safety enforcement is applied again to
the combined magnitude. The crossover introduces additional attenuation
(that is its job), but the combined margin is set slightly tighter at
-0.6 dB to account for the additional multiplication step's numerical
artifacts. Every frequency bin is checked: if any bin exceeds the margin,
it is clipped down.

Finally, the combined magnitude is converted to a minimum-phase FIR using
the same cepstral method from step 7. This is a crucial detail: the
minimum-phase conversion is applied to the *final, clipped* magnitude,
not to an intermediate impulse response. Building the filter from the
target magnitude directly (rather than converting an existing IR)
guarantees that the output magnitude spectrum exactly matches the
D-009-compliant design. There are no accumulated numerical artifacts from
intermediate conversions.

The result is a single FIR filter per output channel that performs room
correction, frequency-band splitting, and driver protection in one
convolution operation. PipeWire's filter-chain convolver loads these
filters as WAV files and applies them in real time using partitioned
FFT convolution with FFTW3's ARM NEON-optimized codelets.


### Step 9: The output

The pipeline produces four WAV files, one per speaker channel:

| File | Channel | Filter type |
|------|---------|-------------|
| `combined_left_hp.wav` | Left main | Highpass + room correction |
| `combined_right_hp.wav` | Right main | Highpass + room correction |
| `combined_sub1_lp.wav` | Subwoofer 1 | Lowpass + room correction + subsonic HPF |
| `combined_sub2_lp.wav` | Subwoofer 2 | Lowpass + room correction + subsonic HPF |

Each file contains a 16,384-tap minimum-phase FIR filter at 48 kHz. At
this length, the filter spans 341 milliseconds and provides 2.9 Hz
frequency resolution. This translates to 6.8 complete cycles at 20 Hz --
enough for solid correction at the very bottom of the audible range -- and
10.2 cycles at 30 Hz, where most subwoofer activity occurs.

The files are deployed to `/etc/pi4audio/coeffs/` on the Pi. PipeWire's
filter-chain convolver references them by path in its configuration. When
the files are updated and the filter-chain is reloaded (via a GraphManager
mode transition), the new corrections take effect immediately.


### The minimum-phase guarantee

The entire pipeline maintains minimum-phase behavior at every step. This
is not a nice-to-have property -- it is a structural requirement. If any
single step introduces linear-phase or mixed-phase behavior, the final
filter will contain pre-ringing, and no subsequent step can remove it.

The chain of minimum-phase consistency:

The **UMIK-1 calibration** is a magnitude-only correction file. Applying
a magnitude-only correction does not alter phase, so it is inherently
compatible with the minimum-phase pipeline.

The **measured impulse response** from a real room is not minimum-phase --
it includes excess phase from propagation delay and reflection paths. The
frequency-dependent windowing in step 3 addresses this by limiting the
impulse response to its early, direct-sound-dominated portion, and the
subsequent magnitude extraction discards phase information entirely. The
correction is computed from magnitude alone.

The **inverse filter** (step 6) is computed from magnitudes, so it has no
phase of its own.

The **cepstral synthesis** (step 7) builds a minimum-phase filter directly
from the magnitude specification. It does not convert an existing
mixed-phase impulse response -- it synthesizes a new one that is
minimum-phase by construction.

The **crossover filter** is also synthesized as a minimum-phase FIR using
the same cepstral method.

The **combination** (step 8) multiplies magnitudes and re-synthesizes
from scratch as minimum-phase. No intermediate impulse response carries
phase information forward.

The result: the final deployed filter is guaranteed minimum-phase. No
pre-ringing, minimal group delay, and the magnitude response exactly
matches the designed correction within the D-009 safety envelope.


### Multi-position measurement

Room correction is most effective when it addresses acoustic behavior that
is consistent across the listening area, not artifacts specific to a
single microphone position. A correction based on a single measurement
point can overcorrect features that are unique to that spot.

The pipeline supports *spatial averaging*: taking measurements at 3-5
positions in a cluster around the intended listening area (the center of
the dancefloor, for instance) and averaging the results. The averaging
operates on the magnitude spectra of the deconvolved impulse responses.
Features that appear consistently across all positions -- room modes, the
speaker's broad frequency response shape -- survive the averaging.
Features that vary between positions -- narrow comb-filter notches from
specific reflection paths -- are averaged out, producing a correction
that is effective over a wider area.

This spatial averaging is complementary to the frequency-dependent
windowing (step 3) and psychoacoustic smoothing (step 4). All three
mechanisms serve the same goal: ensuring the correction addresses
consistent, broadband room behavior rather than position-dependent
interference patterns.


---

*Source code: `src/room-correction/` contains the full pipeline
implementation. Key modules: `sweep.py` (step 1), `deconvolution.py`
(step 2), `dsp_utils.py` (steps 3-4, cepstral method), `target_curves.py`
(step 5), `correction.py` (steps 6-7), `combine.py` (step 8),
`crossover.py` (crossover generation), `deploy.py` (step 9). The room
simulator lives at `mock/room_simulator.py` with configuration in
`mock/room_config.yml`. Tests in `tests/` validate each module
independently and the full pipeline end-to-end via simulated rooms.*
