# wireplumber.nix — WirePlumber config fragments for the Pi 4 Audio Workstation
#
# Deploys all WirePlumber configuration from configs/wireplumber/:
#   50  — Disable ACP for USBStreamer (static adapters handle it)
#   52  — Lower UMIK-1 priority (measurement mic, not a driver)
#   53  — Lua script: deny unauthorized USBStreamer ALSA access
#   90  — Disable automatic linking (GraphManager handles all links)
#
# D-040: 51-loopback-disable-acp.conf REMOVED — CamillaDSP abandoned,
# snd-aloop not loaded, no ALSA Loopback device to disable.
#
# Uses the NixOS WirePlumber module's configPackages + extraScripts
# options, which deploy files via XDG_DATA_DIRS where WirePlumber
# actually searches. The previous environment.etc approach placed files
# in /etc/wireplumber/ which is NOT in WirePlumber's NixOS search path.
{ config, lib, pkgs, ... }:

let
  # Build a config package from the raw .conf files in configs/wireplumber/.
  # configPackages expects packages with share/wireplumber/ trees.
  wpConfigPkg = pkgs.runCommand "pi4audio-wireplumber-config" { } ''
    mkdir -p $out/share/wireplumber/wireplumber.conf.d
    cp ${../../../configs/wireplumber/50-usbstreamer-disable-acp.conf} \
       $out/share/wireplumber/wireplumber.conf.d/50-usbstreamer-disable-acp.conf
    cp ${../../../configs/wireplumber/52-umik1-low-priority.conf} \
       $out/share/wireplumber/wireplumber.conf.d/52-umik1-low-priority.conf
    cp ${../../../configs/wireplumber/53-deny-usbstreamer-alsa.conf} \
       $out/share/wireplumber/wireplumber.conf.d/53-deny-usbstreamer-alsa.conf
    cp ${../../../configs/wireplumber/90-no-auto-link.conf} \
       $out/share/wireplumber/wireplumber.conf.d/90-no-auto-link.conf
  '';
in
{
  # WirePlumber is enabled automatically by services.pipewire on NixOS.
  # Config fragments via configPackages (XDG_DATA_DIRS).
  services.pipewire.wireplumber.configPackages = [ wpConfigPkg ];

  # Lua script referenced by 53-deny-usbstreamer-alsa.conf.
  # extraScripts deploys to share/wireplumber/scripts/ in XDG_DATA_DIRS.
  services.pipewire.wireplumber.extraScripts = {
    "deny-usbstreamer-alsa.lua" =
      builtins.readFile ../../../configs/wireplumber/scripts/deny-usbstreamer-alsa.lua;
  };
}
