# display.nix — Wayland display stack for the Pi 4 Audio Workstation
#
# labwc as Wayland compositor, auto-launched via greetd (no lightdm).
# wayvnc provides remote access with password authentication.
# Hardware V3D GL via vc4-kms-v3d (config.txt in sd-image.nix).
#
# D-022: PREEMPT_RT + hardware V3D GL confirmed working.
# No pixman override, no llvmpipe, no LIBGL_ALWAYS_SOFTWARE.
{ config, lib, pkgs, ... }:

{
  # ── GPU / Mesa drivers ─────────────────────────────────────────
  hardware.graphics = {
    enable = true;
    # V3D GL drivers for the Pi 4's VideoCore VI GPU.
    # vc4-kms-v3d dtoverlay is set in sd-image.nix config.txt.
  };

  # ── Disable lightdm ────────────────────────────────────────────
  # labwc runs as a user session via greetd auto-login, not via a
  # display manager.
  services.xserver.enable = false;

  # ── greetd: auto-login into labwc ──────────────────────────────
  # greetd is a minimal login daemon. We configure it to auto-login
  # user ela and launch labwc directly — no greeter UI needed for a
  # headless audio workstation accessed via VNC.
  #
  # Environment: XDG_SESSION_TYPE tells pam_systemd this is a graphical
  # session. LIBSEAT_BACKEND=logind forces libseat to use systemd-logind
  # for seat/device access instead of falling back to the built-in seatd
  # (which needs root for /dev/tty0).
  services.greetd = {
    enable = true;
    settings = {
      default_session = {
        command = "${pkgs.labwc}/bin/labwc";
        user = "ela";
      };
    };
  };

  # ── logind seat assignment ───────────────────────────────────────
  # greetd's systemd service needs TTYPath so that systemd-logind
  # associates the service (and its PAM sessions) with VT 1 → seat0.
  # Without this, libseat cannot get DRM device access from logind
  # and labwc fails with "Timeout waiting session to become active".
  systemd.services.greetd.serviceConfig = {
    TTYPath = "/dev/tty1";
    TTYReset = true;
    TTYVHangup = true;
    TTYVTDisallocate = true;
  };

  # Force libseat to use the logind backend and set session type.
  systemd.services.greetd.environment = {
    XDG_SESSION_TYPE = "wayland";
    LIBSEAT_BACKEND = "logind";
  };

  # ── wayvnc: remote desktop access ─────────────────────────────
  # Runs as a systemd user service under ela's session.
  # Password authentication is configured via wayvnc's config file
  # (~/.config/wayvnc/config) on the target — not managed by Nix
  # (contains credentials).
  systemd.user.services.wayvnc = {
    description = "wayvnc — VNC server for Wayland";
    after = [ "graphical-session.target" ];
    partOf = [ "graphical-session.target" ];
    wantedBy = [ "graphical-session.target" ];

    serviceConfig = {
      Type = "simple";
      ExecStart = "${pkgs.wayvnc}/bin/wayvnc 0.0.0.0 5900";
      Restart = "on-failure";
      RestartSec = 3;
    };
  };

  # ── Packages ───────────────────────────────────────────────────
  environment.systemPackages = with pkgs; [
    labwc
    wayvnc
    # wlr-randr is useful for display configuration over VNC
    wlr-randr
  ];
}
