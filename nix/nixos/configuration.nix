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
