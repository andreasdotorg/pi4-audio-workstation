# repart-image.nix — MBR SD card image builder for the Raspberry Pi 4 Audio Workstation
#
# Produces a compressed, flashable .raw.zst via:
#   nix build .#images.sd-card
#
# MBR partition layout (matches the proven old sd-image.nix approach):
#   Partition 1: 256 MiB FAT32 (type 0x0C) — firmware, U-Boot, config.txt
#   Partition 2: rest ext4 (type 0x83, bootable) — NixOS root filesystem
#
# F-273: Uses MBR instead of GPT. systemd-repart only supports GPT, so
# this uses sfdisk + mkfs directly. MBR is what the old sd-image.nix used
# and is proven to boot reliably on Pi 4. The VideoCore firmware has no
# issues finding FAT partitions on MBR (scans by type 0x0B/0x0C).
#
# The image uses U-Boot as the second-stage bootloader so that NixOS's
# extlinux-based generation switching works out of the box.
#
# Firmware files come from firmware.nix (single source of truth).
{ config, lib, pkgs, modulesPath, ... }:

let
  # Root filesystem image: ext4 with the NixOS closure.
  # Uses the same make-ext4-fs.nix that the upstream sd-image module uses.
  rootfsImage = pkgs.callPackage "${modulesPath}/../lib/make-ext4-fs.nix" {
    storePaths = [ config.system.build.toplevel ];
    compressImage = true;
    volumeLabel = "NIXOS_SD";
    populateImageCommands = ''
      mkdir -p ./files/boot
      ${config.boot.loader.generic-extlinux-compatible.populateCmd} \
        -c ${config.system.build.toplevel} -d ./files/boot
    '';
  };

  firmwareSize = 256; # MiB
  # Gap before first partition (for MBR + alignment)
  gap = 8; # MiB

  fw = config.pi4audio.firmwareFiles;

  sdImage = pkgs.stdenv.mkDerivation {
    name = "pi4audio.raw";

    nativeBuildInputs = with pkgs; [
      dosfstools
      e2fsprogs
      libfaketime
      mtools
      util-linux
      zstd
    ];

    buildCommand = ''
      mkdir -p $out/sd-image

      # Decompress root filesystem
      root_fs=./root-fs.img
      echo "Decompressing rootfs image"
      zstd -d --no-progress "${rootfsImage}" -o $root_fs
      chmod u+w $root_fs

      # Disable orphan_file INCOMPAT feature. U-Boot 2025.10 ext4 driver
      # doesn't support orphan_file (0x20000), enabled by default in
      # e2fsprogs >= 1.47.3. Without this, U-Boot can't read the root
      # partition to find extlinux.conf. Safe to disable — falls back to
      # linked-list orphan tracking with negligible performance difference.
      tune2fs -O ^orphan_file $root_fs

      # Calculate image size
      rootSizeBlocks=$(du -B 512 --apparent-size $root_fs | awk '{ print $1 }')
      firmwareSizeBlocks=$((${toString firmwareSize} * 1024 * 1024 / 512))
      imageSize=$((rootSizeBlocks * 512 + firmwareSizeBlocks * 512 + ${toString gap} * 1024 * 1024))
      truncate -s $imageSize $out/sd-image/pi4audio.raw

      img=$out/sd-image/pi4audio.raw

      # Create MBR partition table.
      # type=c is W95 FAT32 (LBA) — what the old sd-image.nix used.
      # type=83 is Linux. The "bootable" flag on partition 2 tells
      # U-Boot where to look for extlinux.conf.
      sfdisk --no-reread --no-tell-kernel $img <<EOF
          label: dos

          start=${toString gap}M, size=$firmwareSizeBlocks, type=c
          start=$((${toString gap} + ${toString firmwareSize}))M, type=83, bootable
      EOF

      # Copy root filesystem into partition 2
      eval $(partx $img -o START,SECTORS --nr 2 --pairs)
      dd conv=notrunc if=$root_fs of=$img seek=$START count=$SECTORS

      # Create FAT32 firmware partition
      eval $(partx $img -o START,SECTORS --nr 1 --pairs)
      truncate -s $((SECTORS * 512)) firmware_part.img
      mkfs.vfat --invariant -n FIRMWARE firmware_part.img

      # Populate firmware files
      mkdir firmware
      cp ${fw}/bootcode.bin firmware/
      cp ${fw}/config.txt firmware/
      cp ${fw}/u-boot-rpi4.bin firmware/
      cp ${fw}/armstub8-gic.bin firmware/
      cp ${fw}/bcm2711-rpi-4-b.dtb firmware/
      cp ${fw}/fixup*.dat firmware/
      cp ${fw}/start*.elf firmware/
      # DT overlays
      mkdir -p firmware/overlays
      cp ${fw}/overlays/*.dtbo firmware/overlays/

      find firmware -exec touch --date=2000-01-01 {} +
      cd firmware
      for d in $(find . -type d -mindepth 1 | sort); do
        faketime "2000-01-01 00:00:00" mmd -i ../firmware_part.img "::/$d"
      done
      for f in $(find . -type f | sort); do
        mcopy -pvm -i ../firmware_part.img "$f" "::/$f"
      done
      cd ..

      # Verify and copy firmware partition
      fsck.vfat -vn firmware_part.img
      dd conv=notrunc if=firmware_part.img of=$img seek=$START count=$SECTORS

      # Compress
      zstd -T$NIX_BUILD_CORES --rm $img
    '';
  };
in
{
  # Expose the image as system.build.image (same attribute as repart used).
  system.build.image = sdImage;

  # First-boot: expand root partition to fill the SD card and register
  # the Nix store. Ported from sd-image.nix's boot.postBootCommands.
  # The /nix-path-registration file is placed in the root image above
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
