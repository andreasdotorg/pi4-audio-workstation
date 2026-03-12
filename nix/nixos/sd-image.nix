# sd-image.nix — SD card image builder for the Raspberry Pi 4 Audio Workstation
#
# Produces a compressed, flashable .img.zst via:
#   nix build .#images.sd-card   (or however flake.nix exposes it)
#
# The image uses U-Boot as the second-stage bootloader so that
# NixOS's extlinux-based generation switching works out of the box.
{ config, pkgs, lib, ... }:

{
  imports = [
    "${toString pkgs.path}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
  ];

  # ── Image knobs ────────────────────────────────────────────────
  sdImage.compressImage = true;
  sdImage.firmwareSize = 256; # MiB — generous for firmware + kernels

  # ── Firmware partition population ──────────────────────────────
  # We override the default commands so we can write a custom config.txt
  # with full-KMS, UART, and 64-bit settings.
  sdImage.populateFirmwareCommands = lib.mkForce ''
    # Copy VideoCore firmware blobs
    (cd ${pkgs.raspberrypifw}/share/raspberrypi/boot && \
      cp bootcode.bin fixup*.dat start*.elf $NIX_BUILD_TOP/firmware/)

    # U-Boot binary (64-bit)
    cp ${pkgs.ubootRaspberryPi4_64bit}/u-boot.bin firmware/u-boot-rpi4.bin

    # GICv2 stub required for U-Boot on Pi 4
    cp ${pkgs.raspberrypi-armstubs}/armstub8-gic.bin firmware/armstub8-gic.bin

    # Device-tree blob for the Pi 4 Model B
    cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-4-b.dtb firmware/

    # ── config.txt ───────────────────────────────────────────────
    cat > firmware/config.txt << 'CONFIGTXT'
[pi4]
kernel=u-boot-rpi4.bin
enable_gic=1
armstub=armstub8-gic.bin
arm_64bit=1
disable_overscan=1
arm_boost=1
enable_uart=1
avoid_warnings=1

# Full KMS (not fkms) — required for modern DRM/V3D
dtoverlay=vc4-kms-v3d
gpu_mem=256

[all]
arm_64bit=1
enable_uart=1
CONFIGTXT
  '';
}
