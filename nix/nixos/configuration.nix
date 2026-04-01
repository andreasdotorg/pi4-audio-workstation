# configuration.nix — top-level NixOS configuration for the Pi 4 Audio Workstation
#
# Imports all modules EXCEPT the deployment method (sd-image.nix or disko.nix).
# The deployment method is added at the flake level:
#   - nixosConfigurations.mugge: adds sd-image.nix for image builds
#   - nixosConfigurations.mugge-deploy: adds disko.nix for nixos-anywhere
#
# The nixos-hardware.nixosModules.raspberry-pi-4 import is handled
# at the flake level, not here.
#
# pi4audio-packages is passed via specialArgs from flake.nix — it contains
# the Nix-built packages for our custom Rust services (graph-manager,
# level-bridge, pcm-bridge, signal-gen).
{ config, lib, pkgs, pi4audio-packages, ... }:

{
  imports = [
    ./hardware.nix
    ./firmware.nix
    ./users.nix
    ./network.nix
    # Phase 2: PipeWire + audio stack
    ./audio/pipewire.nix
    ./audio/wireplumber.nix
    ./audio/udev.nix
    # Phase 5: PREEMPT_RT kernel (D-013 mandatory)
    ./kernel-rt.nix
    # Phase 4: Display + applications
    ./display.nix
    ./applications.nix
    # Phase 3: Custom service modules
    ./services/graph-manager.nix
    ./services/level-bridge.nix
    ./services/pcm-bridge.nix
    ./services/signal-gen.nix
    ./services/web-ui.nix
    # Production defaults: enables all services with correct parameters
    ./production.nix
  ];

  # System basics
  system.stateVersion = "25.11";
  time.timeZone = "Europe/Berlin";
  i18n.defaultLocale = "en_US.UTF-8";

  # Enable flakes on the target system
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Closure trim — dedicated audio workstation needs none of these.
  # Audit (2026-03-29): ~5000 derivations in full closure; disabling
  # docs alone saves ~1673 derivations (~33%).
  documentation.nixos.enable = false;  # NixOS manual + manpages
  documentation.doc.enable = false;    # /share/doc tree
  services.speechd.enable = false;     # speech-dispatcher (no screen reader)
  boot.initrd.services.lvm.enable = false;  # LVM not used (simple partition)

  # US-072: Only ext4 + vfat needed (root + boot per disko.nix).
  # profiles/base.nix (imported by sd-image-aarch64.nix) enables btrfs,
  # cifs, f2fs, ntfs, vfat, xfs, and ZFS by default.  ZFS is the critical
  # one: it is an out-of-tree kernel module whose build pulls the kernel
  # -dev output (full source tree rsync, ~1.5 GB) into the closure,
  # overflowing the 30 GB builder disk.  mkForce replaces the full set.
  boot.supportedFilesystems = lib.mkForce [ "ext4" "vfat" ];

  # US-072: Disable all-hardware installer defaults.
  # sd-image.nix imports all-hardware.nix which sets enableAllHardware=true,
  # pulling ~50 SCSI/RAID/NVMe/VirtIO initrd modules.  Our custom kernel
  # (kernel-rt.nix) strips SCSI_LOWLEVEL, BLK_DEV_NVME, VIRTUALIZATION,
  # so those modules don't exist → modules-shrunk build fails.
  hardware.enableAllHardware = lib.mkForce false;

  # Disable kernel.nix default initrd modules (ahci, sata_*, nvme, etc.).
  # Pi 4 has no SATA, NVMe, or PCI storage controllers.
  boot.initrd.includeDefaultModules = false;

  # Pi 4 initrd: only modules needed for SD card boot.
  # Most Pi 4 hardware support is built-in (=y) in our kernel config:
  #   ext4, SCSI (sd_mod), USB storage/UAS, xHCI, USB HID, HID generic,
  #   PCIe brcmstb, reset-raspberrypi, BLK_DEV_SD.
  # Only these are loadable modules (=m) needed at boot:
  boot.initrd.availableKernelModules = lib.mkForce [
    "mmc_block"     # SD/MMC block device (=m) — required for SD card boot
    "vc4"           # Pi 4 display driver (=m) — early KMS console
    "ehci_hcd"      # USB 2.0 host controller (=m) — emergency keyboard
  ];

  # No LVM or device-mapper on this system.
  boot.initrd.kernelModules = lib.mkForce [];

  # Allow specific unfree packages (Reaper DAW)
  nixpkgs.config.allowUnfreePredicate = pkg:
    builtins.elem (lib.getName pkg) [ "reaper" ];

  # Minimal packages for Phase 1 validation
  environment.systemPackages = with pkgs; [
    vim
    git
    htop
  ];
}
