# T-072-06: PipeWire Filter-Chain Convolver NixOS Module — Research Notes

Status: Research complete, implementation pending (ALL STOP).

## Current State (as of commit 0340ef3)

### What exists in `nix/nixos/audio/pipewire.nix`

The module already handles most convolver deployment:

1. **Config deployment (line 20):** `configs/pipewire/30-filter-chain-convolver.conf`
   is copied into a `configPackages` derivation and merged into
   `/etc/pipewire/pipewire.conf.d/` by NixOS's PipeWire module.

2. **Coefficients directory (line 60):** `systemd.tmpfiles.rules` creates
   `/etc/pi4audio/coeffs/` with mode 0755, owned by root.

3. **Other PipeWire configs deployed in the same derivation:**
   - `10-audio-settings.conf` — clock rate 48kHz, quantum 256, max 1024
   - `20-usbstreamer.conf` — ADA8200 8ch capture adapter (USBStreamer)
   - `21-usbstreamer-playback.conf` — USBStreamer 8ch output adapter
   - `80-jack-no-autoconnect.conf` — suppresses JACK auto-connect (JACK conf.d)

4. **D-040 cleanup already done:** `25-loopback-8ch.conf` excluded with comment.

### Production convolver config (`30-filter-chain-convolver.conf`)

The config defines a `libpipewire-module-filter-chain` with:

- **4 convolver builtin nodes:** `conv_left_hp`, `conv_right_hp`, `conv_sub1_lp`,
  `conv_sub2_lp`. Each loads a WAV from `/etc/pi4audio/coeffs/`.
- **4 linear gain nodes:** `gain_left_hp`, `gain_right_hp`, `gain_sub1_lp`,
  `gain_sub2_lp`. Workaround for PW 1.4.9 ignoring `config.gain` (Finding 4,
  GM-12). Chained after each convolver.
- **Gain defaults:** Mains `Mult = 0.001` (-60 dB), subs `Mult = 0.000631`
  (-64 dB). Runtime-adjustable via `pw-cli`, session-only per C-009.
- **Node names:** Capture: `pi4audio-convolver` (Audio/Sink, 4ch AUX0-3).
  Playback: `pi4audio-convolver-out` (passive source, 4ch AUX0-3).
- **Channels 4-7** (engineer HP, singer IEM) bypass the filter-chain entirely.

### Coefficient WAV files referenced

| Path | Purpose |
|------|---------|
| `/etc/pi4audio/coeffs/combined_left_hp.wav` | Left main: highpass + room correction |
| `/etc/pi4audio/coeffs/combined_right_hp.wav` | Right main: highpass + room correction |
| `/etc/pi4audio/coeffs/combined_sub1_lp.wav` | Sub 1: lowpass + room correction |
| `/etc/pi4audio/coeffs/combined_sub2_lp.wav` | Sub 2: lowpass + room correction |

## The Mutable State Problem

The 4 WAV coefficient files must exist at boot for the convolver to load.
However:

- They are regenerated per venue by the room correction pipeline.
- NixOS's Nix store is read-only.
- `/etc/pi4audio/coeffs/` is writable (created by tmpfiles), but currently
  empty on a fresh deploy.
- If the WAVs are missing, PipeWire logs errors, the filter-chain node never
  appears, GM cannot create links, and the audio stack is non-functional.

## Three Strategies Evaluated

### Strategy A: Activation script

Generate dirac WAVs during `system.activationScripts`. Problem: runs on every
`nixos-rebuild switch`, overwriting venue-specific coefficients. Would need
conditional "only if missing" logic, duplicating what tmpfiles `C` does natively.

**Verdict: Rejected.**

### Strategy B: tmpfiles `C` directive (APPROVED)

Build dirac impulse WAVs as a Nix derivation at eval time. Deploy via
`systemd.tmpfiles.rules` using the `C` (copy) directive, which copies the
source file only if the target does not already exist.

- Dirac WAVs = unity passthrough (safe default, convolver loads and passes
  audio through unchanged).
- Venue-specific coefficients survive reboots and `nixos-rebuild switch`.
- Convolver always has valid coefficients at boot.

**Verdict: Approved by Architect.**

### Strategy C: Do nothing, document

Leave `/etc/pi4audio/coeffs/` empty until the room correction pipeline runs.
Problem: convolver fails to start on a fresh deploy, cascading into a
non-functional audio stack. Unacceptable for production auto-start.

**Verdict: Rejected.**

## Architect Decisions

1. **Strategy B approved.** Use tmpfiles `C` with a Nix derivation that runs
   `scripts/generate-dirac-coeffs.py` at build time.

2. **Keep changes in `pipewire.nix`.** The convolver is a PipeWire internal
   module (filter-chain), not a separate service. `pipewire.nix` already owns
   the config deployment and coeffs directory. No extraction to separate file.

3. **No NixOS options for gain values.** The `Mult` values (0.001 mains,
   0.000631 subs) stay hardcoded in `30-filter-chain-convolver.conf`. They are
   runtime-adjustable via `pw-cli` (session-only per C-009). Making them NixOS
   options would create the illusion of declarative management for what is
   actually a runtime concern.

## Implementation Plan

Add to `nix/nixos/audio/pipewire.nix` (estimated ~10 lines):

```nix
# In the let block, add:
diracCoeffs = pkgs.runCommand "pi4audio-dirac-coeffs" {
  nativeBuildInputs = [ pkgs.python3 ];
} ''
  mkdir -p $out
  python3 ${../../../scripts/generate-dirac-coeffs.py} $out
'';

# Extend the existing tmpfiles.rules:
systemd.tmpfiles.rules = [
  "d /etc/pi4audio/coeffs 0755 root root - -"
  "C /etc/pi4audio/coeffs/combined_left_hp.wav 0644 root root - ${diracCoeffs}/combined_left_hp.wav"
  "C /etc/pi4audio/coeffs/combined_right_hp.wav 0644 root root - ${diracCoeffs}/combined_right_hp.wav"
  "C /etc/pi4audio/coeffs/combined_sub1_lp.wav 0644 root root - ${diracCoeffs}/combined_sub1_lp.wav"
  "C /etc/pi4audio/coeffs/combined_sub2_lp.wav 0644 root root - ${diracCoeffs}/combined_sub2_lp.wav"
];
```

No other files need changing. No security consultation needed (no new ports).

## Gotchas and Risks

1. **tmpfiles `C` semantics:** The `C` directive copies only if the target file
   does not exist. It does NOT check content or timestamps. If a venue
   coefficient file gets corrupted (zero-length, wrong format), tmpfiles will
   NOT replace it because the file exists. The room correction pipeline must
   handle this case by overwriting explicitly.

2. **`generate-dirac-coeffs.py` dependency:** The script uses only `struct`
   and `pathlib` (stdlib). No external Python packages needed. The
   `nativeBuildInputs = [ pkgs.python3 ]` is sufficient.

3. **File permissions:** The `C` directive creates files as root:root 0644.
   PipeWire runs as user `ela` and needs read access. 0644 provides this.

4. **Stale config files on disk (from D-040 audit):**
   - `configs/pipewire/25-loopback-8ch.conf` still exists but is not deployed.
   - `configs/wireplumber/51-loopback-disable-acp.conf` still exists but is not
     deployed.
   These do not affect the convolver module but could cause confusion.

## References

- `nix/nixos/audio/pipewire.nix` — target file for implementation
- `configs/pipewire/30-filter-chain-convolver.conf` — production convolver config
- `configs/local-demo/convolver.conf` — local-demo variant (unity gain, COEFFS_DIR placeholder)
- `scripts/generate-dirac-coeffs.py` — dirac impulse WAV generator (80 lines)
- CLAUDE.md "Critical Design Decisions" section 1 — combined minimum-phase FIR rationale
- C-009 — pw-cli changes are session-only, revert on PW restart
