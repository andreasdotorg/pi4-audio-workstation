# level-bridge.nix — NixOS systemd user service template for level-bridge instances
#
# Always-on PipeWire level metering for the web UI (D-049).
# Three production instances:
#   sw     — capture mode, taps app output (Mixxx/Reaper/signal-gen), 8ch, port 9100
#   hw-out — monitor mode, taps USBStreamer sink monitor ports (DAC output), 8ch, port 9101
#   hw-in  — capture mode, reads USBStreamer source (ADC input), 8ch, port 9102
#
# Each instance publishes per-channel peak/RMS JSON at ~30 Hz over TCP.
# The web-ui (sole consumer) connects from localhost — all instances bind
# to 127.0.0.1 by default (SEC: no external exposure of raw metering data).
{ config, lib, pkgs, pi4audio-packages, ... }:

let
  cfg = config.services.pi4audio.level-bridge;

  instanceType = lib.types.submodule {
    options = {
      enable = lib.mkEnableOption "this level-bridge instance";

      mode = lib.mkOption {
        type = lib.types.enum [ "monitor" "capture" ];
        description = ''
          Operating mode. "monitor" taps a sink node's monitor ports (passive,
          no xruns). "capture" reads from a source/capture node directly.
        '';
      };

      target = lib.mkOption {
        type = lib.types.str;
        description = ''
          PipeWire node name. In monitor mode, the sink node to tap.
          In capture mode, the source node to read from.
        '';
      };

      nodeName = lib.mkOption {
        type = lib.types.str;
        description = ''
          Unique PipeWire node name for this instance. GM routes by node name —
          a wrong value causes silent routing failure. Required, no default.
          Production values: pi4audio-level-bridge-sw, pi4audio-level-bridge-hw-out,
          pi4audio-level-bridge-hw-in.
        '';
      };

      levelsListen = lib.mkOption {
        type = lib.types.str;
        description = "TCP address for level metering output (e.g. tcp:127.0.0.1:9100).";
      };

      channels = lib.mkOption {
        type = lib.types.ints.positive;
        default = 8;
        description = "Number of audio channels to capture.";
      };

      rate = lib.mkOption {
        type = lib.types.ints.positive;
        default = 48000;
        description = "Sample rate in Hz.";
      };

      managed = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = ''
          Run under GraphManager supervision (D-043). GM creates links and
          owns the routing table. When false, uses self-link or manual pw-link.
        '';
      };

      selfLink = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = ''
          Enable self-linking via PipeWire stream properties. Sets
          stream.capture.sink + target.object for WirePlumber auto-linking.
          Mutually exclusive with managed mode in practice.
        '';
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
  options.services.pi4audio.level-bridge = {
    instances = lib.mkOption {
      type = lib.types.attrsOf instanceType;
      default = {};
      description = "Named level-bridge instances to run.";
    };
  };

  config = {
    systemd.user.services = lib.mapAttrs' (name: inst:
      lib.nameValuePair "level-bridge-${name}" (lib.mkIf inst.enable {
        description = "Level Bridge metering: ${name} (D-049)";
        after = [ "pipewire.service" ];
        wants = [ "pipewire.service" ]
          ++ lib.optionals inst.managed [ "pi4audio-graph-manager.service" ];
        wantedBy = [ "default.target" ];

        serviceConfig = {
          Type = "simple";
          ExecStart = lib.concatStringsSep " " ([
            "${pi4audio-packages.level-bridge}/bin/level-bridge"
            "--mode" inst.mode
            "--target" inst.target
            "--levels-listen" inst.levelsListen
            "--channels" (toString inst.channels)
            "--rate" (toString inst.rate)
            "--node-name" inst.nodeName
          ] ++ lib.optionals inst.managed [
            "--managed"
          ] ++ lib.optionals inst.selfLink [
            "--self-link"
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
