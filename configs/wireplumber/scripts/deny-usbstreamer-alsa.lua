-- deny-usbstreamer-alsa.lua — T-044-2: WirePlumber hardening
--
-- Prevents unauthorized PipeWire clients from creating nodes that target
-- the USBStreamer ALSA device. PipeWire's own static adapters (created via
-- pipewire.conf.d/20-usbstreamer.conf and 21-usbstreamer-playback.conf)
-- are whitelisted. Any other node attempting to open hw:USBStreamer is
-- destroyed immediately.
--
-- This is a defense-in-depth layer. The primary protection is:
--   1. WP ALSA monitor disabled for USBStreamer (50-usbstreamer-disable-acp.conf)
--   2. PipeWire holds exclusive ALSA access via static adapters
--
-- This script catches edge cases where a PW client (e.g., via pw-cli or
-- a misbehaving application) attempts to create a node targeting the
-- USBStreamer ALSA device directly.
--
-- Pi destination: ~/.config/wireplumber/scripts/deny-usbstreamer-alsa.lua
-- Loaded by:      53-deny-usbstreamer-alsa.conf

-- Whitelisted node names: PipeWire's own static adapters
local ALLOWED_NODES = {
  ["ada8200-in"] = true,   -- 20-usbstreamer.conf capture adapter
  ["alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0"] = true,  -- 21-usbstreamer-playback.conf
}

-- Pattern matching USBStreamer ALSA paths
local ALSA_PATH_PATTERN = "USBStreamer"

local om = ObjectManager {
  Interest {
    type = "node",
  },
}

om:connect("object-added", function (_, node)
  local props = node.properties
  if not props then return end

  -- Check if this node targets the USBStreamer ALSA device
  local alsa_path = props["api.alsa.path"] or ""
  local node_name = props["node.name"] or ""
  local object_path = props["object.path"] or ""

  -- Match USBStreamer by ALSA path or object path
  local targets_usbstreamer = false
  if string.find(alsa_path, ALSA_PATH_PATTERN) then
    targets_usbstreamer = true
  elseif string.find(object_path, ALSA_PATH_PATTERN) then
    targets_usbstreamer = true
  elseif string.find(node_name, "miniDSP_USBStreamer") then
    targets_usbstreamer = true
  end

  if not targets_usbstreamer then return end

  -- Allow whitelisted nodes (PipeWire's own static adapters)
  if ALLOWED_NODES[node_name] then return end

  -- Block: unauthorized node targeting USBStreamer
  Log.warning(om, "DENIED: unauthorized node '" .. node_name
    .. "' targeting USBStreamer (alsa.path=" .. alsa_path
    .. ", object.path=" .. object_path .. "). Destroying.")

  -- Request destruction of the unauthorized node
  node:request_destroy()
end)

om:activate()
