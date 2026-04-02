# signal-gen.nix — NixOS systemd user service for pi4audio-signal-gen
#
# RT signal generator for measurement and test tooling (D-037, D-040).
# Runs in managed mode — GM controls link topology.
{ config, lib, pkgs, pi4audio-packages, ... }:

let
  cfg = config.services.pi4audio.signal-gen;
in
{
  options.services.pi4audio.signal-gen = {
    enable = lib.mkEnableOption "pi4audio signal generator service";

    captureTarget = lib.mkOption {
      type = lib.types.str;
      default = "UMIK-1";
      description = "Device name pattern for hot-plug monitoring (maps to --device-watch).";
    };

    channels = lib.mkOption {
      type = lib.types.ints.positive;
      default = 8;
      description = "Number of output channels.";
    };

    listenAddress = lib.mkOption {
      type = lib.types.str;
      default = "tcp:127.0.0.1:4001";
      description = "RPC listen address.";
    };

    maxLevelDbfs = lib.mkOption {
      type = lib.types.str;
      default = "-20.0";
      description = "Maximum output level in dBFS (safety limit).";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.user.services.pi4audio-signal-gen = {
      description = "RT Signal Generator for Pi Audio Workstation (D-037, D-040)";
      after = [ "pipewire.service" "wireplumber.service" "pi4audio-graph-manager.service" ];
      requires = [ "pipewire.service" ];
      wants = [ "wireplumber.service" "pi4audio-graph-manager.service" ];
      wantedBy = [ "default.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = lib.concatStringsSep " " [
          "${pi4audio-packages.signal-gen}/bin/pi4audio-signal-gen"
          "--managed"
          "--device-watch" cfg.captureTarget
          "--channels" (toString cfg.channels)
          "--listen" cfg.listenAddress
          "--max-level-dbfs=${cfg.maxLevelDbfs}"
        ];
        Restart = "on-failure";
        RestartSec = 2;

        OOMScoreAdjust = -500;
        LimitMEMLOCK = "infinity";
        LimitRTPRIO = 88;

        # Security hardening — PipeWire client profile (SEC-PW-CLIENT / F-035)
        NoNewPrivileges = true;
        PrivateTmp = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        CapabilityBoundingSet = "";
        RestrictSUIDSGID = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [ "@system-service" "~@privileged" ];
        ProtectSystem = "full";
        ProtectHome = "read-only";
      };
    };
  };
}
