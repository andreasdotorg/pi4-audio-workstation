# graph-manager.nix — NixOS systemd user service for pi4audio-graph-manager
#
# PipeWire graph manager: sole session manager for link topology.
# SCHED_FIFO/80 for watchdog safety mute deadline guarantee (T-044-4).
{ config, lib, pkgs, pi4audio-packages, ... }:

let
  cfg = config.services.pi4audio.graph-manager;
in
{
  options.services.pi4audio.graph-manager = {
    enable = lib.mkEnableOption "pi4audio graph manager service";

    mode = lib.mkOption {
      type = lib.types.enum [ "dj" "live" "monitoring" ];
      default = "dj";
      description = "Initial operating mode for the graph manager.";
    };

    logLevel = lib.mkOption {
      type = lib.types.enum [ "error" "warn" "info" "debug" "trace" ];
      default = "info";
      description = "Log verbosity level.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.user.services.pi4audio-graph-manager = {
      description = "PipeWire Graph Manager — sole session manager for link topology";
      after = [ "pipewire.service" "wireplumber.service" ];
      requires = [ "pipewire.service" ];
      wants = [ "wireplumber.service" ];
      wantedBy = [ "default.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = "${pi4audio-packages.graph-manager}/bin/pi4audio-graph-manager --mode ${cfg.mode} --log-level ${cfg.logLevel}";
        Restart = "on-failure";
        RestartSec = 3;

        # RT scheduling: FIFO/80 for watchdog safety mute (T-044-4).
        # Below PipeWire (FIFO/88) but above all non-audio processes.
        CPUSchedulingPolicy = "fifo";
        CPUSchedulingPriority = 80;

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
