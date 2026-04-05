"""Dual-FFT transfer function engine (US-120).

SMAART-style cross-spectrum computation using Welch's method with exponential
averaging. Computes transfer function H(f) = Gxy/Gxx, magnitude-squared
coherence Cxy = |Gxy|^2 / (Gxx * Gyy), and wrapped phase.

Used by the /ws/transfer-function WebSocket endpoint. The engine is pure
computation — it accepts numpy arrays and returns results. No I/O, no
networking.

Audio Engineer consultation (session 13):
- Hann window (standard for SMAART-style TF)
- alpha=0.125 default (8-block equivalent)
- Wrapped phase (+/-180 degrees), hidden where Cxy < 0.5
- Coherence meaningful after 8+ averaged blocks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# Sample rate used for frequency axis computation.
DEFAULT_SAMPLE_RATE = 48000

# Minimum number of averaged blocks before coherence is considered valid.
MIN_COHERENCE_BLOCKS = 8

# Coherence threshold below which phase is not reported (AE consultation).
PHASE_COHERENCE_GATE = 0.5

# Numerical floor to prevent division by zero in spectral computations.
_EPS = 1e-30


@dataclass
class TransferFunctionConfig:
    """Configuration for the cross-spectrum engine."""
    fft_size: int = 4096
    overlap: float = 0.5
    alpha: float = 0.125
    sample_rate: int = DEFAULT_SAMPLE_RATE

    @property
    def hop_size(self) -> int:
        return int(self.fft_size * (1.0 - self.overlap))

    @property
    def n_bins(self) -> int:
        """Number of positive-frequency FFT bins (including DC and Nyquist)."""
        return self.fft_size // 2 + 1

    def freq_axis(self) -> np.ndarray:
        """Return frequency axis in Hz for the positive-frequency bins."""
        return np.fft.rfftfreq(self.fft_size, d=1.0 / self.sample_rate)


@dataclass
class TransferFunctionResult:
    """Result of a transfer function computation."""
    magnitude_db: np.ndarray
    phase_deg: np.ndarray
    coherence: np.ndarray
    freq_axis: np.ndarray
    blocks_accumulated: int
    delay_samples: int

    def to_json_dict(self, channel: int = 0) -> dict:
        """Serialize to the JSON frame format for the WebSocket endpoint.

        Phase values are set to None (JSON null) where coherence < PHASE_COHERENCE_GATE,
        per AE consultation: "display phase only where coherence exceeds threshold."
        """
        phase = self.phase_deg.copy()
        low_coherence = self.coherence < PHASE_COHERENCE_GATE
        phase_list = [
            None if low_coherence[i] else float(round(phase[i], 1))
            for i in range(len(phase))
        ]
        return {
            "magnitude_db": [float(round(v, 2)) for v in self.magnitude_db],
            "phase_deg": phase_list,
            "coherence": [float(round(v, 4)) for v in self.coherence],
            "freq_axis": [float(round(v, 1)) for v in self.freq_axis],
            "channel": channel,
            "blocks_accumulated": self.blocks_accumulated,
            "delay_samples": self.delay_samples,
            "warming_up": self.blocks_accumulated < MIN_COHERENCE_BLOCKS,
        }


class TransferFunctionEngine:
    """Dual-FFT cross-spectrum engine using Welch's method.

    Accepts time-domain blocks of reference (x) and measurement (y) audio.
    Accumulates cross-spectral density Gxy and auto-spectral densities Gxx, Gyy
    using exponential averaging. Computes transfer function and coherence on demand.
    """

    def __init__(self, config: Optional[TransferFunctionConfig] = None) -> None:
        self._config = config or TransferFunctionConfig()
        n = self._config.n_bins

        # Accumulated spectral densities (complex for Gxy, real for Gxx/Gyy).
        self._gxy: np.ndarray = np.zeros(n, dtype=np.complex128)
        self._gxx: np.ndarray = np.zeros(n, dtype=np.float64)
        self._gyy: np.ndarray = np.zeros(n, dtype=np.float64)

        # Block counter for warming-up detection.
        self._blocks: int = 0

        # Pre-computed Hann window.
        self._window: np.ndarray = np.hanning(self._config.fft_size)

        # Window power correction factor for spectral density normalization.
        # sum(w^2) / N gives the noise power bandwidth correction.
        self._window_power: float = float(
            np.sum(self._window ** 2) / self._config.fft_size)

        # Delay compensation (set by the delay finder, in samples).
        self._delay_samples: int = 0

        # Overlap buffer: stores the last (fft_size - hop_size) samples from
        # each stream for the next overlapping block.
        self._ref_overlap: np.ndarray = np.array([], dtype=np.float64)
        self._meas_overlap: np.ndarray = np.array([], dtype=np.float64)

    @property
    def config(self) -> TransferFunctionConfig:
        return self._config

    @property
    def blocks_accumulated(self) -> int:
        return self._blocks

    @property
    def delay_samples(self) -> int:
        return self._delay_samples

    @delay_samples.setter
    def delay_samples(self, value: int) -> None:
        self._delay_samples = value

    def reset(self) -> None:
        """Reset all accumulated spectral state."""
        n = self._config.n_bins
        self._gxy = np.zeros(n, dtype=np.complex128)
        self._gxx = np.zeros(n, dtype=np.float64)
        self._gyy = np.zeros(n, dtype=np.float64)
        self._blocks = 0
        self._ref_overlap = np.array([], dtype=np.float64)
        self._meas_overlap = np.array([], dtype=np.float64)
        log.debug("TransferFunctionEngine reset")

    def set_alpha(self, alpha: float) -> None:
        """Update the exponential averaging alpha (0 < alpha <= 1)."""
        if not 0 < alpha <= 1:
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        self._config.alpha = alpha

    def process_block(self, ref: np.ndarray, meas: np.ndarray) -> int:
        """Process a block of time-domain audio from both streams.

        Extracts overlapping FFT windows from the input, applies Hann window,
        computes FFT, and accumulates cross/auto spectral densities.

        The input arrays may be any length >= 1 sample. Internal overlap
        buffering handles partial blocks.

        Parameters
        ----------
        ref : array of float64, shape (N,)
            Reference signal (post-convolver tap).
        meas : array of float64, shape (N,)
            Measurement signal (UMIK-1).

        Returns
        -------
        int
            Number of FFT blocks processed from this input.
        """
        fft_size = self._config.fft_size
        hop = self._config.hop_size

        # Prepend overlap from previous call.
        ref_buf = np.concatenate([self._ref_overlap, ref])
        meas_buf = np.concatenate([self._meas_overlap, meas])

        # Use the shorter of the two to ensure alignment.
        available = min(len(ref_buf), len(meas_buf))
        blocks_processed = 0
        pos = 0

        while pos + fft_size <= available:
            x_block = ref_buf[pos:pos + fft_size]
            y_block = meas_buf[pos:pos + fft_size]
            self._accumulate_spectra(x_block, y_block)
            blocks_processed += 1
            pos += hop

        # Save remaining samples for next call.
        self._ref_overlap = ref_buf[pos:].copy()
        self._meas_overlap = meas_buf[pos:].copy()

        return blocks_processed

    def _accumulate_spectra(self, x: np.ndarray, y: np.ndarray) -> None:
        """Accumulate one windowed FFT block into the spectral densities.

        Uses exponential averaging:
            Gxy = alpha * X * conj(Y) + (1 - alpha) * Gxy_old
            Gxx = alpha * |X|^2 + (1 - alpha) * Gxx_old
            Gyy = alpha * |Y|^2 + (1 - alpha) * Gyy_old
        """
        alpha = self._config.alpha

        # Window and FFT.
        xw = x * self._window
        yw = y * self._window
        X = np.fft.rfft(xw)
        Y = np.fft.rfft(yw)

        # Cross and auto spectral densities for this block.
        xy = X * np.conj(Y)
        xx = np.abs(X) ** 2
        yy = np.abs(Y) ** 2

        if self._blocks == 0:
            # First block: initialize directly (no old data to blend with).
            self._gxy = xy.astype(np.complex128)
            self._gxx = xx.astype(np.float64)
            self._gyy = yy.astype(np.float64)
        else:
            self._gxy = alpha * xy + (1 - alpha) * self._gxy
            self._gxx = alpha * xx + (1 - alpha) * self._gxx
            self._gyy = alpha * yy + (1 - alpha) * self._gyy

        self._blocks += 1

    def compute(self) -> TransferFunctionResult:
        """Compute the current transfer function, coherence, and phase.

        Returns a TransferFunctionResult with:
        - magnitude_db: |H(f)| in dB
        - phase_deg: angle(H(f)) in degrees, wrapped to +/-180
        - coherence: Cxy(f) in [0, 1]
        - freq_axis: frequency values in Hz
        """
        freq_axis = self._config.freq_axis()

        if self._blocks == 0:
            n = self._config.n_bins
            return TransferFunctionResult(
                magnitude_db=np.full(n, -120.0),
                phase_deg=np.zeros(n),
                coherence=np.zeros(n),
                freq_axis=freq_axis,
                blocks_accumulated=0,
                delay_samples=self._delay_samples,
            )

        # Transfer function: H(f) = Gxy / Gxx
        gxx_safe = np.maximum(self._gxx, _EPS)
        H = self._gxy / gxx_safe

        # Magnitude in dB.
        magnitude = np.abs(H)
        magnitude_db = 20.0 * np.log10(np.maximum(magnitude, _EPS))

        # Wrapped phase in degrees.
        phase_deg = np.degrees(np.angle(H))

        # Magnitude-squared coherence: Cxy = |Gxy|^2 / (Gxx * Gyy)
        gyy_safe = np.maximum(self._gyy, _EPS)
        denominator = gxx_safe * gyy_safe
        coherence = np.abs(self._gxy) ** 2 / denominator
        # Clamp to [0, 1] — numerical errors can push slightly above 1.
        coherence = np.clip(coherence, 0.0, 1.0)

        return TransferFunctionResult(
            magnitude_db=magnitude_db,
            phase_deg=phase_deg,
            coherence=coherence,
            freq_axis=freq_axis,
            blocks_accumulated=self._blocks,
            delay_samples=self._delay_samples,
        )


class DelayFinder:
    """Cross-correlation based delay finder for time-aligning reference and
    measurement signals.

    Computes the propagation delay between reference (post-convolver) and
    measurement (UMIK-1) using cross-correlation peak detection.

    AE consultation: 200ms max range (9600 samples at 48kHz), 1-second
    correlation window (48000 samples).
    """

    def __init__(
        self,
        max_delay_samples: int = 9600,
        correlation_window: int = 48000,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> None:
        self._max_delay = max_delay_samples
        self._window = correlation_window
        self._sample_rate = sample_rate

        # Accumulation buffers.
        self._ref_buf: np.ndarray = np.array([], dtype=np.float64)
        self._meas_buf: np.ndarray = np.array([], dtype=np.float64)

        self._last_delay: int = 0
        self._confidence: float = 0.0

    @property
    def delay_samples(self) -> int:
        return self._last_delay

    @property
    def delay_ms(self) -> float:
        return self._last_delay / self._sample_rate * 1000.0

    @property
    def confidence(self) -> float:
        """Confidence of the last delay estimate (0-1, ratio of peak to RMS)."""
        return self._confidence

    def accumulate(self, ref: np.ndarray, meas: np.ndarray) -> None:
        """Add samples to the accumulation buffers.

        Keeps only the last `correlation_window` samples in each buffer.
        """
        self._ref_buf = np.concatenate([self._ref_buf, ref])
        self._meas_buf = np.concatenate([self._meas_buf, meas])

        # Trim to window size.
        if len(self._ref_buf) > self._window:
            self._ref_buf = self._ref_buf[-self._window:]
        if len(self._meas_buf) > self._window:
            self._meas_buf = self._meas_buf[-self._window:]

    def has_enough_data(self) -> bool:
        """Return True if enough data has been accumulated for a delay estimate."""
        return (len(self._ref_buf) >= self._window
                and len(self._meas_buf) >= self._window)

    def compute_delay(self) -> int:
        """Compute propagation delay via cross-correlation.

        Returns delay in samples (positive = measurement lags reference).
        Updates internal state with the result.
        """
        if not self.has_enough_data():
            return self._last_delay

        ref = self._ref_buf[-self._window:]
        meas = self._meas_buf[-self._window:]

        # Normalize to prevent numerical issues.
        ref_norm = ref - np.mean(ref)
        meas_norm = meas - np.mean(meas)

        ref_rms = np.sqrt(np.mean(ref_norm ** 2))
        meas_rms = np.sqrt(np.mean(meas_norm ** 2))
        if ref_rms < _EPS or meas_rms < _EPS:
            log.warning("DelayFinder: signal too quiet for delay estimation")
            return self._last_delay

        # Cross-correlation via FFT (much faster than direct for large windows).
        # Compute only for the search range [-max_delay, +max_delay].
        n_fft = 1
        while n_fft < len(ref) + self._max_delay:
            n_fft *= 2

        X = np.fft.rfft(ref_norm, n=n_fft)
        Y = np.fft.rfft(meas_norm, n=n_fft)
        xcorr_full = np.fft.irfft(np.conj(X) * Y, n=n_fft)

        # Extract the region of interest: delays [0, max_delay].
        # Positive delay means measurement is delayed relative to reference
        # (expected: sound travels from speaker to mic).
        positive_delays = xcorr_full[:self._max_delay + 1]

        # Also check small negative delays (mic closer than reference tap,
        # or timing offsets in the capture chain).
        negative_region = xcorr_full[-(self._max_delay):]
        search_region = np.concatenate([negative_region, positive_delays])
        offset = self._max_delay  # index offset so that index=offset means delay=0

        peak_idx = int(np.argmax(np.abs(search_region)))
        delay = peak_idx - offset

        # Confidence: ratio of peak correlation to RMS of the correlation.
        peak_val = abs(search_region[peak_idx])
        corr_rms = np.sqrt(np.mean(search_region ** 2))
        self._confidence = float(peak_val / max(corr_rms, _EPS))

        self._last_delay = delay
        log.info("DelayFinder: delay=%d samples (%.1fms), confidence=%.1f",
                 delay, delay / self._sample_rate * 1000.0, self._confidence)
        return delay
