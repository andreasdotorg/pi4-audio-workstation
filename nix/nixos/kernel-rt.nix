# kernel-rt.nix — PREEMPT_RT kernel for the Pi 4 Audio Workstation (Phase 5)
#
# Overrides the stock RPi 4 kernel (linuxPackages_rpi4) with
# CONFIG_PREEMPT_RT=y via structuredExtraConfig, and pins the source
# to RPi fork 6.12.62 which includes the V3D ABBA deadlock fix.
#
# PREEMPT_RT was merged into mainline Linux 6.12-rc1 and is available
# as a Kconfig choice in the RPi fork (rpi-6.12.y). No external RT
# patches are needed — the RPi fork source already includes full RT
# support. This matches how Debian/RPi OS builds kernel8_rt.img
# (same source, CONFIG_PREEMPT_RT=y).
#
# Prerequisites verified in RPi fork commit a1073743767f (6.12.62):
#   - arch/arm64/Kconfig selects ARCH_SUPPORTS_RT
#   - bcm2711_defconfig sets CONFIG_EXPERT=y (required by PREEMPT_RT)
#
# D-013: PREEMPT_RT is mandatory for this project.
# D-022: V3D ABBA deadlock fix (upstream commit 09fb2c6f4093, issue
#         raspberrypi/linux#7035) is included in RPi fork >= 6.12.62.
#         The nixos-hardware module pins 6.12.47 (tag stable_20250916)
#         which does NOT include this fix. We pin 6.12.62 explicitly.
{ config, lib, pkgs, ... }:

let
  # Pin RPi kernel source to 6.12.62 from RPi-Distro packaging.
  # This is the same commit used by nixpkgs' linux-rpi.nix and matches
  # the Debian RPi OS kernel that has been validated on our Pi.
  # The V3D fix (09fb2c6f4093) was merged to the RPi fork on 2025-10-28,
  # well before this release.
  rpiKernelSrc = pkgs.fetchFromGitHub {
    owner = "raspberrypi";
    repo = "linux";
    rev = "a1073743767f9e7fdc7017ababd2a07ea0c97c1c";
    hash = "sha256-jcSzPoCCnmZU1GDBUWAljIUjZRzbfdh2aQB9/GOc5mQ=";
  };

  linuxPackages_rpi4_rt = pkgs.linuxPackagesFor (
    pkgs.linuxKernel.kernels.linux_rpi4.override {
      argsOverride = {
        # Pin to 6.12.62 source (includes V3D fix, D-022)
        version = "6.12.62-1+rpt1";
        modDirVersion = "6.12.62";
        src = rpiKernelSrc;

        structuredExtraConfig = with lib.kernel; {
          # Enable full PREEMPT_RT (real-time preemption)
          PREEMPT_RT = yes;
          # EXPERT is required by PREEMPT_RT — already in bcm2711_defconfig,
          # but set explicitly to be safe
          EXPERT = yes;
          # PREEMPT_RT is a choice that deselects the other preemption models
          PREEMPT = lib.mkForce no;
          PREEMPT_VOLUNTARY = lib.mkForce no;
          # RT_GROUP_SCHED is incompatible with PREEMPT_RT
          RT_GROUP_SCHED = lib.mkForce (option no);
        };
      };
    }
  );
in
{
  boot.kernelPackages = lib.mkForce linuxPackages_rpi4_rt;
}
