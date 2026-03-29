# firmware.nix — Raspberry Pi 4 firmware partition management
#
# Single source of truth for the Pi 4B boot firmware files:
#   - VideoCore firmware blobs (bootcode.bin, fixup*.dat, start*.elf)
#   - U-Boot binary (u-boot-rpi4.bin)
#   - GICv2 stub (armstub8-gic.bin)
#   - Device-tree blob (bcm2711-rpi-4-b.dtb)
#   - config.txt (KMS, UART, GPU memory, arm_boost)
#
# Shared by:
#   - sd-image.nix: uses firmwareFiles derivation for image build
#   - disko.nix: activation script populates /boot/firmware on first boot
#   - nixos-rebuild: activation script updates firmware on upgrades
#
# Boot sequence: VideoCore reads bootcode.bin from FAT partition ->
# loads start4.elf -> reads config.txt -> loads U-Boot -> U-Boot reads
# extlinux.conf -> Linux boots. The RT kernel is selected by extlinux
# (controlled by boot.kernelPackages), NOT by config.txt kernel= line.
{ config, lib, pkgs, ... }:

let
  # config.txt — written to the Nix store as a file, then copied
  # into the firmware derivation. No heredoc whitespace issues.
  configTxtFile = pkgs.writeText "pi4audio-config.txt" ''
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
  '';

  # Pre-built firmware directory in the Nix store.
  # Contains all files needed on the FAT firmware partition.
  firmwareFiles = pkgs.runCommand "pi4audio-firmware" { } ''
    mkdir -p $out

    # VideoCore firmware blobs
    cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bootcode.bin $out/
    for f in ${pkgs.raspberrypifw}/share/raspberrypi/boot/fixup*.dat; do
      cp "$f" $out/
    done
    for f in ${pkgs.raspberrypifw}/share/raspberrypi/boot/start*.elf; do
      cp "$f" $out/
    done

    # U-Boot binary (64-bit)
    cp ${pkgs.ubootRaspberryPi4_64bit}/u-boot.bin $out/u-boot-rpi4.bin

    # GICv2 stub required for U-Boot on Pi 4
    cp ${pkgs.raspberrypi-armstubs}/armstub8-gic.bin $out/

    # Device-tree blob for the Pi 4 Model B
    cp ${pkgs.raspberrypifw}/share/raspberrypi/boot/bcm2711-rpi-4-b.dtb $out/

    # config.txt
    cp ${configTxtFile} $out/config.txt
  '';
in
{
  # Export firmwareFiles so sd-image.nix can reference it.
  options.pi4audio.firmwareFiles = lib.mkOption {
    type = lib.types.package;
    default = firmwareFiles;
    readOnly = true;
    description = "Pre-built Pi 4 firmware directory for the boot partition.";
  };

  config = {
    # Activation script: populate /boot/firmware/ with firmware files.
    # Runs on every nixos-rebuild switch / nixos-anywhere install.
    # Copies fresh firmware files each time to keep them in sync with
    # the NixOS generation (firmware packages may update across rebuilds).
    system.activationScripts.pi4audio-firmware = lib.stringAfter [ "specialfs" ] ''
      FWDIR="/boot/firmware"
      if [ -d "$FWDIR" ]; then
        echo "Updating Pi 4 firmware in $FWDIR..."
        cp ${firmwareFiles}/bootcode.bin "$FWDIR/"
        cp ${firmwareFiles}/fixup*.dat "$FWDIR/"
        cp ${firmwareFiles}/start*.elf "$FWDIR/"
        cp ${firmwareFiles}/u-boot-rpi4.bin "$FWDIR/"
        cp ${firmwareFiles}/armstub8-gic.bin "$FWDIR/"
        cp ${firmwareFiles}/bcm2711-rpi-4-b.dtb "$FWDIR/"
        cp ${firmwareFiles}/config.txt "$FWDIR/"
        echo "Pi 4 firmware updated."
      fi
    '';
  };
}
