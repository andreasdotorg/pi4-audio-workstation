# disko.nix — Disk partitioning for nixos-anywhere deployment
#
# Defines the SD card partition layout for the Pi 4 Audio Workstation.
# Used by nixos-anywhere for fresh installs on a Pi reachable via SSH.
#
# Layout (GPT):
#   Partition 1: 256 MiB FAT32 ESP — VideoCore firmware, U-Boot, config.txt,
#                DTBs. ESP type required for VideoCore EEPROM to find the
#                boot partition on GPT. U-Boot efi_mgr errors on ESP are
#                harmless — it falls through to extlinux.
#   Partition 2: rest of disk ext4 — NixOS root filesystem
#
# This module is NOT imported by configuration.nix. It's added as an extra
# module by the mugge-deploy NixOS configuration in flake.nix.
#
# Firmware population is handled by firmware.nix's activation script, which
# runs during nixos-anywhere's chroot install (before first boot) and on
# every subsequent nixos-rebuild switch.
#
# F-273: Filesystem labels (FIRMWARE, NIXOS_SD) are set explicitly to match
# repart-image.nix. Both deployment paths reference partitions via
# /dev/disk/by-label/ (filesystem labels), ensuring nixos-rebuild switch
# works regardless of whether the SD card was created by repart or
# nixos-anywhere. The fileSystems entries below match the shared
# declarations in configuration.nix.
#
# T-072-18: nixos-anywhere fresh install
# Usage: nixos-anywhere --flake .#mugge-deploy root@<target-host>
#
# T-072-19: Incremental upgrade (after initial install)
# Usage: nix run nixpkgs#nixos-rebuild -- switch --flake .#mugge-deploy --target-host ela@<target-host> --sudo
{ config, lib, pkgs, ... }:

{
  # F-273: Override disko's auto-generated fileSystems to use filesystem
  # labels (by-label/) instead of GPT partition labels (by-partlabel/).
  # Disko generates entries using by-partlabel/ which only works on GPT.
  # We use by-label/ (filesystem labels) because they work on both GPT
  # (nixos-anywhere) and any future partition table type. These overrides
  # match the fileSystems declared in configuration.nix.
  fileSystems."/" = lib.mkForce {
    device = "/dev/disk/by-label/NIXOS_SD";
    fsType = "ext4";
  };

  fileSystems."/boot/firmware" = lib.mkForce {
    device = "/dev/disk/by-label/FIRMWARE";
    fsType = "vfat";
    options = [ "nofail" "noauto" ];
  };

  disko.devices.disk.main = {
    type = "disk";
    # On Pi 4B, the SD card is /dev/mmcblk0.
    device = "/dev/mmcblk0";

    content = {
      type = "gpt";

      partitions = {
        # Firmware partition: VideoCore blobs, U-Boot, config.txt
        # ESP (EF00) — required for Pi 4 boot. VideoCore EEPROM on GPT
        # only recognizes ESP and Microsoft Basic Data type partitions.
        #
        # U-Boot's efi_mgr bootmeth logs EFI errors when it runs on
        # the ESP (harmless noise) — it fails to find bootable EFI
        # entries, then falls through to extlinux on the root partition.
        firmware = {
          size = "256M";
          type = "EF00";  # EFI System Partition (C12A7328)
          content = {
            type = "filesystem";
            format = "vfat";
            # F-273: Filesystem label matching repart-image.nix.
            extraArgs = [ "-n" "FIRMWARE" ];
            mountpoint = "/boot/firmware";
            mountOptions = [ "nofail" "noauto" ];
          };
        };

        # Root filesystem: NixOS
        root = {
          size = "100%";
          content = {
            type = "filesystem";
            format = "ext4";
            # F-273: Filesystem label matching repart-image.nix.
            # -O ^orphan_file: U-Boot 2025.10 ext4 driver doesn't support
            # the orphan_file INCOMPAT feature (0x20000), enabled by default
            # in e2fsprogs >= 1.47.3. Without this flag, U-Boot can't read
            # the root partition to find extlinux.conf. Safe to disable —
            # falls back to linked-list orphan tracking.
            extraArgs = [ "-L" "NIXOS_SD" "-O" "^orphan_file" ];
            mountpoint = "/";
            mountOptions = [ "defaults" ];
          };
        };
      };
    };
  };
}
