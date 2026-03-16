#!/usr/bin/env python3
"""Generate Dirac impulse WAV files for BM-2 benchmark (US-058).

Creates a single-sample unit impulse (Dirac delta) as a 32-bit float WAV
at 48 kHz.  The resulting file is a transparent convolution filter -- output
equals input, isolating the convolver's CPU overhead from any spectral
processing.

Usage:
    python3 gen_dirac_bm2.py [output_dir] [taps]

Defaults:
    output_dir: /tmp/bm2-coeffs
    taps: 16384
"""

import os
import sys

import numpy as np
import soundfile as sf


def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bm2-coeffs"
    taps = int(sys.argv[2]) if len(sys.argv) > 2 else 16384
    sample_rate = 48000

    os.makedirs(output_dir, exist_ok=True)

    ir = np.zeros(taps, dtype=np.float32)
    ir[0] = 1.0

    filename = os.path.join(output_dir, f"dirac_{taps}.wav")
    sf.write(filename, ir, sample_rate, subtype="FLOAT")
    print(f"Generated {filename} ({taps} taps, {sample_rate} Hz, float32)")


if __name__ == "__main__":
    main()
