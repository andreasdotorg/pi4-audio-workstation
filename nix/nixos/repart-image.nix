# repart-image.nix — GPT SD card image builder for the Raspberry Pi 4 Audio Workstation
#
# Produces a compressed, flashable .raw.zst via:
#   nix build .#images.sd-card
#
# Uses systemd-repart to build a GPT image with:
#   Partition 1: 256 MiB FAT32 — VideoCore firmware, U-Boot, config.txt, DTBs
#   Partition 2: rest of disk ext4 — NixOS root filesystem
#
# F-273: Replaces sd-image.nix (MBR) so that both image builds and
# nixos-anywhere (disko.nix) produce identical GPT partition layouts with
# the same filesystem labels: FIRMWARE (vfat) and NIXOS_SD (ext4).
#
# The image uses U-Boot as the second-stage bootloader so that NixOS's
# extlinux-based generation switching works out of the box.
#
# Firmware files come from firmware.nix (single source of truth).
{ config, lib, pkgs, modulesPath, ... }:

let
  # Build extlinux boot directory from the system toplevel.
  # This creates /boot/extlinux/extlinux.conf pointing to kernel, initrd, DTBs.
  extlinuxDir = pkgs.runCommand "pi4audio-extlinux" { } ''
    mkdir -p $out/boot
    ${config.boot.loader.generic-extlinux-compatible.populateCmd} \
      -c ${config.system.build.toplevel} -d $out/boot
  '';

  # Nix path registration for the initial store DB load on first boot.
  closureInfo = pkgs.closureInfo {
    rootPaths = [ config.system.build.toplevel ];
  };
in
{
  imports = [
    "${modulesPath}/image/repart.nix"
  ];

  image.repart = {
    name = "pi4audio";
    compression.enable = true;
    sectorSize = 512;

    # Filesystem labels: -n FIRMWARE for vfat, -L NIXOS_SD for ext4.
    # These are global per filesystem type — safe because we have exactly
    # one vfat and one ext4 partition.
    #
    # -O ^orphan_file: U-Boot 2025.10 ext4 driver doesn't support the
    # orphan_file INCOMPAT feature (0x20000), enabled by default in
    # e2fsprogs >= 1.47.3. Without this flag, U-Boot can't read the root
    # partition to find extlinux.conf. Safe to disable — falls back to
    # linked-list orphan tracking with negligible performance difference.
    mkfsOptions = {
      vfat = [ "-n" "FIRMWARE" ];
      ext4 = [ "-L" "NIXOS_SD" "-O" "^orphan_file" ];
    };

    partitions = {
      # Firmware partition: VideoCore blobs, U-Boot, config.txt, DTBs.
      # Populated at image build time from firmware.nix's firmwareFiles.
      "10-firmware" = {
        contents =
          let
            fw = config.pi4audio.firmwareFiles;
          in
          {
            "/bootcode.bin".source = "${fw}/bootcode.bin";
            "/config.txt".source = "${fw}/config.txt";
            "/u-boot-rpi4.bin".source = "${fw}/u-boot-rpi4.bin";
            "/armstub8-gic.bin".source = "${fw}/armstub8-gic.bin";
            "/bcm2711-rpi-4-b.dtb".source = "${fw}/bcm2711-rpi-4-b.dtb";
            # fixup*.dat and start*.elf are multiple files — enumerate them.
            "/fixup.dat".source = "${fw}/fixup.dat";
            "/fixup4.dat".source = "${fw}/fixup4.dat";
            "/fixup4cd.dat".source = "${fw}/fixup4cd.dat";
            "/fixup4db.dat".source = "${fw}/fixup4db.dat";
            "/fixup4x.dat".source = "${fw}/fixup4x.dat";
            "/fixup_cd.dat".source = "${fw}/fixup_cd.dat";
            "/fixup_db.dat".source = "${fw}/fixup_db.dat";
            "/fixup_x.dat".source = "${fw}/fixup_x.dat";
            "/start.elf".source = "${fw}/start.elf";
            "/start4.elf".source = "${fw}/start4.elf";
            "/start4cd.elf".source = "${fw}/start4cd.elf";
            "/start4db.elf".source = "${fw}/start4db.elf";
            "/start4x.elf".source = "${fw}/start4x.elf";
            "/start_cd.elf".source = "${fw}/start_cd.elf";
            "/start_db.elf".source = "${fw}/start_db.elf";
            "/start_x.elf".source = "${fw}/start_x.elf";
          };
        repartConfig = {
          # ESP (EFI System Partition) — required for Pi 4 boot.
          # VideoCore EEPROM on GPT only recognizes ESP (C12A7328) and
          # Microsoft Basic Data (EBD0A0A2) type partitions.
          #
          # U-Boot's efi_mgr bootmeth runs first and logs EFI errors
          # (e.g. "cannot persist efi variables") — these are harmless.
          # The efi_mgr fails to find bootable EFI entries, then the
          # bootflow scan falls through to extlinux on the root partition.
          Type = "esp";
          Format = "vfat";
          Label = "firmware";   # GPT partition label
          SizeMinBytes = "256M";
          SizeMaxBytes = "256M";
        };
      };

      # Root partition: NixOS system closure + boot loader files.
      # Minimized at build time; expanded to fill the SD card on first boot.
      "20-root" = {
        storePaths = [ config.system.build.toplevel ];
        contents = {
          "/boot".source = "${extlinuxDir}/boot";
          "/nix-path-registration".source = "${closureInfo}/registration";
        };
        repartConfig = {
          Type = "root";
          Format = "ext4";
          Label = "root";       # GPT partition label
          Minimize = "guess";
          # No SizeMaxBytes — allows first-boot expansion to fill the disk.
        };
      };
    };
  };

  # First-boot: expand root partition to fill the SD card and register
  # the Nix store. Ported from sd-image.nix's boot.postBootCommands.
  # The /nix-path-registration file is placed by repart's contents above
  # and removed after first boot to prevent re-running.
  boot.postBootCommands = ''
    if [ -f /nix-path-registration ]; then
      set -euo pipefail
      set -x

      # Expand root partition to fill the disk
      rootPart=$(${pkgs.util-linux}/bin/findmnt -n -o SOURCE /)
      bootDevice=$(${pkgs.util-linux}/bin/lsblk -npo PKNAME $rootPart)
      partNum=$(${pkgs.util-linux}/bin/lsblk -npo MAJ:MIN $rootPart | ${pkgs.gawk}/bin/awk -F: '{print $2}')
      echo ",+," | ${pkgs.util-linux}/bin/sfdisk -N$partNum --no-reread $bootDevice
      ${pkgs.parted}/bin/partprobe
      ${pkgs.e2fsprogs}/bin/resize2fs $rootPart

      # Register the contents of the initial Nix store
      ${config.nix.package.out}/bin/nix-store --load-db < /nix-path-registration

      # Set up system profile and NixOS marker
      touch /etc/NIXOS
      ${config.nix.package.out}/bin/nix-env -p /nix/var/nix/profiles/system --set /run/current-system

      # Prevents this from running on later boots
      rm -f /nix-path-registration
    fi
  '';
}
