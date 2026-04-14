{ config, lib, pkgs, ... }:
{
  networking = {
    hostName = "mugge";

    # Static route to VM subnet via gateway host
    interfaces.end0.ipv4.routes = [{
      address = "192.168.105.0";
      prefixLength = 24;
      via = "192.168.178.26";
    }];

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
