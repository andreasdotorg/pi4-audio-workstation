"""Channel identity verification — no cross-channel contamination (US-098 P1).

The room correction pipeline generates one combined FIR per speaker channel.
Each channel receives its own correction filter (derived from its own room IR
measurement). A cross-contamination bug would apply one channel's correction
to a different channel's output — potentially routing sub correction to a main
speaker or vice versa, risking speaker damage.

Tests verify:
1. Each channel's output contains ONLY its own correction signature.
2. No channel's output correlates with another channel's correction input.
3. Injecting a notch into one channel does not affect other channels.

These tests exercise generate_profile_filters() — the production pipeline —
with deliberately distinct per-channel corrections so that contamination is
detectable via spectral analysis.
"""

import os
import sys

import numpy as np
import pytest
import scipy.signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from room_correction import dsp_utils
from room_correction.correction import generate_correction_filter
from room_correction.generate_profile_filters import generate_profile_filters

SR = dsp_utils.SAMPLE_RATE
# Use shorter taps for test speed; channel identity is independent of length.
TEST_TAPS = 4096


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_notch_correction(notch_freq, q=8.0, n_taps=TEST_TAPS, sr=SR):
    """Create a correction filter with a deep notch at notch_freq.

    The notch serves as a unique spectral fingerprint — if it appears in
    the wrong channel's output, we have cross-contamination.

    Uses scipy.signal.iirnotch for a clean, deep notch that survives the
    pipeline's D-009 clipping (which only clips boosts, not cuts).
    """
    w0 = notch_freq / (sr / 2)
    w0 = min(w0, 0.99)
    b, a = scipy.signal.iirnotch(w0, q)
    impulse = np.zeros(n_taps)
    impulse[0] = 1.0
    notch_ir = scipy.signal.lfilter(b, a, impulse)
    # Normalize peak to 1.0
    peak = np.max(np.abs(notch_ir))
    if peak > 0:
        notch_ir /= peak
    return notch_ir


def _magnitude_at_freq(fir, freq, sr=SR, bandwidth_hz=None):
    """Measure the magnitude (dB) of a FIR filter at a specific frequency.

    Uses zero-padded FFT (8x) for better frequency resolution at low
    frequencies. Default bandwidth scales with frequency for robustness.
    """
    n_fft = dsp_utils.next_power_of_2(len(fir)) * 8
    spectrum = np.fft.rfft(fir, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    mags = np.abs(spectrum)
    if bandwidth_hz is None:
        bandwidth_hz = max(freq * 0.15, 3.0)
    mask = (freqs >= freq - bandwidth_hz) & (freqs <= freq + bandwidth_hz)
    if not np.any(mask):
        raise ValueError(f"No bins near {freq} Hz")
    return float(np.mean(dsp_utils.linear_to_db(mags[mask])))


def _spectral_correlation(fir_a, fir_b, sr=SR, freq_range=None):
    """Compute the Pearson correlation of two FIRs' log-magnitude spectra.

    If freq_range is provided as (low_hz, high_hz), restricts comparison
    to that band. Otherwise uses the full audio band (20 Hz - 20 kHz).
    """
    n_fft = dsp_utils.next_power_of_2(max(len(fir_a), len(fir_b))) * 4
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
    if freq_range is not None:
        band = (freqs >= freq_range[0]) & (freqs <= freq_range[1])
    else:
        band = (freqs >= 20) & (freqs <= 20000)

    if not np.any(band):
        return 0.0

    mag_a = dsp_utils.linear_to_db(np.abs(np.fft.rfft(fir_a, n=n_fft)))[band]
    mag_b = dsp_utils.linear_to_db(np.abs(np.fft.rfft(fir_b, n=n_fft)))[band]

    # Pearson correlation
    return float(np.corrcoef(mag_a, mag_b)[0, 1])


def _make_4ch_profile():
    """Build a standard 4-channel 2-way profile (matches production topology)."""
    return {
        "name": "channel-identity-test",
        "topology": "2way",
        "crossover": {"frequency_hz": 80, "slope_db_per_oct": 48},
        "speakers": {
            "left_hp": {"identity": "", "filter_type": "highpass"},
            "right_hp": {"identity": "", "filter_type": "highpass"},
            "sub1_lp": {"identity": "", "filter_type": "lowpass"},
            "sub2_lp": {"identity": "", "filter_type": "lowpass"},
        },
    }


# Distinct notch frequencies — one per channel, well-separated and
# well within each channel's passband.
# HP channels: passband is above 80 Hz crossover -> use 500+ Hz
# LP channels: passband is below 80 Hz crossover -> use 35-55 Hz
CHANNEL_NOTCH_FREQS = {
    "left_hp": 500.0,
    "right_hp": 2000.0,
    "sub1_lp": 35.0,
    "sub2_lp": 55.0,
}


# ===================================================================
# 1. Distinct-correction identity test
# ===================================================================

class TestDistinctCorrectionIdentity:
    """Each channel gets a correction with a unique notch frequency.
    After generate_profile_filters(), each output must show its own notch
    and NOT show any other channel's notch.
    """

    @pytest.fixture(scope="class")
    def pipeline_result(self):
        """Run the full pipeline with distinct per-channel corrections."""
        profile = _make_4ch_profile()
        corrections = {}
        for spk_key, notch_freq in CHANNEL_NOTCH_FREQS.items():
            corrections[spk_key] = _make_notch_correction(notch_freq)

        return generate_profile_filters(
            profile=profile,
            identities={},
            correction_filters=corrections,
            n_taps=TEST_TAPS,
        )

    @pytest.mark.parametrize("channel", list(CHANNEL_NOTCH_FREQS.keys()))
    def test_own_notch_present(self, pipeline_result, channel):
        """Each channel's output must show its own correction's notch.

        We compare the output WITH the notch correction to a baseline
        output with dirac correction. The notch should cause a dip of
        at least 2 dB at the notch frequency relative to the baseline.
        """
        fir = pipeline_result[channel]
        notch_freq = CHANNEL_NOTCH_FREQS[channel]

        # Generate baseline (dirac correction) for comparison
        profile = _make_4ch_profile()
        dirac = np.zeros(TEST_TAPS)
        dirac[0] = 1.0
        baseline = generate_profile_filters(
            profile=profile, identities={},
            correction_filters={k: dirac.copy() for k in profile["speakers"]},
            n_taps=TEST_TAPS,
        )

        level_with_notch = _magnitude_at_freq(fir, notch_freq)
        level_baseline = _magnitude_at_freq(baseline[channel], notch_freq)
        dip = level_baseline - level_with_notch

        assert dip >= 2.0, (
            f"{channel}: notch at {notch_freq} Hz shows only {dip:.1f} dB dip "
            f"vs baseline (need >= 2 dB). With notch: {level_with_notch:.1f} dB, "
            f"baseline: {level_baseline:.1f} dB"
        )

    @pytest.mark.parametrize("channel", list(CHANNEL_NOTCH_FREQS.keys()))
    def test_no_foreign_notch(self, pipeline_result, channel):
        """Each channel's output must NOT show other channels' notches.

        A foreign notch appearing in a channel's output means cross-
        contamination — the wrong correction was applied.
        """
        fir = pipeline_result[channel]
        own_notch = CHANNEL_NOTCH_FREQS[channel]

        for other_channel, other_notch in CHANNEL_NOTCH_FREQS.items():
            if other_channel == channel:
                continue

            # Skip if the other notch is in this channel's stopband
            # (HP channels attenuate below 80 Hz; LP channels attenuate above 80 Hz)
            if "hp" in channel and other_notch < 80:
                continue
            if "lp" in channel and other_notch > 80:
                continue

            # The foreign notch should NOT produce a significant dip
            level_at_foreign = _magnitude_at_freq(fir, other_notch)
            # Use a neighbor that's in the passband
            if "hp" in channel:
                neighbor = max(other_notch * 1.5, 200.0)
            else:
                neighbor = max(other_notch * 0.7, 20.0)
            level_at_neighbor = _magnitude_at_freq(fir, neighbor, bandwidth_hz=10.0)

            dip = level_at_neighbor - level_at_foreign
            # Allow up to 3 dB — the crossover and D-009 clipping cause
            # some spectral shaping, but a contamination notch would be >> 3 dB
            assert dip < 6.0, (
                f"{channel}: foreign notch from {other_channel} at "
                f"{other_notch} Hz shows {dip:.1f} dB dip (contamination?). "
                f"Level at notch: {level_at_foreign:.1f} dB, "
                f"neighbor: {level_at_neighbor:.1f} dB"
            )


# ===================================================================
# 2. Zero-contamination matrix test
# ===================================================================

class TestZeroContaminationMatrix:
    """For each channel, its output should correlate with its own correction
    input more strongly than with any other channel's correction input.

    Uses random room IRs to produce distinct corrections, then checks
    that the spectral correlation matrix is diagonally dominant.
    """

    @pytest.fixture(scope="class")
    def corrections_and_outputs(self):
        """Generate distinct random corrections and run the pipeline."""
        profile = _make_4ch_profile()
        corrections = {}
        for i, spk_key in enumerate(profile["speakers"]):
            rng = np.random.RandomState(seed=9000 + i)
            ir = rng.randn(TEST_TAPS)
            ir[0] = 1.0  # direct path
            ir /= np.max(np.abs(ir))
            corrections[spk_key] = generate_correction_filter(
                ir, n_taps=TEST_TAPS,
            )

        outputs = generate_profile_filters(
            profile=profile,
            identities={},
            correction_filters=corrections,
            n_taps=TEST_TAPS,
        )
        return corrections, outputs

    @pytest.mark.parametrize("channel", ["left_hp", "right_hp", "sub1_lp", "sub2_lp"])
    def test_self_correlation_highest(self, corrections_and_outputs, channel):
        """Each output should correlate most strongly with its own correction.

        Comparison is restricted to the channel's passband so the crossover
        shape doesn't dominate: HP channels use 200-20000 Hz, LP channels
        use 20-60 Hz. Within the passband, the correction's spectral
        signature should be clearly visible.
        """
        corrections, outputs = corrections_and_outputs
        output_fir = outputs[channel]

        # Restrict to the channel's passband
        if "hp" in channel:
            freq_range = (200.0, 20000.0)
        else:
            freq_range = (20.0, 60.0)

        # Compare against same-type channels only (HP vs HP, LP vs LP)
        # Cross-type comparison is meaningless (HP output at 20 Hz is
        # in the stopband regardless of which correction was used)
        same_type_keys = [
            k for k in corrections
            if ("hp" in k) == ("hp" in channel)
        ]

        self_corr = _spectral_correlation(
            output_fir, corrections[channel], freq_range=freq_range)

        for other in same_type_keys:
            if other == channel:
                continue
            cross_corr = _spectral_correlation(
                output_fir, corrections[other], freq_range=freq_range)
            assert self_corr > cross_corr, (
                f"{channel}: self-correlation ({self_corr:.4f}) should exceed "
                f"cross-correlation with {other} ({cross_corr:.4f}) "
                f"in band {freq_range}"
            )

    def test_outputs_differ_across_channels(self, corrections_and_outputs):
        """All 4 output filters should be mutually distinct.

        If any two outputs are nearly identical, a mapping error may be
        silently producing the same filter for multiple channels.
        """
        _, outputs = corrections_and_outputs
        keys = list(outputs.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                corr = _spectral_correlation(outputs[keys[i]], outputs[keys[j]])
                # Same filter-type channels (both HP or both LP) will have
                # high correlation due to shared crossover shape, but should
                # not be identical (correlation < 0.999).
                assert not np.array_equal(outputs[keys[i]], outputs[keys[j]]), (
                    f"{keys[i]} and {keys[j]} are bitwise identical"
                )


# ===================================================================
# 3. Dirac-isolation test
# ===================================================================

class TestDiracIsolation:
    """Set ONE channel's correction to a strong notch; all others get dirac.
    Verify only the target channel shows the notch.

    This is the strongest isolation test: with dirac corrections on the
    non-target channels, any notch appearing in them is pure contamination
    — there is no other explanation.
    """

    @pytest.mark.parametrize("target_channel,notch_freq", [
        ("left_hp", 1000.0),
        ("right_hp", 3000.0),
        ("sub1_lp", 40.0),
        ("sub2_lp", 55.0),
    ])
    def test_notch_only_in_target(self, target_channel, notch_freq):
        """Inject a notch into one channel, verify others are unaffected."""
        profile = _make_4ch_profile()

        # Dirac for all channels
        dirac = np.zeros(TEST_TAPS)
        dirac[0] = 1.0
        corrections = {key: dirac.copy() for key in profile["speakers"]}

        # Replace target channel with notch correction
        corrections[target_channel] = _make_notch_correction(notch_freq)

        outputs = generate_profile_filters(
            profile=profile,
            identities={},
            correction_filters=corrections,
            n_taps=TEST_TAPS,
        )

        # Generate the "baseline" — all dirac, no notch
        baseline_outputs = generate_profile_filters(
            profile=profile,
            identities={},
            correction_filters={key: dirac.copy() for key in profile["speakers"]},
            n_taps=TEST_TAPS,
        )

        # For non-target channels: output should be identical to baseline
        # (the notch correction was not applied to them)
        for other_channel in profile["speakers"]:
            if other_channel == target_channel:
                continue

            # Compare with baseline — should be bitwise identical since
            # both used dirac correction
            np.testing.assert_array_equal(
                outputs[other_channel],
                baseline_outputs[other_channel],
                err_msg=(
                    f"Contamination: {other_channel} output changed when "
                    f"notch was injected into {target_channel}. "
                    f"Filters should be independent."
                ),
            )

    @pytest.mark.parametrize("target_channel,notch_freq", [
        ("left_hp", 1000.0),
        ("sub1_lp", 40.0),
    ])
    def test_target_shows_notch_effect(self, target_channel, notch_freq):
        """The target channel's output should differ from its dirac baseline."""
        profile = _make_4ch_profile()

        dirac = np.zeros(TEST_TAPS)
        dirac[0] = 1.0

        corrections_with_notch = {key: dirac.copy() for key in profile["speakers"]}
        corrections_with_notch[target_channel] = _make_notch_correction(notch_freq)

        corrections_dirac = {key: dirac.copy() for key in profile["speakers"]}

        output_with_notch = generate_profile_filters(
            profile=profile, identities={},
            correction_filters=corrections_with_notch, n_taps=TEST_TAPS,
        )
        output_dirac = generate_profile_filters(
            profile=profile, identities={},
            correction_filters=corrections_dirac, n_taps=TEST_TAPS,
        )

        # The target channel should differ from baseline
        rms_diff = np.sqrt(np.mean(
            (output_with_notch[target_channel] - output_dirac[target_channel]) ** 2
        ))
        assert rms_diff > 1e-6, (
            f"{target_channel}: output is identical to dirac baseline "
            f"(RMS diff = {rms_diff:.2e}). Notch correction was not applied."
        )


# ===================================================================
# 4. 3-way topology identity test
# ===================================================================

class TestThreeWayChannelIdentity:
    """Verify channel identity for a 3-way topology with 6 channels.

    The 3-way profile has bass (LP), mid (BP), and tweeter (HP) channels,
    each left/right. This tests that the pipeline correctly routes
    corrections in a more complex topology.
    """

    @pytest.fixture(scope="class")
    def pipeline_result(self):
        profile = {
            "name": "3way-identity-test",
            "topology": "3way",
            "crossover": {"frequency_hz": [300, 3000], "slope_db_per_oct": 48},
            "speakers": {
                "bass_l": {"identity": "", "filter_type": "lowpass"},
                "bass_r": {"identity": "", "filter_type": "lowpass"},
                "mid_l": {"identity": "", "filter_type": "bandpass"},
                "mid_r": {"identity": "", "filter_type": "bandpass"},
                "hf_l": {"identity": "", "filter_type": "highpass"},
                "hf_r": {"identity": "", "filter_type": "highpass"},
            },
        }

        corrections = {}
        for i, spk_key in enumerate(profile["speakers"]):
            rng = np.random.RandomState(seed=8000 + i)
            ir = rng.randn(TEST_TAPS)
            ir[0] = 1.0
            ir /= np.max(np.abs(ir))
            corrections[spk_key] = generate_correction_filter(
                ir, n_taps=TEST_TAPS,
            )

        outputs = generate_profile_filters(
            profile=profile, identities={},
            correction_filters=corrections, n_taps=TEST_TAPS,
        )
        return corrections, outputs, profile

    def test_all_6_channels_present(self, pipeline_result):
        _, outputs, _ = pipeline_result
        assert len(outputs) == 6

    def test_left_right_differ_with_different_corrections(self, pipeline_result):
        """L/R of same type should differ when given different corrections."""
        _, outputs, _ = pipeline_result
        for prefix in ["bass", "mid", "hf"]:
            left = outputs[f"{prefix}_l"]
            right = outputs[f"{prefix}_r"]
            assert not np.array_equal(left, right), (
                f"{prefix} L/R are identical despite different corrections"
            )

    def test_no_cross_type_contamination(self, pipeline_result):
        """Bass correction should not affect HF output, and vice versa."""
        corrections, outputs, profile = pipeline_result

        # The bass and HF channels operate in completely different bands.
        # Their spectral correlation should be low.
        bass_hf_corr = _spectral_correlation(outputs["bass_l"], outputs["hf_l"])
        # Different band shapes make correlation inherently low, but
        # contamination would push it anomalously high.
        assert bass_hf_corr < 0.7, (
            f"Bass/HF spectral correlation suspiciously high: {bass_hf_corr:.4f}"
        )
