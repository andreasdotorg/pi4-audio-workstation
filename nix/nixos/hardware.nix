# hardware.nix — Raspberry Pi 4 hardware configuration for the Audio Workstation
#
# This module is intended to be used alongside nixos-hardware's
# nixosModules.raspberry-pi-4, which is imported in flake.nix.
# We set options here that are specific to our use-case or that
# need to override / complement the nixos-hardware defaults.
{ config, lib, pkgs, ... }:

{
  # ── Boot loader ────────────────────────────────────────────────
  # extlinux is the standard approach for U-Boot-based ARM boards.
  # The nixos-hardware module does NOT set a bootloader, so we must.
  boot.loader.generic-extlinux-compatible.enable = true;
  boot.loader.grub.enable = false;

  # ── Kernel ─────────────────────────────────────────────────────
  # The PREEMPT_RT kernel is set in kernel-rt.nix (Phase 5) via
  # lib.mkForce, overriding both nixos-hardware's mkDefault and any
  # other default. See kernel-rt.nix for details.

  # D-040: snd-aloop removed — CamillaDSP abandoned, PW filter-chain
  # convolver handles all DSP natively (no ALSA loopback needed).

  # brcmfmac: WiFi unused (Ethernet only). The BCM43455 driver triggers a
  # FORTIFY_SOURCE memcpy kernel WARNING with full stack trace on boot.
  # Blacklisting eliminates the stack dump and also prevents brcmfmac_wcc,
  # brcmutil, and cfg80211 from loading (no other consumers).
  boot.blacklistedKernelModules = [ "brcmfmac" ];

  # ── Firmware ───────────────────────────────────────────────────
  hardware.enableRedistributableFirmware = true;

  # ── GPU / display ──────────────────────────────────────────────
  # We want full KMS (vc4-kms-v3d), NOT the legacy fake-KMS overlay.
  # The nixos-hardware RPi 4 module exposes hardware.raspberry-pi."4".fkms-3d;
  # make sure it is off — we apply full KMS via hardware.deviceTree.overlays.
  hardware.raspberry-pi."4".fkms-3d.enable = lib.mkForce false;

  # Full KMS device tree overlay (vc4-kms-v3d equivalent).
  #
  # The VideoCore firmware processes dtoverlay=vc4-kms-v3d from config.txt,
  # but U-Boot overrides the firmware-patched DTB with the base DTB from
  # its FDTDIR. NixOS's hardware.deviceTree.overlays applies overlays at
  # Nix build time, producing a pre-patched DTB that U-Boot loads directly.
  #
  # This overlay enables the same nodes as the upstream vc4-kms-v3d-pi4.dtbo:
  # V3D (3D engine), VC4 (DRM driver), HVS (hardware video scaler),
  # TXP (writeback), all 5 pixelvalves, and both HDMI controllers.
  # The legacy firmware framebuffer is disabled.
  # CMA is set to 256MB matching gpu_mem=256 in config.txt.
  hardware.deviceTree.overlays = [
    {
      name = "rpi4-vc4-kms-v3d";
      # Only apply to Pi 4 Model B (not CM4 variants which lack the fb node).
      filter = "bcm2711-rpi-4-b.dtb";
      dtsText = ''
        /dts-v1/;
        /plugin/;

        / {
          compatible = "brcm,bcm2711";

          /* CMA: 256 MiB (matches gpu_mem=256 in config.txt) */
          fragment@0 {
            target = <&cma>;
            __overlay__ {
              size = <0x10000000>;
            };
          };

          /* Disable legacy firmware framebuffer */
          fragment@1 {
            target = <&fb>;
            __overlay__ {
              status = "disabled";
            };
          };

          /* Enable V3D 3D engine */
          fragment@2 {
            target = <&v3d>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable VC4 DRM driver (gpu node) */
          fragment@3 {
            target = <&vc4>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable HVS (hardware video scaler) */
          fragment@4 {
            target = <&hvs>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable TXP (writeback connector) */
          fragment@5 {
            target = <&txp>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable pixelvalve 0 (DSI0 / DPI) */
          fragment@6 {
            target = <&pixelvalve0>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable pixelvalve 1 (DSI1) */
          fragment@7 {
            target = <&pixelvalve1>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable pixelvalve 2 (HDMI0) */
          fragment@8 {
            target = <&pixelvalve2>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable pixelvalve 3 (HDMI1) */
          fragment@9 {
            target = <&pixelvalve3>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable pixelvalve 4 (composite video) */
          fragment@10 {
            target = <&pixelvalve4>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable HDMI0 */
          fragment@11 {
            target = <&hdmi0>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable HDMI1 */
          fragment@12 {
            target = <&hdmi1>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable DDC0 (HDMI0 EDID I2C) */
          fragment@13 {
            target = <&ddc0>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable DDC1 (HDMI1 EDID I2C) */
          fragment@14 {
            target = <&ddc1>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Disable firmware KMS (replaced by full KMS) */
          fragment@15 {
            target = <&firmwarekms>;
            __overlay__ {
              status = "disabled";
            };
          };

          /* Enable DVP clock controller (provides audio clock for HDMI) */
          fragment@16 {
            target = <&dvp>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Enable AON interrupt controller (HDMI interrupts) */
          fragment@17 {
            target = <&aon_intr>;
            __overlay__ {
              status = "okay";
            };
          };

          /* Disable legacy BCM2835 HDMI audio (conflicts with VC4 HDMI audio) */
          fragment@18 {
            target-path = "/chosen";
            __overlay__ {
              bootargs = "snd_bcm2835.enable_hdmi=0";
            };
          };
        };
      '';
    }
    # D-019: Disable Bluetooth hardware in the device tree.
    # The BCM43455 combo chip shares UART between BT and serial console.
    # BT kernel support is stripped (kernel-rt.nix BT=no). This overlay
    # disables the BT UART node, re-assigns uart0 pins to serial console,
    # and disables the bt node. Mirrors dtoverlay=disable-bt in config.txt
    # (which the VideoCore firmware processes for firmware-level BT disable).
    {
      name = "rpi4-disable-bt";
      filter = "bcm2711-rpi-4-b.dtb";
      dtsText = ''
        /dts-v1/;
        /plugin/;

        / {
          compatible = "brcm,bcm2711";

          /* Disable mini-UART (used by BT) */
          fragment@0 {
            target = <&uart1>;
            __overlay__ {
              status = "disabled";
            };
          };

          /* Re-enable PL011 UART for serial console */
          fragment@1 {
            target = <&uart0>;
            __overlay__ {
              pinctrl-names = "default";
              pinctrl-0 = <&uart0_pins>;
              status = "okay";
            };
          };

          /* Disable Bluetooth node */
          fragment@2 {
            target = <&bt>;
            __overlay__ {
              status = "disabled";
            };
          };

          /* Clear UART0 pin muxing (release from BT) */
          fragment@3 {
            target = <&uart0_pins>;
            __overlay__ {
              brcm,pins;
              brcm,function;
              brcm,pull;
            };
          };

          /* Clear BT pin muxing */
          fragment@4 {
            target = <&bt_pins>;
            __overlay__ {
              brcm,pins;
              brcm,function;
              brcm,pull;
            };
          };

          /* Remap serial aliases: serial0→PL011, serial1→mini-UART */
          fragment@5 {
            target-path = "/aliases";
            __overlay__ {
              serial0 = "/soc/serial@7e201000";
              serial1 = "/soc/serial@7e215040";
            };
          };
        };
      '';
    }
  ];
}
