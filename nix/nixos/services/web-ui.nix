# web-ui.nix — NixOS systemd user service for pi4-audio-webui
#
# FastAPI/uvicorn monitoring web UI (D-020).
# Type=simple (NOT notify — uvicorn does not call sd_notify; F-059 lesson).
{ config, lib, pkgs, ... }:

let
  cfg = config.services.pi4audio.web-ui;
  pcmCfg = config.services.pi4audio.pcm-bridge;

  # Auto-generate PI4AUDIO_PCM_SOURCES JSON from pcm-bridge instances.
  # Maps each enabled instance name to its tcp:host:port address.
  pcmSourcesJson = builtins.toJSON (
    lib.mapAttrs (_name: inst: "tcp:127.0.0.1:${toString inst.port}")
      (lib.filterAttrs (_name: inst: inst.enable) pcmCfg.instances)
  );

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
    # US-110: Passkey auth dependencies
    ps.webauthn    # py-webauthn (WebAuthn registration/authentication)
    ps.aiosqlite   # async SQLite for credential + session storage
    ps.qrcode      # QR code generation for invite links
  ]);

  # Web UI source bundle: web-ui + room-correction + measurement as siblings.
  # The web-ui code resolves room-correction via ../../room-correction relative
  # to app/__file__, and measurement via PI4AUDIO_MEAS_DIR or relative path.
  # This derivation reproduces that layout in the Nix store.
  webUiSrc = pkgs.runCommand "pi4audio-web-ui-src" { } ''
    mkdir -p $out/web-ui $out/room-correction $out/measurement
    cp -r ${../../../src/web-ui/app} $out/web-ui/app
    cp -r ${../../../src/web-ui/static} $out/web-ui/static
    cp -r ${../../../src/room-correction}/* $out/room-correction/
    cp -r ${../../../src/measurement}/* $out/measurement/
  '';
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
      default = "${webUiSrc}/web-ui";
      description = "Path to the web-ui source directory (containing app/).";
    };

    environment = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = {};
      description = "Additional environment variables for the web UI process.";
    };
  };

  config = lib.mkIf cfg.enable {
    # Generate self-signed TLS certs if configured paths don't exist yet.
    # Runs as a system-level oneshot (needs to write to /var/lib/pi4audio/certs).
    systemd.services.pi4audio-generate-certs = lib.mkIf (cfg.sslKeyFile != null && cfg.sslCertFile != null) {
      description = "Generate self-signed TLS certs for pi4audio web UI";
      wantedBy = [ "multi-user.target" ];
      before = [ "multi-user.target" ];
      unitConfig.ConditionPathExists = "!${toString cfg.sslCertFile}";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = let
          keyFile = toString cfg.sslKeyFile;
          certFile = toString cfg.sslCertFile;
        in "${pkgs.openssl}/bin/openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -keyout ${keyFile} -out ${certFile} -days 3650 -nodes -subj /CN=mugge";
        ExecStartPost = "${pkgs.coreutils}/bin/chmod 0600 ${toString cfg.sslKeyFile} ${toString cfg.sslCertFile}";
        User = "ela";
        Group = "users";
      };
    };

    systemd.user.services.pi4-audio-webui = {
      description = "Pi4 Audio Workstation monitoring web UI (D-020)";
      after = [ "pipewire.service" ];
      wants = [ "pipewire.service" ];
      wantedBy = [ "default.target" ];

      environment = {
        PI_AUDIO_MOCK = "0";
        PI4AUDIO_SIGGEN = "1";
        JACK_NO_START_SERVER = "1";
        PI4AUDIO_RC_DIR = "${webUiSrc}/room-correction";
        PI4AUDIO_MEAS_DIR = "${webUiSrc}/measurement";
        PI4AUDIO_PCM_SOURCES = pcmSourcesJson;
        PI4AUDIO_PCM_CHANNELS = "8";
      } // cfg.environment;

      serviceConfig = {
        Type = "simple";
        # pw-dump, pw-cli, pw-metadata called by pw_helpers.py + config_routes.py
        Environment = "PATH=${pkgs.pipewire}/bin:${pkgs.coreutils}/bin";
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

        # F-064: Nice=0 (not 10) — single-worker uvicorn needs full CPU
        # access to avoid event loop starvation under WebSocket load.
        Nice = 0;
      };
    };
  };
}
