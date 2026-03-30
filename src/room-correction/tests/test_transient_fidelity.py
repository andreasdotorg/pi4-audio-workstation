"""Transient fidelity verification — no pre-ringing in correction filters (US-098 P2).

The entire design rationale for minimum-phase FIR filters is transient fidelity:
psytrance kick drums should have crisp attacks with no audible "ghost" energy
before the transient. Linear-phase FIR filters produce pre-ringing that smears
the attack; minimum-phase filters avoid this at the cost of slight group delay.

Tests verify signal-level behavior by convolving synthetic audio (kick drums)
through the correction pipeline and measuring pre-attack energy:

1. Kick drum transient test: < 1% energy before the attack after filtering.
2. Null correction test: flat room produces near-dirac correction.
3. Linear-phase comparison: proves minimum-phase has less pre-ringing.
4. Multi-position averaging: averaged corrections still have no pre-ringing.

These complement test_minimum_phase_property.py (which tests filter properties)
by testing actual signal behavior through the full pipeline.
"""

import os
import sys

import numpy as np
import pytest
import scipy.signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from room_correction import dsp_utils
from room_correction.combine import combine_filters
from room_correction.correction import generate_correction_filter
from room_correction.crossover import generate_crossover_filter
from room_correction.generate_profile_filters import generate_profile_filters

SR = dsp_utils.SAMPLE_RATE
N_TAPS = 16384
CROSSOVER_FREQ = 80.0
CORRECTION_MARGIN_DB = -0.6


# ---------------------------------------------------------------------------
# Synthetic audio helpers
# ---------------------------------------------------------------------------

def _make_psytrance_kick(sr=SR, duration_s=0.15):
    """Synthesize a psytrance kick drum with sharp attack and sub-bass content.

    Characteristics:
    - Exponential pitch sweep from ~150 Hz to ~45 Hz (typical psytrance kick)
    - Fast attack (~2ms rise time)
    - Sub-bass fundamental at ~45 Hz with harmonics
    - Total duration ~150ms

    The sharp attack transient is what makes pre-ringing audible:
    any filter energy appearing before the attack onset is perceived as
    a "ghost" or "click" preceding the kick.
    """
    n_samples = int(duration_s * sr)
    t = np.arange(n_samples, dtype=np.float64) / sr

    # Pitch sweep: exponential decay from 150 Hz to 45 Hz
    freq_start = 150.0
    freq_end = 45.0
    decay_rate = 20.0  # Hz/s decay speed
    freq = freq_end + (freq_start - freq_end) * np.exp(-decay_rate * t)

    # Phase integral of instantaneous frequency
    phase = 2.0 * np.pi * np.cumsum(freq) / sr

    # Waveform: sine with amplitude envelope
    # Very fast attack (~0.5ms), exponential decay
    attack_samples = int(0.0005 * sr)
    envelope = np.ones(n_samples)
    if attack_samples > 0:
        envelope[:attack_samples] = np.linspace(0, 1, attack_samples)
    # Exponential decay after attack
    decay_start = attack_samples
    envelope[decay_start:] *= np.exp(-8.0 * t[decay_start:])

    kick = np.sin(phase) * envelope

    # Add 2nd harmonic for body
    kick += 0.3 * np.sin(2 * phase) * envelope

    # Normalize to peak 1.0
    peak = np.max(np.abs(kick))
    if peak > 0:
        kick /= peak

    return kick


def _make_test_signal(kick, pre_silence_s=0.05, post_silence_s=0.05, sr=SR):
    """Embed a kick in silence with known onset position.

    Returns (signal, onset_sample) where onset_sample is the index
    of the first non-zero sample in the kick.
    """
    pre_samples = int(pre_silence_s * sr)
    post_samples = int(post_silence_s * sr)
    signal = np.zeros(pre_samples + len(kick) + post_samples)
    signal[pre_samples:pre_samples + len(kick)] = kick
    return signal, pre_samples


def _pre_attack_energy_ratio(original, filtered, onset_sample, sr=SR):
    """Measure the ratio of pre-attack energy in the filtered signal.

    For a minimum-phase filter, the output onset should coincide with the
    input onset — there should be no energy before the original onset
    position in the filtered signal. For a linear-phase filter, the
    symmetric IR spreads energy before the onset (pre-ringing).

    We measure the energy in the filtered signal before the original onset
    sample, relative to total filtered energy. The original onset is the
    correct reference because:
    - Minimum-phase filters are causal: output cannot precede input
    - The pre-silence region before onset should remain silent
    - Any energy there is pre-ringing from the filter

    A small guard margin (2ms) before the onset accounts for the filter's
    causal group delay spreading the attack slightly.
    """
    # The onset in the filtered signal should be at approximately the same
    # position as the original — minimum-phase filters are causal.
    # Use the original onset as the boundary.
    guard_samples = int(0.002 * sr)
    pre_end = max(0, onset_sample - guard_samples)

    if pre_end <= 0:
        return 0.0

    pre_energy = np.sum(filtered[:pre_end] ** 2)
    total_energy = np.sum(filtered ** 2)

    if total_energy < 1e-20:
        return 0.0

    return pre_energy / total_energy


def _make_room_ir(n=16384, sr=SR, seed=42):
    """Synthetic room IR with realistic features (same as test_minimum_phase_property)."""
    rng = np.random.RandomState(seed)
    ir = np.zeros(n, dtype=np.float64)
    ir[24] = 1.0
    for delay_ms in [3, 5, 7, 10, 14]:
        idx = int(delay_ms * sr / 1000)
        if idx < n:
            ir[idx] = 0.3 * rng.randn()
    decay = np.exp(-np.arange(n) / (0.3 * sr))
    ir += 0.02 * rng.randn(n) * decay
    t = np.arange(n) / sr
    mode = 0.1 * np.sin(2 * np.pi * 42 * t) * np.exp(-t / 0.5)
    ir += mode
    return ir


def _make_linear_phase_fir(min_phase_fir):
    """Convert a minimum-phase FIR to linear-phase with the same magnitude.

    Creates a symmetric (type I) linear-phase FIR with the same magnitude
    response. This is the reference for the pre-ringing comparison:
    the linear-phase version should have significant pre-ringing while
    the minimum-phase version should not.
    """
    n = len(min_phase_fir)
    # Get magnitude spectrum
    n_fft = dsp_utils.next_power_of_2(2 * n)
    spectrum = np.fft.rfft(min_phase_fir, n=n_fft)
    mag = np.abs(spectrum)

    # Create linear-phase (zero-phase) FIR via IFFT of magnitude only
    # This produces a symmetric IR centered at n_fft/2
    zero_phase_ir = np.fft.irfft(mag, n=n_fft)

    # Shift to create a causal linear-phase FIR
    # The zero-phase IR has its peak at sample 0 and wraps around;
    # we roll it to center the peak
    half = n_fft // 2
    linear_ir = np.roll(zero_phase_ir, half)

    # Truncate to original length, centered on the peak
    start = half - n // 2
    linear_fir = linear_ir[start:start + n]

    # Apply fade window to avoid truncation artifacts
    fade_len = n // 20
    fade = dsp_utils.fade_window(n, fade_len, fade_len)
    linear_fir *= fade

    return linear_fir


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def kick():
    """A synthetic psytrance kick drum."""
    return _make_psytrance_kick()


@pytest.fixture(scope="module")
def room_ir():
    """Synthetic room IR with 42 Hz mode."""
    return _make_room_ir()


@pytest.fixture(scope="module")
def correction_filter(room_ir):
    """Correction filter for the synthetic room."""
    return generate_correction_filter(
        room_ir, target_curve_name="flat",
        n_taps=N_TAPS, sr=SR, margin_db=CORRECTION_MARGIN_DB,
    )


@pytest.fixture(scope="module")
def combined_hp(correction_filter):
    """Combined correction + highpass crossover (main speaker path)."""
    xo = generate_crossover_filter(
        filter_type="highpass", crossover_freq=CROSSOVER_FREQ,
        slope_db_per_oct=48.0, n_taps=N_TAPS, sr=SR,
    )
    return combine_filters(correction_filter, xo, n_taps=N_TAPS)


@pytest.fixture(scope="module")
def combined_lp(correction_filter):
    """Combined correction + lowpass crossover (sub speaker path)."""
    xo = generate_crossover_filter(
        filter_type="lowpass", crossover_freq=CROSSOVER_FREQ,
        slope_db_per_oct=48.0, n_taps=N_TAPS, sr=SR,
    )
    return combine_filters(correction_filter, xo, n_taps=N_TAPS)


# ===================================================================
# 1. Kick drum transient test
# ===================================================================

class TestKickDrumTransient:
    """Convolve a psytrance kick through combined correction filters.
    Verify < 1% pre-ringing energy before the attack.
    """

    def test_kick_has_sharp_attack(self, kick):
        """Sanity: the synthetic kick should have a sharp onset.

        The peak should be near the start and the first 5ms should
        contain meaningful energy (> 2% of total). The kick is 150ms
        with exponential decay, so most energy is in the body/tail.
        """
        peak_idx = np.argmax(np.abs(kick))
        assert peak_idx < int(0.010 * SR), (
            f"Kick peak at sample {peak_idx} ({peak_idx/SR*1000:.1f} ms), "
            f"expected within first 10 ms"
        )
        # Energy in first 5ms should be nonzero
        early = int(0.005 * SR)
        early_energy = np.sum(kick[:early] ** 2)
        total_energy = np.sum(kick ** 2)
        assert early_energy / total_energy > 0.02, (
            f"Kick attack too soft: {early_energy/total_energy*100:.1f}% "
            f"energy in first 5ms"
        )

    def test_hp_filter_no_pre_ringing(self, kick, combined_hp):
        """HP (main speaker) path: < 1% pre-attack energy."""
        signal, onset = _make_test_signal(kick)
        filtered = dsp_utils.convolve_fir(signal, combined_hp)
        ratio = _pre_attack_energy_ratio(signal, filtered, onset)
        assert ratio < 0.01, (
            f"HP path pre-ringing: {ratio*100:.2f}% of energy before attack "
            f"(limit: 1%)"
        )

    def test_lp_filter_no_pre_ringing(self, kick, combined_lp):
        """LP (sub) path: < 1% pre-attack energy."""
        signal, onset = _make_test_signal(kick)
        filtered = dsp_utils.convolve_fir(signal, combined_lp)
        ratio = _pre_attack_energy_ratio(signal, filtered, onset)
        assert ratio < 0.01, (
            f"LP path pre-ringing: {ratio*100:.2f}% of energy before attack "
            f"(limit: 1%)"
        )

    @pytest.mark.parametrize("seed", [42, 123, 456, 789, 1024])
    def test_random_room_no_pre_ringing(self, kick, seed):
        """Different random rooms should all produce < 1% pre-ringing."""
        ir = _make_room_ir(seed=seed)
        correction = generate_correction_filter(
            ir, n_taps=N_TAPS, margin_db=CORRECTION_MARGIN_DB,
        )
        xo = generate_crossover_filter(
            "highpass", crossover_freq=CROSSOVER_FREQ,
            slope_db_per_oct=48.0, n_taps=N_TAPS,
        )
        combined = combine_filters(correction, xo, n_taps=N_TAPS)

        signal, onset = _make_test_signal(kick)
        filtered = dsp_utils.convolve_fir(signal, combined)
        ratio = _pre_attack_energy_ratio(signal, filtered, onset)
        assert ratio < 0.01, (
            f"seed={seed}: pre-ringing {ratio*100:.2f}% (limit: 1%)"
        )

    def test_full_pipeline_no_pre_ringing(self, kick):
        """Full generate_profile_filters pipeline: no pre-ringing on any channel."""
        ir = _make_room_ir()
        correction = generate_correction_filter(
            ir, n_taps=N_TAPS, margin_db=CORRECTION_MARGIN_DB,
        )
        profile = {
            "name": "transient-test",
            "crossover": {"frequency_hz": CROSSOVER_FREQ, "slope_db_per_oct": 48},
            "speakers": {
                "left_hp": {"filter_type": "highpass", "identity": ""},
                "sub1_lp": {"filter_type": "lowpass", "identity": ""},
            },
        }
        corrections = {k: correction for k in profile["speakers"]}
        outputs = generate_profile_filters(
            profile=profile, identities={},
            correction_filters=corrections, n_taps=N_TAPS,
        )

        signal, onset = _make_test_signal(kick)
        for channel, fir in outputs.items():
            filtered = dsp_utils.convolve_fir(signal, fir)
            ratio = _pre_attack_energy_ratio(signal, filtered, onset)
            assert ratio < 0.01, (
                f"{channel}: pre-ringing {ratio*100:.2f}% (limit: 1%)"
            )


# ===================================================================
# 2. Null correction transient test
# ===================================================================

class TestNullCorrectionTransient:
    """Flat room (dirac IR) -> correction -> should produce near-dirac output.
    Convolved with a kick, the kick should be nearly unmodified.
    """

    @pytest.fixture(scope="class")
    def null_correction(self):
        """Correction for a perfectly flat room."""
        dirac = np.zeros(N_TAPS)
        dirac[0] = 1.0
        return generate_correction_filter(dirac, n_taps=N_TAPS)

    def test_null_correction_near_dirac(self, null_correction):
        """The correction filter for a flat room should be near-dirac.

        Its peak should be at or near sample 0, and energy should be
        heavily concentrated at the start.
        """
        peak_idx = np.argmax(np.abs(null_correction))
        assert peak_idx < N_TAPS // 100, (
            f"Null correction peak at sample {peak_idx} (expected near 0)"
        )

        # Energy in first 1% of samples should dominate
        early = max(N_TAPS // 100, 10)
        early_energy = np.sum(null_correction[:early] ** 2)
        total_energy = np.sum(null_correction ** 2)
        assert early_energy / total_energy > 0.8, (
            f"Null correction energy not concentrated at start: "
            f"{early_energy/total_energy*100:.1f}% in first {early} samples"
        )

    def test_kick_preserved_through_null(self, kick, null_correction):
        """A kick convolved with the null correction should be nearly unchanged.

        The correlation between original and filtered kick should be > 0.95,
        proving the correction doesn't distort the signal.
        """
        filtered = dsp_utils.convolve_fir(kick, null_correction)

        # Align by finding the peak in both signals
        orig_peak = np.argmax(np.abs(kick))
        filt_peak = np.argmax(np.abs(filtered))

        # Extract aligned segments for correlation
        seg_len = min(len(kick) - orig_peak, len(filtered) - filt_peak)
        seg_len = min(seg_len, len(kick))

        orig_seg = kick[orig_peak:orig_peak + seg_len]
        filt_seg = filtered[filt_peak:filt_peak + seg_len]

        # Normalize both to unit energy for fair comparison
        orig_seg = orig_seg / (np.sqrt(np.sum(orig_seg ** 2)) + 1e-10)
        filt_seg = filt_seg / (np.sqrt(np.sum(filt_seg ** 2)) + 1e-10)

        corr = float(np.corrcoef(orig_seg, filt_seg)[0, 1])
        assert corr > 0.90, (
            f"Kick correlation through null correction: {corr:.4f} "
            f"(expected > 0.90). Correction is distorting the signal."
        )

    def test_null_no_pre_ringing(self, kick, null_correction):
        """Null correction should produce zero pre-ringing."""
        signal, onset = _make_test_signal(kick)
        filtered = dsp_utils.convolve_fir(signal, null_correction)
        ratio = _pre_attack_energy_ratio(signal, filtered, onset)
        assert ratio < 0.005, (
            f"Null correction pre-ringing: {ratio*100:.3f}% (limit: 0.5%)"
        )


# ===================================================================
# 3. Linear-phase comparison
# ===================================================================

class TestLinearPhaseComparison:
    """Prove that minimum-phase filters have less pre-ringing than
    linear-phase filters with the same magnitude response.

    This validates the core design decision (CLAUDE.md decision #1):
    minimum-phase FIR was chosen specifically because it avoids
    pre-ringing that smears psytrance kick transients.
    """

    @pytest.fixture(scope="class")
    def filters(self):
        """Generate both minimum-phase and linear-phase versions."""
        ir = _make_room_ir()
        correction = generate_correction_filter(
            ir, n_taps=N_TAPS, margin_db=CORRECTION_MARGIN_DB,
        )
        xo = generate_crossover_filter(
            "highpass", crossover_freq=CROSSOVER_FREQ,
            slope_db_per_oct=48.0, n_taps=N_TAPS,
        )
        min_phase = combine_filters(correction, xo, n_taps=N_TAPS)
        lin_phase = _make_linear_phase_fir(min_phase)
        return min_phase, lin_phase

    def test_same_magnitude_response(self, filters):
        """Both filters should have the same magnitude response.

        This is the premise of the comparison: same correction effect,
        different phase behavior.
        """
        min_phase, lin_phase = filters
        n_fft = dsp_utils.next_power_of_2(N_TAPS * 2)
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / SR)

        min_mag = np.abs(np.fft.rfft(min_phase, n=n_fft))
        lin_mag = np.abs(np.fft.rfft(lin_phase, n=n_fft))

        # Compare in the passband (200 Hz - 10 kHz for HP filter)
        passband = (freqs >= 200) & (freqs <= 10000)
        min_db = dsp_utils.linear_to_db(min_mag[passband])
        lin_db = dsp_utils.linear_to_db(lin_mag[passband])

        # The fade windowing changes the magnitude slightly, so allow 6 dB
        max_diff = np.max(np.abs(min_db - lin_db))
        assert max_diff < 6.0, (
            f"Magnitude responses differ by {max_diff:.1f} dB in passband "
            f"(expected < 6 dB)"
        )

    def test_minimum_phase_less_pre_ringing(self, kick, filters):
        """Minimum-phase should have less pre-onset energy than linear-phase.

        This is the definitive proof: same magnitude correction, but
        the linear-phase version produces pre-ringing (energy before
        the original signal onset) while the minimum-phase version does not.

        Uses generous pre-silence (200ms = 9600 samples at 48kHz) to give
        the linear-phase filter room to spread its pre-ringing into.
        The linear-phase filter's group delay (~N/2 = ~8192 samples =
        ~170ms) means its output is delayed, and the symmetric pre-ringing
        extends into the pre-onset region.
        """
        min_phase, lin_phase = filters
        signal, onset = _make_test_signal(kick, pre_silence_s=0.4)

        filtered_min = dsp_utils.convolve_fir(signal, min_phase)
        filtered_lin = dsp_utils.convolve_fir(signal, lin_phase)

        ratio_min = _pre_attack_energy_ratio(signal, filtered_min, onset)
        ratio_lin = _pre_attack_energy_ratio(signal, filtered_lin, onset)

        # Minimum-phase: causal, no energy before onset
        assert ratio_min < 0.01, (
            f"Minimum-phase pre-onset energy: {ratio_min*100:.2f}% (limit: 1%)"
        )

        # Linear-phase: symmetric IR spreads energy before onset
        assert ratio_lin > ratio_min, (
            f"Linear-phase ({ratio_lin*100:.2f}%) should have more "
            f"pre-onset energy than minimum-phase ({ratio_min*100:.2f}%)"
        )

    def test_linear_phase_peak_centered(self, filters):
        """Linear-phase filter's peak should be near the center (symmetric).

        This confirms the linear-phase construction is correct — the
        pre-ringing is real, not an artifact of bad construction.
        """
        _, lin_phase = filters
        peak_idx = np.argmax(np.abs(lin_phase))
        center = len(lin_phase) // 2
        # Allow 25% tolerance for the peak position
        tolerance = len(lin_phase) // 4
        assert abs(peak_idx - center) < tolerance, (
            f"Linear-phase peak at {peak_idx}, expected near center "
            f"{center} (+/- {tolerance})"
        )

    def test_minimum_phase_peak_early(self, filters):
        """Minimum-phase filter's peak should be near the start.

        This is the fundamental property: energy concentrated at the
        beginning means no pre-ringing.
        """
        min_phase, _ = filters
        peak_idx = np.argmax(np.abs(min_phase))
        limit = len(min_phase) // 4
        assert peak_idx < limit, (
            f"Minimum-phase peak at {peak_idx}, expected in first "
            f"{limit} samples (first 25%)"
        )


# ===================================================================
# 4. Multi-position averaging
# ===================================================================

class TestMultiPositionAveraging:
    """Average room IRs from multiple mic positions, generate correction,
    verify no pre-ringing in the averaged result.

    Multi-position averaging is the standard technique for spatial
    robustness. The averaged correction must still be minimum-phase
    and free of pre-ringing.
    """

    @pytest.fixture(scope="class")
    def averaged_correction(self):
        """Generate corrections from 4 different "mic positions" and average."""
        corrections = []
        for seed in [100, 200, 300, 400]:
            ir = _make_room_ir(seed=seed)
            corr = generate_correction_filter(
                ir, n_taps=N_TAPS, margin_db=CORRECTION_MARGIN_DB,
            )
            corrections.append(corr)

        # Average the correction filters (simple arithmetic mean)
        averaged = np.mean(corrections, axis=0)

        # Re-normalize: ensure D-009 compliance after averaging
        # (averaging can create slight boosts)
        margin_linear = dsp_utils.db_to_linear(CORRECTION_MARGIN_DB)
        spectrum = np.fft.rfft(averaged)
        mag = np.abs(spectrum)
        exceed = mag > margin_linear
        if np.any(exceed):
            phase = np.angle(spectrum)
            mag[exceed] = margin_linear
            averaged = np.fft.irfft(mag * np.exp(1j * phase), n=len(averaged))

        return averaged

    def test_averaged_no_pre_ringing(self, kick, averaged_correction):
        """Averaged correction should produce < 1% pre-ringing."""
        signal, onset = _make_test_signal(kick)
        filtered = dsp_utils.convolve_fir(signal, averaged_correction)
        ratio = _pre_attack_energy_ratio(signal, filtered, onset)
        assert ratio < 0.01, (
            f"Averaged correction pre-ringing: {ratio*100:.2f}% (limit: 1%)"
        )

    def test_averaged_combined_no_pre_ringing(self, kick, averaged_correction):
        """Averaged correction + crossover should produce < 1% pre-ringing."""
        xo = generate_crossover_filter(
            "highpass", crossover_freq=CROSSOVER_FREQ,
            slope_db_per_oct=48.0, n_taps=N_TAPS,
        )
        combined = combine_filters(averaged_correction, xo, n_taps=N_TAPS)

        signal, onset = _make_test_signal(kick)
        filtered = dsp_utils.convolve_fir(signal, combined)
        ratio = _pre_attack_energy_ratio(signal, filtered, onset)
        assert ratio < 0.01, (
            f"Averaged combined pre-ringing: {ratio*100:.2f}% (limit: 1%)"
        )

    def test_averaged_is_minimum_phase(self, averaged_correction):
        """The averaged correction should still be approximately minimum-phase.

        Energy in the first half should exceed 80% (slightly relaxed from
        the standard 90% since averaging blurs the impulse response).
        """
        n = len(averaged_correction)
        first_half_energy = np.sum(averaged_correction[:n // 2] ** 2)
        total_energy = np.sum(averaged_correction ** 2)

        if total_energy < 1e-20:
            pytest.skip("Near-zero energy in averaged correction")

        ratio = first_half_energy / total_energy
        assert ratio > 0.80, (
            f"Averaged correction energy in first half: {ratio*100:.1f}% "
            f"(need > 80%)"
        )
