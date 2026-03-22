{ config, lib, pkgs, ... }:
{
  users.users.ela = {
    isNormalUser = true;
    extraGroups = [ "wheel" "audio" "video" "input" ];
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGm69fnMG3I2s+B9GYageyu5pHlbZiwcngpeJ9ab9Qyl gabriela.bogk@MacBook-Pro-von-Gabriela.local"
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPx5Fo55tKXlVZRMCgCFtqhZBzL42KWOHDzoMvlUvwJ7 ela@desktop"
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIC6Q5zICdH3gX1pNeXM9izHdKSW/DZ38yWyI9YCHf7mF ela@andreas.org"
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIME7e3DphYSPD6IG5WxZv1yYlTtr7wP2EHcZQVnd85Cj ela@nix-builder"
    ];
  };

  security.sudo.wheelNeedsPassword = false;
}
