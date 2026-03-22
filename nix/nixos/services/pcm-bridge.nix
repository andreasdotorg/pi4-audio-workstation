# pcm-bridge.nix — NixOS systemd user service template for pcm-bridge instances
#
# Two instances: monitor (taps convolver input) and capture-usb (USBStreamer input).
# Each instance has its own configuration (mode, target, port, channels, etc.).
{ config, lib, pkgs, pi4audio-packages, ... }:

let
  cfg = config.services.pi4audio.pcm-bridge;

  instanceType = lib.types.submodule {
    options = {
      enable = lib.mkEnableOption "this pcm-bridge instance";

      mode = lib.mkOption {
        type = lib.types.enum [ "monitor" "capture" ];
        description = "PCM bridge operating mode.";
      };

      target = lib.mkOption {
        type = lib.types.str;
        description = "PipeWire node name to monitor or capture from.";
      };

      port = lib.mkOption {
        type = lib.types.port;
        description = "TCP port for PCM stream output.";
      };

      channels = lib.mkOption {
        type = lib.types.ints.positive;
        default = 4;
        description = "Number of audio channels.";
      };

      rate = lib.mkOption {
        type = lib.types.ints.positive;
        default = 48000;
        description = "Sample rate in Hz.";
      };

      quantum = lib.mkOption {
        type = lib.types.ints.positive;
        default = 256;
        description = "PipeWire quantum (buffer size in frames).";
      };

      levelsListen = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "TCP address for level metering (e.g. tcp:127.0.0.1:9100).";
      };

      extraArgs = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [];
        description = "Additional command-line arguments.";
      };
    };
  };
in
{
  options.services.pi4audio.pcm-bridge = {
    instances = lib.mkOption {
      type = lib.types.attrsOf instanceType;
      default = {};
      description = "Named pcm-bridge instances to run.";
    };
  };

  config = {
    systemd.user.services = lib.mapAttrs' (name: inst:
      lib.nameValuePair "pcm-bridge-${name}" (lib.mkIf inst.enable {
        description = "PCM Bridge audio stream: ${name}";
        after = [ "pipewire.service" ];
        wants = [ "pipewire.service" ];
        wantedBy = [ "default.target" ];

        serviceConfig = {
          Type = "simple";
          ExecStart = lib.concatStringsSep " " ([
            "${pi4audio-packages.pcm-bridge}/bin/pcm-bridge"
            "--mode" inst.mode
            "--target" inst.target
            "--listen" "tcp:127.0.0.1:${toString inst.port}"
            "--channels" (toString inst.channels)
            "--rate" (toString inst.rate)
            "--quantum" (toString inst.quantum)
          ] ++ lib.optionals (inst.levelsListen != null) [
            "--levels-listen" inst.levelsListen
          ] ++ inst.extraArgs);
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
      })
    ) cfg.instances;
  };
}
