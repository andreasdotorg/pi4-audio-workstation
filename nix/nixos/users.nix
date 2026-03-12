{ config, lib, pkgs, ... }:
{
  users.users.ela = {
    isNormalUser = true;
    extraGroups = [ "wheel" "audio" "video" "input" ];
    openssh.authorizedKeys.keys = [
      # FIXME: replace with actual SSH public key from Pi (~ela/.ssh/authorized_keys)
      "ssh-ed25519 AAAA... gabriela@mac"
    ];
  };

  security.sudo.wheelNeedsPassword = false;
}
