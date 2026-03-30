#!/usr/bin/env python3
"""Generate room simulator impulse response WAVs for local-demo.

Creates mono float32 WAVs at 48 kHz containing synthetic room IRs using
the image source method. The IR models a small venue (8x6x3m) with moderate
absorption, matching the room_config.yml used by US-067 room simulation tests.

Two modes:

1. Single IR (default): One mono WAV for the room-sim convolver node.
   Signal flow:
       convolver-out:output_AUX0 -> room-sim-convolver -> umik1-loopback-sink

2. Per-channel IRs (--per-channel): Four mono WAVs with per-speaker position
   differences — different propagation delays, early reflection patterns, and
   LF room gain on sub channels. Used by the 4-channel room-sim filter-chain
   (T-111-03) for realistic per-channel measurement simulation.

Usage:
    python scripts/generate-room-sim-ir.py <output_dir>
    python scripts/generate-room-sim-ir.py --per-channel <output_dir>

Creates (default):
    <output_dir>/room_sim_ir.wav

Creates (--per-channel):
    <output_dir>/room_ir_left.wav
    <output_dir>/room_ir_right.wav
    <output_dir>/room_ir_sub1.wav
    <output_dir>/room_ir_sub2.wav
"""

import math
import struct
import sys
from pathlib import Path

SAMPLE_RATE = 48000
SPEED_OF_SOUND = 343.0  # m/s at ~20C
IR_DURATION_S = 0.3     # 300ms — enough for room decay (single-IR mode)
WALL_ABSORPTION = 0.3

# Room dimensions matching configs/local-demo/room_config.yml
ROOM_DIMS = (8.0, 6.0, 3.0)  # L x W x H meters

# Speaker and mic positions (from room_config.yml: main_left speaker)
SPEAKER_POS = (1.0, 5.0, 1.5)
MIC_POS = (4.0, 3.0, 1.2)

# Per-channel speaker positions.
# Mains at 1.5m height, symmetric about x=4.0 center.
# Subs at 0.3m (floor), slightly forward (y=5.5, near front wall at y=6.0).
CHANNEL_SPEAKERS = {
    "left":  (1.0, 5.0, 1.5),   # left main — same as existing single-IR
    "right": (7.0, 5.0, 1.5),   # right main — symmetric about x=4.0
    "sub1":  (2.0, 5.5, 0.3),   # sub 1 — floor, left-of-center, near front wall
    "sub2":  (6.0, 5.5, 0.3),   # sub 2 — floor, right-of-center, near front wall
}

# Room modes: axial resonances of the 8x6x3m room.
# (frequency_hz, Q, base_amplitude)
ROOM_MODES = [
    (28.7, 8.0, 0.15),   # deep bass mode
    (42.5, 8.0, 0.20),   # strong axial mode
    (57.2, 5.0, 0.10),   # tangential mode
]

# LF room gain multipliers for sub channels (frequency-dependent).
# Subs couple more strongly to room modes due to floor boundary gain,
# front wall proximity, and omnidirectional radiation at LF.
# Multipliers per mode: [28.7 Hz, 42.5 Hz, 57.2 Hz]
SUB_MODE_BOOST = [2.5, 2.0, 1.5]

# Per-channel IR length: 1024 taps (~21ms at 48 kHz).
# Captures direct sound + first/second order reflections.
PER_CHANNEL_IR_TAPS = 1024


def distance(p1, p2):
    """Euclidean distance between two 3D points."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))


def reflect(pos, axis, side, dims):
    """Reflect a point across a wall."""
    pos = list(pos)
    if side == 0:
        pos[axis] = -pos[axis]
    else:
        pos[axis] = 2 * dims[axis] - pos[axis]
    return tuple(pos)


def generate_room_ir_for_speaker(speaker_pos, ir_len, mode_boosts=None):
    """Generate a synthetic room IR for a given speaker position.

    Args:
        speaker_pos: (x, y, z) speaker position in meters.
        ir_len: Number of samples in the IR.
        mode_boosts: Optional list of per-mode amplitude multipliers.
            If None, uses 1.0 for all modes (no boost).

    Returns a list of float samples (normalized, peak ~0.2).
    """
    ir = [0.0] * ir_len

    # Direct path
    d = distance(speaker_pos, MIC_POS)
    delay = int(d / SPEED_OF_SOUND * SAMPLE_RATE)
    if delay < ir_len:
        ir[delay] = 1.0 / max(d, 0.01)

    # First-order reflections (6 walls)
    walls = [
        (0, 0), (0, 1),  # x=0, x=Lx
        (1, 0), (1, 1),  # y=0, y=Ly
        (2, 0), (2, 1),  # z=0 (floor), z=Lz (ceiling)
    ]
    refl_coeff = 1.0 - WALL_ABSORPTION

    for axis, side in walls:
        img = reflect(speaker_pos, axis, side, ROOM_DIMS)
        d = distance(img, MIC_POS)
        delay = int(d / SPEED_OF_SOUND * SAMPLE_RATE)
        if 0 <= delay < ir_len:
            ir[delay] += refl_coeff / max(d, 0.01)

    # Second-order reflections
    for ax1, s1 in walls:
        img1 = reflect(speaker_pos, ax1, s1, ROOM_DIMS)
        for ax2, s2 in walls:
            if (ax2, s2) == (ax1, s1):
                continue
            img2 = reflect(img1, ax2, s2, ROOM_DIMS)
            d = distance(img2, MIC_POS)
            delay = int(d / SPEED_OF_SOUND * SAMPLE_RATE)
            if 0 <= delay < ir_len:
                ir[delay] += (refl_coeff ** 2) / max(d, 0.01)

    # Room modes: decaying sinusoids at axial mode frequencies.
    for idx, (freq, q, amp) in enumerate(ROOM_MODES):
        boost = 1.0
        if mode_boosts is not None and idx < len(mode_boosts):
            boost = mode_boosts[idx]
        decay_rate = math.pi * freq / q
        for i in range(ir_len):
            t = i / SAMPLE_RATE
            if t < 0.01:  # skip direct sound region
                continue
            mode_val = amp * boost * math.sin(2.0 * math.pi * freq * t) * math.exp(-decay_rate * t)
            ir[i] += mode_val

    # Normalize peak to 0.2 (~-14 dBFS).
    peak = max(abs(s) for s in ir)
    if peak > 0:
        scale = 0.2 / peak
        ir = [s * scale for s in ir]

    # DC-blocking highpass at 20 Hz (matches physical UMIK-1 behavior).
    fc = 20.0
    alpha = 1.0 / (1.0 + 2.0 * math.pi * fc / SAMPLE_RATE)
    filtered = [0.0] * len(ir)
    filtered[0] = ir[0]
    for i in range(1, len(ir)):
        filtered[i] = alpha * (filtered[i - 1] + ir[i] - ir[i - 1])
    ir = filtered

    return ir


def generate_room_ir():
    """Generate the single-channel room IR (backward-compatible).

    Returns a list of float samples using the original speaker position
    and full 300ms duration.
    """
    ir_len = int(IR_DURATION_S * SAMPLE_RATE)
    return generate_room_ir_for_speaker(SPEAKER_POS, ir_len)


def generate_per_channel_irs():
    """Generate 4 per-channel room IRs with physically distinct characteristics.

    Returns a dict of {filename: samples} for left, right, sub1, sub2.
    Each IR has:
    - Different propagation delay (from speaker position geometry)
    - Different early reflection pattern (from image source positions)
    - LF room gain on sub channels (frequency-dependent mode boost)
    """
    results = {}
    for name, speaker_pos in CHANNEL_SPEAKERS.items():
        is_sub = name.startswith("sub")
        mode_boosts = SUB_MODE_BOOST if is_sub else None
        ir = generate_room_ir_for_speaker(
            speaker_pos, PER_CHANNEL_IR_TAPS, mode_boosts
        )
        d = distance(speaker_pos, MIC_POS)
        delay_ms = d / SPEED_OF_SOUND * 1000
        print(f"  {name}: {len(ir)} taps, distance={d:.2f}m, delay={delay_ms:.1f}ms"
              f"{', LF boost' if is_sub else ''}")
        results[f"room_ir_{name}.wav"] = ir
    return results


def write_float32_wav(path, samples, sample_rate=SAMPLE_RATE):
    """Write a mono float32 WAV file without numpy/soundfile dependency."""
    num_channels = 1
    bits_per_sample = 32
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = len(samples) * (bits_per_sample // 8)

    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        # fmt chunk (IEEE float)
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 3))  # format: IEEE float
        f.write(struct.pack("<H", num_channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        for s in samples:
            f.write(struct.pack("<f", s))


def main():
    per_channel = "--per-channel" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--per-channel"]

    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} [--per-channel] <output_dir>", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args[0])
    out_dir.mkdir(parents=True, exist_ok=True)

    if per_channel:
        print("Generating per-channel room IRs...")
        irs = generate_per_channel_irs()
        for filename, samples in irs.items():
            path = out_dir / filename
            write_float32_wav(path, samples)
            print(f"  -> {path}")
        print(f"Generated {len(irs)} per-channel room IRs at {out_dir}")
    else:
        ir = generate_room_ir()
        path = out_dir / "room_sim_ir.wav"
        write_float32_wav(path, ir)
        print(f"Generated room sim IR ({len(ir)} samples, {len(ir)/SAMPLE_RATE:.1f}s) at {path}")


if __name__ == "__main__":
    main()
