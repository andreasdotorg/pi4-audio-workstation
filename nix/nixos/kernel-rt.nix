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
#
# US-114: Minimal kernel config for dedicated audio workstation.
#         NixOS common-config.nix enables hundreds of modules for a
#         general-purpose system. We disable everything not needed by
#         the Pi 4B audio workstation hardware inventory:
#
#         KEPT (required by hardware):
#           - PREEMPT_RT (D-013)
#           - USB core + xHCI, snd-usb-audio (USBStreamer, UMIK-1)
#           - USB HID (Hercules, APCmini mk2, Nektar SE25)
#           - DRM + VC4 + V3D (Mixxx, labwc Wayland compositor)
#           - I2C + GPIO (Pi HAT support, future)
#           - WiFi brcmfmac + Ethernet genet (BCM2711 built-in)
#           - SD/MMC, ext4+vfat, tmpfs, squashfs (Nix store)
#           - TCP/IP + nftables (firewall), NET_SCHED (systemd)
#           - BCM2835 watchdog + thermal (flight-case safety)
#           - Device tree overlay support (config.txt dtoverlays)
#
#         DISABLED (not needed):
#           - Bluetooth (D-019), HAM radio, InfiniBand, CAN, ATM
#           - L2TP, IPsec, MPTCP, PPP, SLIP, BRIDGE
#           - HDA/AC97/PCI sound, Intel SoC sound
#           - AMD/Nouveau/Hyper-V/Rockchip GPU drivers
#           - NFS, CIFS, Ceph, F2FS, UDF, ISO9660
#           - KVM, Xen, VirtIO
#           - TV tuners, cameras, SCSI/RAID, NVMe
#           - Joystick force-feedback, IR/LIRC, accessibility
#
#         The bcm2711_defconfig base already provides most Pi 4 support.
#         structuredExtraConfig overrides common-config via lib.mkForce.
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

          # =============================================================
          # PREEMPT_RT (D-013 mandatory)
          # =============================================================
          PREEMPT_RT = yes;
          EXPERT = yes;
          PREEMPT = lib.mkForce no;
          PREEMPT_VOLUNTARY = lib.mkForce no;
          PREEMPT_LAZY = lib.mkForce (option no);
          RT_GROUP_SCHED = lib.mkForce (option no);

          # =============================================================
          # Pi 4 hardware: explicit KEEP (ensure not accidentally stripped)
          # =============================================================
          # The following are critical and MUST remain enabled.
          # They come from bcm2711_defconfig and/or common-config.nix.
          # Listed here so future maintainers know NOT to touch them:
          #   - I2C_BCM2835, GPIOLIB, GPIO_BCM_VIRT (I2C/GPIO, future HAT)
          #   - BCM2835_THERMAL, THERMAL_GOV_STEP_WISE (thermal protection)
          #   - OF_OVERLAY, OF_DYNAMIC (device tree overlays — Pi boot)
          #   - DRM, DRM_V3D, DRM_VC4, DRM_KMS_HELPER (GPU — Mixxx, labwc)
          #   - SND, SND_SOC (required by DRM_VC4 — see Sound section)
          #   - SND_USB_AUDIO, SND_USB_AUDIO_MIDI_V2 (USBStreamer, UMIK-1)
          #   - INOTIFY_USER, TMPFS, EPOLL (systemd hard requirements)
          #   - BCM2835_WDT (watchdog)
          #   - BRCMFMAC (WiFi), GENET (Ethernet)
          DRM_VC4_HDMI_CEC = lib.mkForce yes;

          # =============================================================
          # Networking: strip unused protocols
          # =============================================================
          # Keep: TCP/IP, IPv6, nftables inet family, NET_SCHED (systemd),
          #        CGROUP_BPF, NET_CLS_BPF (systemd eBPF accounting)
          HAMRADIO = lib.mkForce no;
          CAN = option no;
          ATM = option no;
          ARCNET = option no;
          INFINIBAND = lib.mkForce (option no);
          NET_FC = lib.mkForce no;
          WAN = lib.mkForce no;
          HIPPI = lib.mkForce (option no);

          # Bridge — not needed; no VMs, containers, or bridged interfaces.
          # nftables uses inet family (not bridge family) for our firewall.
          BRIDGE = lib.mkForce (option no);
          BRIDGE_NETFILTER = lib.mkForce (option no);
          NF_TABLES_BRIDGE = lib.mkForce (option no);
          BRIDGE_VLAN_FILTERING = lib.mkForce no;

          # Tunnels / VPN protocols
          L2TP_V3 = lib.mkForce no;
          L2TP_IP = lib.mkForce (option no);
          L2TP_ETH = lib.mkForce (option no);
          NET_FOU_IP_TUNNELS = lib.mkForce (option no);
          IPV6_FOU_TUNNEL = lib.mkForce (option no);
          INET_ESPINTCP = lib.mkForce no;
          INET6_ESPINTCP = lib.mkForce no;
          TLS = lib.mkForce (option no);  # kTLS — kernel TLS offload, not userspace TLS
          MPTCP = lib.mkForce no;
          MPTCP_IPV6 = lib.mkForce no;
          BONDING = lib.mkForce (option no);

          # PPP / SLIP — no dial-up
          PPP_MULTILINK = lib.mkForce no;
          PPP_FILTER = lib.mkForce no;
          SLIP_COMPRESSED = lib.mkForce no;
          SLIP_SMART = lib.mkForce no;

          # =============================================================
          # Bluetooth: fully disabled (D-019)
          # =============================================================
          # Pi 4 has on-board BCM43455 BT sharing UART with WiFi.
          # We use USB audio (USBStreamer) and USB MIDI (all controllers).
          # config.txt should have dtoverlay=disable-bt.
          BT = lib.mkForce (option no);
          BT_HCIUART = lib.mkForce (option no);
          BT_BCM = lib.mkForce (option no);
          BT_RFCOMM = lib.mkForce (option no);
          BT_BNEP = lib.mkForce (option no);
          BT_HIDP = lib.mkForce (option no);
          BT_HCIBTUSB_MTK = lib.mkForce no;
          BT_QCA = lib.mkForce (option no);
          BT_RFCOMM_TTY = lib.mkForce (option no);

          # =============================================================
          # Sound: strip non-USB audio (keep SND_SOC for DRM_VC4)
          # =============================================================
          # Keep: SND core, SND_USB_AUDIO, SND_USB_AUDIO_MIDI_V2
          # No PCI bus, no HDA codec, no AC97 on Pi 4 — top-level toggles
          # disable entire subsystems more effectively than individual options.
          #
          # CRITICAL: SND_SOC MUST remain enabled. DRM_VC4 (the Pi 4's
          # primary display driver) depends on "SND && SND_SOC" for HDMI
          # audio output. Without SND_SOC, DRM_VC4 cannot be compiled and
          # the Pi has no display driver. The defconfig sets SND_SOC=m.
          # We keep it and only disable individual SoC codecs we don't need.
          SND_PCI = lib.mkForce (option no);
          SND_USB_CAIAQ_INPUT = lib.mkForce no;

          # =============================================================
          # GPU / Display: strip non-Pi drivers
          # =============================================================
          # Keep: DRM, DRM_VC4, DRM_V3D, DRM_KMS_HELPER, DRM_GEM_DMA_HELPER,
          #        DRM_SIMPLEDRM, DRM_FBDEV_EMULATION, FRAMEBUFFER_CONSOLE
          DRM_AMDGPU_SI = lib.mkForce no;
          DRM_AMDGPU_CIK = lib.mkForce no;
          DRM_AMD_ACP = lib.mkForce no;
          DRM_AMD_SECURE_DISPLAY = lib.mkForce (option no);
          DRM_AMD_ISP = lib.mkForce (option no);
          DRM_NOUVEAU_GSP_DEFAULT = lib.mkForce (option no);
          DRM_HYPERV = lib.mkForce (option no);

          # Rockchip — not our SoC
          ROCKCHIP_DW_HDMI_QP = lib.mkForce (option no);
          ROCKCHIP_DW_MIPI_DSI2 = lib.mkForce (option no);

          # Allwinner — not our SoC
          SUN8I_DE2_CCU = lib.mkForce no;

          # Legacy framebuffer drivers for desktop GPUs
          FB_NVIDIA_I2C = lib.mkForce no;
          FB_RIVA_I2C = lib.mkForce no;
          FB_ATY_CT = lib.mkForce no;
          FB_ATY_GX = lib.mkForce no;
          FB_SAVAGE_I2C = lib.mkForce no;
          FB_SAVAGE_ACCEL = lib.mkForce no;
          FB_SIS_300 = lib.mkForce no;
          FB_SIS_315 = lib.mkForce no;
          FB_3DFX_ACCEL = lib.mkForce no;

          # =============================================================
          # Filesystems: strip network / exotic FS
          # =============================================================
          # Keep: ext4, vfat (boot), tmpfs (systemd), squashfs (Nix store),
          #        devtmpfs, NLS (vfat mount), FUSE (low cost, useful)
          # boot.supportedFilesystems already forces [ "ext4" "vfat" ]
          # Top-level toggles disable entire subsystems (architect Issue 5)
          NFS_FS = lib.mkForce (option no);
          NFSD = lib.mkForce (option no);
          CIFS = lib.mkForce (option no);
          CEPH_FS = lib.mkForce (option no);
          F2FS_FS = lib.mkForce (option no);
          UDF_FS = lib.mkForce (option no);
          SUNRPC_DEBUG = lib.mkForce no;
          ISO9660_FS = lib.mkForce (option no);

          # =============================================================
          # Virtualisation: fully disabled (parent-level)
          # =============================================================
          # VIRTUALIZATION is the top-level menuconfig that gates KVM, Xen,
          # vhost, etc. Disabling it cascades to all child options —
          # KVM_MMIO, KVM_VFIO, KVM_GENERIC_DIRTYLOG_READ_PROTECT, VIRT_DRIVERS,
          # VIRTIO_MENU, XEN, HYPERV are all unreachable with VIRTUALIZATION=n.
          # The bcm2711_defconfig sets VIRTUALIZATION=y and KVM=y, but we
          # have no VMs or containers on this dedicated audio workstation.
          VIRTUALIZATION = lib.mkForce no;
          KSM = lib.mkForce no;

          # =============================================================
          # Media: fully disabled (parent-level)
          # =============================================================
          # MEDIA_SUPPORT is the top-level menuconfig for V4L2, DVB, cameras,
          # tuners, etc. Disabling it cascades to all media sub-options —
          # MEDIA_DIGITAL_TV_SUPPORT, MEDIA_CAMERA_SUPPORT, MEDIA_ANALOG_TV_SUPPORT,
          # MEDIA_PCI_SUPPORT, STAGING_MEDIA, tuner modules are all unreachable.
          # The bcm2711_defconfig sets MEDIA_SUPPORT=m.
          #
          # MEDIA_CEC_SUPPORT is independent (sourced before MEDIA_SUPPORT in
          # drivers/media/Kconfig). CEC is needed for DRM_VC4_HDMI_CEC, so
          # keep it enabled. RC_CORE (IR remotes) is also independent.
          MEDIA_SUPPORT = lib.mkForce (option no);
          RC_CORE = lib.mkForce no;

          # =============================================================
          # USB: strip gadget mode
          # =============================================================
          # Pi 4B USB-C is power-only (OTG-capable but no gadget use case)
          USB_GADGET = option no;

          # =============================================================
          # Storage: strip SCSI / RAID / NVMe
          # =============================================================
          SCSI_LOWLEVEL = lib.mkForce no;
          SCSI_LOWLEVEL_PCMCIA = lib.mkForce no;
          SCSI_SAS_ATA = lib.mkForce no;
          MEGARAID_NEWGEN = lib.mkForce no;
          FUSION = lib.mkForce no;
          # Pi 4B has no NVMe — disable the entire subsystem.
          # BLK_DEV_NVME is the top-level NVMe block device; disabling it
          # cascades to all transport modules (TCP, FC) and their TLS deps.
          # Without this, NVME_TCP_TLS selects TLS, blocking our TLS=no.
          BLK_DEV_NVME = lib.mkForce (option no);
          NVME_FC = lib.mkForce (option no);
          NVME_TCP = lib.mkForce (option no);
          NVME_MULTIPATH = lib.mkForce no;
          NVME_TARGET = lib.mkForce (option no);
          NVME_HWMON = lib.mkForce no;

          # =============================================================
          # Platform: strip non-Pi hardware
          # =============================================================
          CHROME_PLATFORMS = lib.mkForce (option no);
          HSA_AMD = lib.mkForce (option no);
          HSA_AMD_P2P = lib.mkForce (option no);
          ACPI_HOTPLUG_CPU = lib.mkForce (option no);
          ACPI_HOTPLUG_MEMORY = lib.mkForce (option no);
          GOOGLE_FIRMWARE = lib.mkForce no;

          # =============================================================
          # HID: strip joystick force-feedback drivers
          # =============================================================
          # None of these USB game controllers are in our hardware inventory.
          # Our MIDI controllers (Hercules, APCmini, Nektar) use standard
          # USB HID which remains enabled.
          HID_ACRUX_FF = lib.mkForce no;
          DRAGONRISE_FF = lib.mkForce no;
          GREENASIA_FF = lib.mkForce no;
          HOLTEK_FF = lib.mkForce no;
          JOYSTICK_PSXPAD_SPI_FF = lib.mkForce no;
          LOGITECH_FF = lib.mkForce no;
          LOGIG940_FF = lib.mkForce no;
          LOGIWHEELS_FF = lib.mkForce no;
          NINTENDO_FF = lib.mkForce (option no);
          NVIDIA_SHIELD_FF = lib.mkForce (option no);
          PLAYSTATION_FF = lib.mkForce (option no);
          SONY_FF = lib.mkForce no;
          SMARTJOYPLUS_FF = lib.mkForce no;
          THRUSTMASTER_FF = lib.mkForce no;
          ZEROPLUS_FF = lib.mkForce no;
          LOGIRUMBLEPAD2_FF = lib.mkForce no;

          # =============================================================
          # Misc: strip remaining unused subsystems
          # =============================================================
          ACCESSIBILITY = lib.mkForce no;
          AUXDISPLAY = lib.mkForce no;
        };
      };
    }
  );
in
{
  boot.kernelPackages = lib.mkForce linuxPackages_rpi4_rt;
}
