# HOWTO: NixOS Deployment and Upgrades

This guide covers the two deployment methods for the Pi 4 Audio Workstation:
initial installation via `nixos-anywhere` and incremental upgrades via
`nixos-rebuild`. Both use the `mugge-deploy` flake configuration, which
includes the disko partitioning module.

T-072-19a (US-072: NixOS Build)


## 1. Prerequisites

- Nix with flakes enabled on the build host
- SSH access to the target Pi as user `ela` (key-based, passwordless sudo)
- The Pi must be network-reachable from the build host
- For nixos-anywhere: the Pi must be running some Linux with SSH access
  (DietPi, Raspberry Pi OS, or an existing NixOS install)


## 2. Initial Installation (nixos-anywhere)

Use `nixos-anywhere` for the first NixOS install on a Pi that is currently
running another OS (e.g., DietPi, Raspberry Pi OS). This wipes the SD card,
repartitions it via disko, and installs NixOS.

**WARNING:** This is destructive. The entire SD card will be reformatted.
Back up any data on the Pi first.

**SAFETY:** The USBStreamer will lose its audio stream during the reboot.
Ensure amplifiers are OFF before proceeding. See `docs/operations/safety.md`.

```sh
# From the project root on the build host:
nix run github:nix-community/nixos-anywhere -- \
    --flake .#mugge-deploy \
    root@<target-host>
```

What nixos-anywhere does:
1. Boots a minimal NixOS installer via kexec on the target
2. Runs disko to partition the SD card (256M FAT32 firmware + ext4 root)
3. Installs the NixOS system closure
4. Runs activation scripts (including firmware population to /boot/firmware)
5. Reboots into the new NixOS system

After installation, run the smoke test to verify:

```sh
scp scripts/nixos-smoke-test.sh ela@<target-host>:/tmp/
ssh ela@<target-host> sudo bash /tmp/nixos-smoke-test.sh
```


## 3. Incremental Upgrades (nixos-rebuild)

For ongoing updates after the initial NixOS installation, use `nixos-rebuild`.
This is the standard NixOS upgrade path: it builds the new system closure,
switches to it, and runs activation scripts. No repartitioning, no data loss.

```sh
# From the project root on the build host:
nix run nixpkgs#nixos-rebuild -- switch \
    --flake .#mugge-deploy \
    --target-host ela@<target-host> \
    --sudo
```

The `--sudo` flag runs activation commands via `sudo` on the
target. This works because user `ela` has passwordless sudo configured
in the NixOS config (`security.sudo.wheelNeedsPassword = false`). Root
SSH login is disabled for security (`PermitRootLogin = "no"`).

What nixos-rebuild does:
1. Evaluates the NixOS configuration on the build host
2. Builds all derivations (cross-compiled for aarch64-linux if building
   on x86_64, or natively if building on aarch64)
3. Copies the closure to the target via SSH
4. Activates the new system configuration on the target
5. Updates the bootloader (extlinux) to point at the new generation
6. Runs activation scripts (firmware update, tmpfiles, etc.)

**No reboot required** for most changes. The new configuration takes effect
immediately. Services are restarted as needed by NixOS's activation logic.

### When a reboot IS required

- Kernel changes (PREEMPT_RT version, kernel config)
- Boot firmware changes (config.txt, U-Boot)
- Changes to early-boot services

**SAFETY:** Warn the owner before rebooting. Amplifiers must be OFF.


## 4. Which Method to Use

| Scenario | Method | Command |
|----------|--------|---------|
| First install (non-NixOS Pi) | nixos-anywhere | `nix run github:nix-community/nixos-anywhere -- --flake .#mugge-deploy root@<ip>` |
| Incremental config/code change | nixos-rebuild | `nixos-rebuild switch --flake .#mugge-deploy --target-host ela@<ip> --use-remote-sudo` |
| Wipe and reinstall | nixos-anywhere | Same as first install |
| Kernel/firmware update | nixos-rebuild + reboot | `nixos-rebuild switch ...` then `ssh ela@<ip> sudo reboot` |

**Note:** `nixos-anywhere` requires root SSH on the **source** OS (before
NixOS is installed). After NixOS installation, root SSH is disabled —
all subsequent operations use `ela` with `--use-remote-sudo`.

**Always use `mugge-deploy`** (not `mugge`). The `mugge` configuration is
for building SD card images; `mugge-deploy` includes the disko partitioning
module needed for an installed system.


## 5. Build Host Options

### Building on the same architecture (aarch64)

If the build host is aarch64-linux (e.g., another Pi, an ARM cloud VM, or
the nix-builder), the build is native and straightforward.

### Cross-building from x86_64

If the build host is x86_64-linux, Nix will cross-compile for aarch64.
This requires either:

- **binfmt/QEMU:** `boot.binfmt.emulatedSystems = [ "aarch64-linux" ];`
  on the NixOS build host. Slower but works everywhere.
- **Remote builder:** Configure a remote aarch64-linux builder in
  `nix.buildMachines`. The build host offloads aarch64 builds to the
  remote machine.

The project's nix-builder (if available) handles this transparently.


## 6. Rollback

NixOS keeps previous generations. To roll back after a bad upgrade:

```sh
# On the Pi:
nixos-rebuild switch --rollback

# Or boot the previous generation via the bootloader menu
# (if using U-Boot with extlinux, select the previous entry)
```

To list available generations:

```sh
nix-env --list-generations --profile /nix/var/nix/profiles/system
```


## 7. Flake Input Updates

To update nixpkgs or other flake inputs (e.g., for PipeWire version bumps):

```sh
# Update all inputs
nix flake update

# Update only nixpkgs
nix flake update nixpkgs

# Then deploy
nixos-rebuild switch --flake .#mugge-deploy --target-host ela@<ip> --use-remote-sudo
```

After updating inputs, run the full test suite before deploying:

```sh
nix run .#test-all
```
