{ config, lib, pkgs, ... }:
{
  networking = {
    hostName = "mugge";

    # nftables firewall (matches US-000a hardening)
    nftables.enable = true;
    firewall = {
      enable = true;
      allowedTCPPorts = [ 22 ];      # SSH only for Phase 1
      allowedUDPPorts = [ 5353 ];    # mDNS
      # VNC (5900) added in Phase 3 (display.nix)
      # Web UI (8080) added in Phase 4 (applications.nix)
    };
  };

  # SSH hardening — key-only, no root login
  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "no";
    };
  };

  # mDNS via avahi — hostname resolution on local network
  services.avahi = {
    enable = true;
    nssmdns4 = true;
    publish = {
      enable = true;
      addresses = true;
    };
  };
}
