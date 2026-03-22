# web-ui.nix — NixOS systemd user service for pi4-audio-webui
#
# FastAPI/uvicorn monitoring web UI (D-020).
# Type=simple (NOT notify — uvicorn does not call sd_notify; F-059 lesson).
{ config, lib, pkgs, ... }:

let
  cfg = config.services.pi4audio.web-ui;

  # Python environment with all web-ui runtime dependencies.
  # This mirrors the testPython from flake.nix but for production use.
  python = pkgs.python313;
  webUiPython = python.withPackages (ps: [
    ps.fastapi
    ps.uvicorn
    ps.scipy
    ps.numpy
    ps.soundfile
    ps.websockets
    ps.pyyaml
    ps.httpx
  ]);
in
{
  options.services.pi4audio.web-ui = {
    enable = lib.mkEnableOption "pi4audio web UI service";

    host = lib.mkOption {
      type = lib.types.str;
      default = "0.0.0.0";
      description = "Listen address for the web UI.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "Listen port for the web UI.";
    };

    sslKeyFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "Path to TLS private key (PEM). Omit for plain HTTP.";
    };

    sslCertFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "Path to TLS certificate (PEM). Omit for plain HTTP.";
    };

    webUiPath = lib.mkOption {
      type = lib.types.path;
      description = "Path to the web-ui source directory (containing app/).";
    };

    environment = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = {};
      description = "Additional environment variables for the web UI process.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.user.services.pi4-audio-webui = {
      description = "Pi4 Audio Workstation monitoring web UI (D-020)";
      after = [ "pipewire.service" ];
      wants = [ "pipewire.service" ];
      wantedBy = [ "default.target" ];

      environment = {
        PI_AUDIO_MOCK = "0";
        PI4AUDIO_SIGGEN = "1";
        JACK_NO_START_SERVER = "1";
      } // cfg.environment;

      serviceConfig = {
        Type = "simple";
        WorkingDirectory = toString cfg.webUiPath;
        ExecStart = lib.concatStringsSep " " ([
          "${webUiPython}/bin/uvicorn"
          "app.main:app"
          "--host" cfg.host
          "--port" (toString cfg.port)
          "--workers" "1"
        ] ++ lib.optionals (cfg.sslKeyFile != null && cfg.sslCertFile != null) [
          "--ssl-keyfile" (toString cfg.sslKeyFile)
          "--ssl-certfile" (toString cfg.sslCertFile)
        ]);
        Restart = "on-failure";
        RestartSec = 2;

        # Web UI must not compete with RT audio
        Nice = 10;
      };
    };
  };
}
