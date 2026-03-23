#!/usr/bin/env python3
"""Generate dirac impulse WAV files for the local demo convolver.

Each file is a 1024-sample mono float32 WAV at 48 kHz: sample[0] = 1.0,
rest zeros. Convolving with a dirac impulse is a no-op — the signal
passes through unchanged. This gives us a real PipeWire convolver with
the same node/port topology as production, but without needing actual
FIR correction coefficients.

Usage:
    python scripts/generate-dirac-coeffs.py <output_dir>

Creates:
    <output_dir>/combined_left_hp.wav
    <output_dir>/combined_right_hp.wav
    <output_dir>/combined_sub1_lp.wav
    <output_dir>/combined_sub2_lp.wav
"""

import struct
import sys
from pathlib import Path

NUM_SAMPLES = 1024


def write_dirac_wav(path: Path, sample_rate: int = 48000) -> None:
    """Write a 1024-sample float32 WAV (dirac impulse: [1.0, 0, 0, ...])."""
    num_channels = 1
    bits_per_sample = 32
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
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
        f.write(struct.pack("<H", 3))  # format: IEEE float
        f.write(struct.pack("<H", num_channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(struct.pack("<f", 1.0))  # dirac impulse at sample 0
        f.write(b"\x00" * (data_size - 4))  # remaining samples = 0.0


COEFF_NAMES = [
    "combined_left_hp.wav",
    "combined_right_hp.wav",
    "combined_sub1_lp.wav",
    "combined_sub2_lp.wav",
]


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <output_dir>", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)

    for name in COEFF_NAMES:
        path = out_dir / name
        write_dirac_wav(path)

    print(f"Generated {len(COEFF_NAMES)} dirac coefficients ({NUM_SAMPLES} samples each) in {out_dir}")


if __name__ == "__main__":
    main()
