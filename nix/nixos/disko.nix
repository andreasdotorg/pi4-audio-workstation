# disko.nix — Disk partitioning for nixos-anywhere deployment
#
# Defines the SD card partition layout for the Pi 4 Audio Workstation.
# Used by nixos-anywhere for fresh installs on a Pi reachable via SSH.
#
# Layout (GPT):
#   Partition 1: 256 MiB FAT32 (EFI System) — VideoCore firmware, U-Boot,
#                config.txt, DTBs. Pi 4B EEPROM bootloader supports GPT since
#                late 2020.
#   Partition 2: rest of disk ext4 — NixOS root filesystem
#
# This module is NOT imported by configuration.nix. It's added as an extra
# module by the mugge-deploy NixOS configuration in flake.nix.
#
# Firmware population is handled by firmware.nix's activation script, which
# runs during nixos-anywhere's chroot install (before first boot) and on
# every subsequent nixos-rebuild switch.
#
# T-072-18: nixos-anywhere fresh install
# Usage: nixos-anywhere --flake .#mugge-deploy root@<target-host>
#
# T-072-19: Incremental upgrade (after initial install)
# Usage: nix run nixpkgs#nixos-rebuild -- switch --flake .#mugge-deploy --target-host ela@<target-host> --sudo
{ config, lib, pkgs, ... }:

{
  # F-266: Mark /boot/firmware as needed for boot so that switch-to-configuration
  # does not try to restart the mount unit during `nixos-rebuild switch`.
  # The firmware partition genuinely IS needed for boot (VideoCore firmware,
  # U-Boot, config.txt, DTBs).  Without this, systemd attempts to restart
  # boot-firmware.mount during a live switch, which fails because the
  # partition is already mounted.
  #
  # NOTE: Pi partition labels (by-partlabel/disk-main-firmware) were NOT
  # verified on the live Pi (offline at time of fix).  Verify on next deploy
  # with: lsblk -o NAME,PARTLABEL /dev/mmcblk0
  fileSystems."/boot/firmware".neededForBoot = true;

  disko.devices.disk.main = {
    type = "disk";
    # On Pi 4B, the SD card is /dev/mmcblk0.
    device = "/dev/mmcblk0";

    content = {
      type = "gpt";

      partitions = {
        # Firmware partition: VideoCore blobs, U-Boot, config.txt
        firmware = {
          size = "256M";
          type = "EF00";  # EFI System Partition
          content = {
            type = "filesystem";
            format = "vfat";
            mountpoint = "/boot/firmware";
            mountOptions = [ "defaults" "noatime" ];
          };
        };

        # Root filesystem: NixOS
        root = {
          size = "100%";
          content = {
            type = "filesystem";
            format = "ext4";
            mountpoint = "/";
            mountOptions = [ "defaults" "noatime" ];
          };
        };
      };
    };
  };
}
