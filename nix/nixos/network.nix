{ config, lib, pkgs, ... }:
{
  networking = {
    hostName = "mugge";

    # nftables firewall (matches US-000a hardening)
    nftables.enable = true;
    firewall = {
      enable = true;
      allowedTCPPorts = [ 22 5900 8080 ];  # SSH, wayvnc, web-ui
      allowedUDPPorts = [ 5353 ];           # mDNS
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
