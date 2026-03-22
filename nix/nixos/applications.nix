# applications.nix — Audio applications for the Pi 4 Audio Workstation
#
# Mixxx (DJ software) and Reaper (DAW) for the two operational modes.
# Both run under PipeWire's JACK bridge via pw-jack.
{ config, lib, pkgs, ... }:

{
  environment.systemPackages = with pkgs; [
    # ── Mixxx — DJ/PA mode ─────────────────────────────────────
    # Runs via: pw-jack mixxx
    # Hardware V3D GL (D-022) — no LIBGL_ALWAYS_SOFTWARE needed.
    # CPU ~85% with hardware GL (vs 142-166% with llvmpipe).
    mixxx

    # ── Reaper — Live vocal performance mode ───────────────────
    # Runs via: pw-jack reaper
    # nixpkgs packages Reaper for aarch64-linux.
    reaper

    # ── pw-jack wrapper ────────────────────────────────────────
    # Provided by the PipeWire JACK bridge (services.pipewire.jack.enable
    # in audio/pipewire.nix). Listed here as documentation — the binary
    # comes from the pipewire package, which is already in the system path
    # when services.pipewire.jack.enable = true.
  ];
}
