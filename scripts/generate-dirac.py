#!/usr/bin/env python3
"""Generate 16384-sample Dirac impulse WAV files for the filter-chain convolver.

All files are mono 32-bit float WAVs at 48 kHz: sample[0] = 1.0, samples
1..16383 = 0.0.  Convolving with a Dirac impulse is the identity operation --
the signal passes through unchanged.

The 16384-tap length matches the speaker FIR channels so all 8 convolvers
share a uniform FFT partition size (D-063).

Usage:
    python scripts/generate-dirac.py <output_dir>

Creates:
    <output_dir>/dirac.wav               (shared identity, ch 5-8: HP/IEM)
    <output_dir>/combined_left_hp.wav     (passthrough default, ch 0)
    <output_dir>/combined_right_hp.wav    (passthrough default, ch 1)
    <output_dir>/combined_sub1_lp.wav     (passthrough default, ch 2)
    <output_dir>/combined_sub2_lp.wav     (passthrough default, ch 3)

The combined_*.wav passthrough defaults are overwritten by the measurement
pipeline with real crossover + room correction FIR coefficients.  dirac.wav
is the permanent identity coefficient for monitoring channels.
"""

import struct
import sys
from pathlib import Path

NUM_SAMPLES = 16384
SAMPLE_RATE = 48000

COEFF_NAMES = [
    "dirac.wav",
    "combined_left_hp.wav",
    "combined_right_hp.wav",
    "combined_sub1_lp.wav",
    "combined_sub2_lp.wav",
]


def write_dirac_wav(path: Path) -> None:
    """Write a 16384-sample float32 WAV (Dirac impulse: [1.0, 0, 0, ...])."""
    num_channels = 1
    bits_per_sample = 32
    byte_rate = SAMPLE_RATE * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = NUM_SAMPLES * (bits_per_sample // 8)

    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))  # file size - 8
        f.write(b"WAVE")
        # fmt chunk (IEEE float)
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))  # chunk size
        f.write(struct.pack("<H", 3))   # format: IEEE float
        f.write(struct.pack("<H", num_channels))
        f.write(struct.pack("<I", SAMPLE_RATE))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(struct.pack("<f", 1.0))          # Dirac impulse at sample 0
        f.write(b"\x00" * (data_size - 4))       # remaining samples = 0.0


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <output_dir>", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)

    for name in COEFF_NAMES:
        write_dirac_wav(out_dir / name)

    print(f"Generated {len(COEFF_NAMES)} Dirac coefficients "
          f"({NUM_SAMPLES} samples each) in {out_dir}")


if __name__ == "__main__":
    main()
