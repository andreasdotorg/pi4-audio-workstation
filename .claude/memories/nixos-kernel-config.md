# NixOS Kernel Config — mugge

## Topic: Kernel config pipeline and override mechanics (2026-04-01)

**Context:** US-114 — trimming the NixOS kernel config for Pi 4B audio workstation.
**Learning:** The NixOS kernel config pipeline is: `bcm2711_defconfig` -> `common-config.nix` (NixOS defaults) -> `structuredExtraConfig` (our overrides). Our overrides win via `lib.mkForce`. The `ignoreConfigErrors = true` in `linux-rpi.nix` means absent Kconfig symbols don't break the build.
**Source:** Worker-5, US-114 implementation.
**Tags:** nix, kernel, kconfig, structuredExtraConfig, mkForce, bcm2711

## Topic: ZFS was the -dev output blocker (2026-04-01)

**Context:** US-114 — kernel builds failed due to disk full (30GB builder and 87GB local).
**Learning:** `boot.supportedFilesystems` defaults include ZFS, which is an out-of-tree module requiring the kernel `-dev` output (full source tree, ~1.5GB). `lib.mkForce [ "ext4" "vfat" ]` in configuration.nix eliminates this. This was already done before US-114.
**Source:** Worker-5, US-114 investigation.
**Tags:** nix, kernel, zfs, dev-output, disk-space, supportedFilesystems

## Topic: autoModules = true behavior on aarch64 (2026-04-01)

**Context:** US-114 — understanding why disabled modules might reappear.
**Learning:** Even after setting `CONFIG_FOO=n` in structuredExtraConfig, new Kconfig options from kernel upgrades will be auto-answered "m" (module) by `generate-config.pl` because `autoModules = true` is the default on aarch64. This means kernel upgrades may add new modules. Our approach (disable known bloat) is fine but requires vigilance on upgrades.
**Source:** Worker-5, US-114 implementation.
**Tags:** nix, kernel, autoModules, aarch64, generate-config, module-creep

## Topic: SND_SOC MUST stay enabled — DRM_VC4 dependency (2026-04-01, corrected 2026-04-01)

**Context:** US-114 — safely trimming audio subsystem modules.
**Learning:** `snd-usb-audio` lives under `SND_USB` in the Kconfig tree, NOT under `SND_SOC`. However, **disabling SND_SOC is NOT safe** on Pi 4 — `DRM_VC4` (the Pi 4 display driver) depends on `SND && SND_SOC`. Disabling `SND_SOC` would break the display driver entirely. `SND_SOC` MUST stay enabled even though our audio path is USB-only (USBStreamer). Individual `SND_SOC_*` machine drivers (e.g., `SND_BCM2835_SOC_I2S`) can be disabled safely, but the `SND_SOC` subsystem itself cannot.
**Source:** Worker-5 (original, incorrect), corrected by QE flag + Architect review + commit 7976ee0.
**Tags:** kernel, audio, snd-usb-audio, snd-soc, kconfig, usbstreamer, drm-vc4, CORRECTED

## Topic: nix eval cross-arch performance (2026-04-01)

**Context:** US-114 — validating kernel config changes on x86_64 build host targeting aarch64.
**Learning:** `nix eval` of `nixosConfigurations.mugge.config.*` is very slow for cross-arch (x86_64 evaluating aarch64 target). Concurrent evals cause SQLite eval-cache contention. Always run one eval at a time.
**Source:** Worker-5, US-114 build experience.
**Tags:** nix, eval, cross-arch, aarch64, sqlite, performance

## Topic: lib.kernel type selection guide (2026-04-01)

**Context:** US-114 — writing structuredExtraConfig entries.
**Learning:** Use `no` for options that definitely exist in Kconfig. Use `option no` for options that might not exist (prevents build failure if symbol is absent). Use `lib.mkForce no` when overriding values set by `common-config.nix`.
**Source:** Worker-5, US-114 implementation.
**Tags:** nix, kernel, lib.kernel, structuredExtraConfig, option, mkForce
