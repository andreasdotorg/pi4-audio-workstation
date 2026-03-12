#!/home/ela/audio-workstation-venv/bin/python3
"""JACK callback-based tone/noise generator for audio path and room correction testing.

Generates test signals through PipeWire's JACK bridge, testing the same code path
as Reaper: JACK process callbacks -> loopback-8ch-sink -> CamillaDSP -> USBStreamer.

Registers 8 output ports matching the loopback-8ch-sink channel layout.
By default outputs tone on ports 1+2 (L/R mains), silence on remaining ports.

Supported waveforms:
  sine  — pure sine tone (default)
  white — white noise (uniform random, broadband)
  pink  — pink noise (1/f spectrum, perceptually flat)
  sweep — logarithmic frequency sweep for impulse response measurement

Usage:
    python3 jack-tone-generator.py --duration 30 --frequency 1000
    python3 jack-tone-generator.py --continuous --waveform pink
    python3 jack-tone-generator.py --waveform sweep --duration 10 --sweep-start 20 --sweep-end 20000
    python3 jack-tone-generator.py --waveform sine --channels 3,4 --frequency 80
"""

import argparse
import sys
import threading
import time
import numpy as np

import jack


def make_pink_noise_generator():
    """Create a pink noise generator using the Voss-McCartney algorithm.

    Sums random number generators updating at octave-spaced intervals to
    approximate a 1/f power spectrum. Efficient and gives good results
    for audio testing.
    """
    # 16 octave rows covers well beyond the audible range at 48kHz
    num_rows = 16
    # Running total and per-row values
    running_sum = np.float64(0.0)
    rows = np.zeros(num_rows, dtype=np.float64)
    # Initialize rows
    for i in range(num_rows):
        val = np.random.uniform(-1.0, 1.0)
        rows[i] = val
        running_sum += val
    # Counter for determining which row to update
    counter = 0
    # Normalization factor to keep output roughly in [-1, 1]
    norm = 1.0 / num_rows

    def generate(frames):
        nonlocal running_sum, counter
        out = np.empty(frames, dtype=np.float64)
        for i in range(frames):
            # Determine which row to update: index of lowest set bit of counter
            # This gives octave-spaced update rates
            counter += 1
            # Find lowest set bit position
            row_idx = 0
            n = counter
            if n > 0:
                row_idx = int(np.log2(n & -n)) % num_rows
            # Update that row
            running_sum -= rows[row_idx]
            new_val = np.random.uniform(-1.0, 1.0)
            rows[row_idx] = new_val
            running_sum += new_val
            out[i] = running_sum * norm
        return out

    return generate


def main():
    parser = argparse.ArgumentParser(description="JACK tone/noise generator")
    parser.add_argument("--duration", type=float, default=30,
                        help="Duration in seconds (default: 30)")
    parser.add_argument("--frequency", type=float, default=1000,
                        help="Tone frequency in Hz (default: 1000)")
    parser.add_argument("--amplitude", type=float, default=0.063,
                        help="Amplitude, 0.063 = -24dBFS (default: 0.063)")
    parser.add_argument("--connect-to", type=str, default="CamillaDSP 8ch Input",
                        help="JACK sink to auto-connect to (default: CamillaDSP 8ch Input)")
    parser.add_argument("--continuous", action="store_true",
                        help="Run indefinitely until Ctrl+C (ignores --duration)")
    parser.add_argument("--waveform", type=str, default="sine",
                        choices=["sine", "white", "pink", "sweep"],
                        help="Waveform type (default: sine)")
    parser.add_argument("--channels", type=str, default="1,2",
                        help="Comma-separated output channels (default: 1,2)")
    parser.add_argument("--sweep-start", type=float, default=20,
                        help="Sweep start frequency in Hz (default: 20)")
    parser.add_argument("--sweep-end", type=float, default=20000,
                        help="Sweep end frequency in Hz (default: 20000)")
    args = parser.parse_args()

    # Amplitude validation
    if args.amplitude > 1.0:
        print(f"ERROR: --amplitude {args.amplitude} exceeds 1.0 (full scale). "
              f"Values above 1.0 will produce clipped/distorted output.", file=sys.stderr)
        sys.exit(1)
    if args.amplitude > 0.5:
        print(f"WARNING: amplitude > 0.5 may cause clipping with multiple channels",
              file=sys.stderr)

    # Parse channel list
    try:
        active_channels = [int(ch.strip()) for ch in args.channels.split(",")]
        for ch in active_channels:
            if ch < 1 or ch > 8:
                print(f"ERROR: Channel {ch} out of range (1-8)", file=sys.stderr)
                sys.exit(1)
    except ValueError:
        print(f"ERROR: Invalid --channels format: '{args.channels}'. "
              f"Use comma-separated integers, e.g. '1,2' or '3,4'", file=sys.stderr)
        sys.exit(1)

    # Convert to 0-indexed set for fast lookup in the RT callback
    active_channel_set = set(ch - 1 for ch in active_channels)

    if args.waveform == "sweep" and args.continuous:
        print("ERROR: --waveform sweep requires a finite --duration "
              "(cannot be used with --continuous)", file=sys.stderr)
        sys.exit(1)

    # Shared state — phase is only accessed from the RT callback (single-threaded)
    phase = [np.float64(0.0)]
    xruns = []
    callback_gaps = []
    last_callback_time = [0.0]
    shutdown_reason = [None]
    finished = threading.Event()

    # Sweep state (set after client activation when we know samplerate)
    sweep_total_samples = [0]
    sweep_samples_elapsed = [0]

    # Pink noise generator (created once, maintains internal state)
    pink_gen = make_pink_noise_generator() if args.waveform == "pink" else None

    client = jack.Client("tone-generator")

    # Register 8 output ports
    outports = []
    for i in range(8):
        outports.append(client.outports.register(f"out_{i+1}"))

    @client.set_process_callback
    def process(frames):
        now = time.monotonic()
        sr = client.samplerate

        # Detect graph suspension gaps (callback interval > 2x expected)
        if last_callback_time[0] > 0:
            expected_interval = frames / sr
            actual_interval = now - last_callback_time[0]
            if actual_interval > 2.0 * expected_interval:
                ts = time.strftime("%H:%M:%S")
                callback_gaps.append((ts, actual_interval))
                print(f"[{ts}] CALLBACK GAP: {actual_interval*1000:.1f}ms "
                      f"(expected {expected_interval*1000:.1f}ms)", file=sys.stderr)
        last_callback_time[0] = now

        # Generate waveform
        if args.waveform == "sine":
            phase_inc = 2.0 * np.pi * args.frequency / sr
            t = np.arange(frames, dtype=np.float64) * phase_inc + phase[0]
            phase[0] = (phase[0] + frames * phase_inc) % (2.0 * np.pi)
            signal = args.amplitude * np.sin(t)

        elif args.waveform == "white":
            signal = args.amplitude * np.random.uniform(-1.0, 1.0, frames)

        elif args.waveform == "pink":
            raw = pink_gen(frames)
            signal = args.amplitude * raw

        elif args.waveform == "sweep":
            # Log sweep: phase = 2*pi * f1 * T / ln(f2/f1) * (exp(t/T * ln(f2/f1)) - 1)
            f1 = args.sweep_start
            f2 = args.sweep_end
            T = args.duration
            ln_ratio = np.log(f2 / f1)
            total_samples = sweep_total_samples[0]
            n0 = sweep_samples_elapsed[0]
            n = np.arange(frames, dtype=np.float64) + n0
            t_sec = n / sr
            # Instantaneous phase
            inst_phase = 2.0 * np.pi * f1 * T / ln_ratio * (
                np.exp(t_sec / T * ln_ratio) - 1.0)
            signal = args.amplitude * np.sin(inst_phase)
            sweep_samples_elapsed[0] = n0 + frames

        signal_f32 = signal.astype(np.float32)
        silence = np.zeros(frames, dtype=np.float32)

        # Output to active channels, silence on the rest
        for i, port in enumerate(outports):
            if i in active_channel_set:
                port.get_array()[:] = signal_f32
            else:
                port.get_array()[:] = silence

    @client.set_xrun_callback
    def xrun(delay):
        ts = time.strftime("%H:%M:%S")
        xruns.append(ts)
        print(f"[{ts}] XRUN (delay: {delay:.1f}us)", file=sys.stderr)

    @client.set_shutdown_callback
    def shutdown(status, reason):
        shutdown_reason[0] = reason
        print(f"JACK shutdown: {reason}", file=sys.stderr)
        finished.set()

    # Activate and connect
    client.activate()

    # Set sweep total samples now that we know the samplerate
    sweep_total_samples[0] = int(args.duration * client.samplerate)

    # Build description string
    if args.waveform == "sine":
        desc = f"sine {args.frequency}Hz"
    elif args.waveform == "white":
        desc = "white noise"
    elif args.waveform == "pink":
        desc = "pink noise"
    elif args.waveform == "sweep":
        desc = f"log sweep {args.sweep_start}Hz-{args.sweep_end}Hz over {args.duration}s"

    ch_str = ",".join(str(ch) for ch in sorted(active_channels))
    print(f"JACK tone generator active: {desc} @ {args.amplitude} "
          f"({20*np.log10(args.amplitude):.1f}dBFS)")
    print(f"Sample rate: {client.samplerate}, Buffer size: {client.blocksize}")
    print(f"Channels: {ch_str}")
    if args.continuous:
        print(f"Duration: continuous (Ctrl+C to stop)")
    else:
        print(f"Duration: {args.duration}s")

    # Discover and connect to sink ports
    target_ports = client.get_ports(args.connect_to, is_input=True)
    if not target_ports:
        print(f"WARNING: No ports matching '{args.connect_to}' found. "
              f"Running unconnected.", file=sys.stderr)
    else:
        for i, outport in enumerate(outports):
            if i < len(target_ports):
                client.connect(outport, target_ports[i])
                print(f"  {outport.name} -> {target_ports[i].name}")
            else:
                print(f"  {outport.name} -> (no target port)")

    start = time.monotonic()

    try:
        if args.continuous:
            # Run until Ctrl+C or JACK shutdown
            while not finished.is_set():
                finished.wait(timeout=1.0)
        else:
            while not finished.is_set():
                elapsed = time.monotonic() - start
                if elapsed >= args.duration:
                    break
                remaining = args.duration - elapsed
                finished.wait(timeout=min(1.0, remaining))
    except KeyboardInterrupt:
        pass

    elapsed = time.monotonic() - start
    client.deactivate()
    client.close()

    # Summary
    print()
    print("=== Tone Generator Summary ===")
    print(f"Waveform: {desc}")
    print(f"Channels: {ch_str}")
    print(f"Duration: {elapsed:.1f}s")
    print(f"Xruns: {len(xruns)}")
    if xruns:
        print(f"Xrun timestamps: {', '.join(xruns)}")
    print(f"Callback gaps: {len(callback_gaps)}")
    if callback_gaps:
        for ts, dur in callback_gaps:
            print(f"  [{ts}] {dur*1000:.1f}ms")
    if shutdown_reason[0]:
        print(f"Shutdown reason: {shutdown_reason[0]}")
    print(f"Result: {'PASS' if len(xruns) == 0 and len(callback_gaps) == 0 else 'FAIL'}")


if __name__ == "__main__":
    main()
