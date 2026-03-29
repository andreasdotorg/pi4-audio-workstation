# sd-image.nix — SD card image builder for the Raspberry Pi 4 Audio Workstation
#
# Produces a compressed, flashable .img.zst via:
#   nix build .#images.sd-card
#
# The image uses U-Boot as the second-stage bootloader so that
# NixOS's extlinux-based generation switching works out of the box.
#
# Firmware files come from firmware.nix (single source of truth).
{ config, pkgs, lib, modulesPath, ... }:

{
  imports = [
    "${modulesPath}/installer/sd-card/sd-image-aarch64.nix"
  ];

  # ── Image knobs ────────────────────────────────────────────────
  sdImage.compressImage = true;
  sdImage.firmwareSize = 256; # MiB — generous for firmware + kernels

  # ── Firmware partition population ──────────────────────────────
  # Uses the pre-built firmware directory from firmware.nix.
  sdImage.populateFirmwareCommands = lib.mkForce ''
    cp ${config.pi4audio.firmwareFiles}/* $NIX_BUILD_TOP/firmware/
  '';
}
