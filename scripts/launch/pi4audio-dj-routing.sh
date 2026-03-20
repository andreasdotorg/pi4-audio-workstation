#!/usr/bin/env bash
# pi4audio-dj-routing.sh — Create DJ mode PipeWire links.
#
# Waits for the convolver, USBStreamer, and Mixxx nodes to appear,
# then creates all 12 DJ mode links per the routing table (routing.rs).
#
# Idempotent: pw-link silently succeeds if a link already exists.
#
# Pi destination: /home/ela/bin/pi4audio-dj-routing (chmod +x)
set -euo pipefail

# --- Node name patterns ---
CONVOLVER_IN="pi4audio-convolver"
CONVOLVER_OUT="pi4audio-convolver-out"
USBSTREAMER_PREFIX="alsa_output.usb-MiniDSP_USBStreamer"
MIXXX_PREFIX="Mixxx"

MAX_WAIT=90   # seconds (Mixxx needs ~40s to register JACK ports on Pi4)

# --- helpers ---

wait_for_port() {
    local direction="$1"  # -o (output) or -i (input)
    local pattern="$2"
    local elapsed=0
    while ! pw-link "$direction" 2>/dev/null | grep -qF "$pattern"; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [ "$elapsed" -ge "$MAX_WAIT" ]; then
            echo "TIMEOUT: port matching '$pattern' not found after ${MAX_WAIT}s" >&2
            exit 1
        fi
    done
}

# Resolve a node name prefix to the first matching output port's node:port
# prefix (needed because USBStreamer has a variable suffix).
resolve_node() {
    local direction="$1"
    local prefix="$2"
    pw-link "$direction" 2>/dev/null | grep -F "$prefix" | head -1 | cut -d: -f1
}

link() {
    local src="$1"
    local dst="$2"
    pw-link "$src" "$dst" 2>/dev/null || true
}

# Disconnect all direct links from a Mixxx output port to USBStreamer input ports.
# Mixxx auto-connect creates bypass links (Mixxx → USBStreamer) that skip the
# convolver.  This function removes them.  pw-link -d silently succeeds if the
# link doesn't exist.
disconnect_mixxx_bypass() {
    local mixxx="$1"
    local usb="$2"
    # Try all plausible auto-connect pairings.
    # Mixxx exposes 6 JACK outputs (out_0..out_5: master, headphones, booth).
    for out in 0 1 2 3 4 5 6 7; do
        for ch in 0 1 2 3 4 5 6 7; do
            pw-link -d "${mixxx}:out_${out}" "${usb}:playback_AUX${ch}" 2>/dev/null || true
        done
    done
}

# --- Phase 1: wait for infrastructure nodes ---

echo "Waiting for convolver and USBStreamer..."
wait_for_port -o "$CONVOLVER_OUT"
wait_for_port -i "$USBSTREAMER_PREFIX"

USB_NODE=$(resolve_node -i "$USBSTREAMER_PREFIX")
echo "USBStreamer node: $USB_NODE"

# Phase 1 links: convolver-out → USBStreamer (ch 1-4, shared across all modes)
for ch in 0 1 2 3; do
    link "${CONVOLVER_OUT}:output_AUX${ch}" "${USB_NODE}:playback_AUX${ch}"
done
echo "Convolver → USBStreamer: 4 links created"

# --- Phase 2: wait for Mixxx ---

echo "Waiting for Mixxx..."
wait_for_port -o "$MIXXX_PREFIX"

MIXXX_NODE=$(resolve_node -o "$MIXXX_PREFIX")
echo "Mixxx node: $MIXXX_NODE"

# --- Phase 2a: remove any auto-connected Mixxx links (D-001) ---
# Mixxx (or WirePlumber) may auto-connect Mixxx outputs directly to the
# USBStreamer, bypassing the convolver.  Remove all such links before
# creating the correct topology.
disconnect_mixxx_bypass "$MIXXX_NODE" "$USB_NODE"
echo "Cleaned up any auto-connected Mixxx → USBStreamer bypass links"

# Mixxx master → convolver mains (1:1)
# Ch 1 (Master L) → convolver ch 1 (left wideband)
# Ch 2 (Master R) → convolver ch 2 (right wideband)
link "${MIXXX_NODE}:out_0" "${CONVOLVER_IN}:playback_AUX0"
link "${MIXXX_NODE}:out_1" "${CONVOLVER_IN}:playback_AUX1"
echo "Mixxx master → convolver mains: 2 links"

# Mixxx master → convolver subs (L+R mono sum per TK-239)
# Both Master L and Master R feed each sub input.
# PipeWire sums the two links at the input port.
for sub_aux in 2 3; do
    link "${MIXXX_NODE}:out_0" "${CONVOLVER_IN}:playback_AUX${sub_aux}"
    link "${MIXXX_NODE}:out_1" "${CONVOLVER_IN}:playback_AUX${sub_aux}"
done
echo "Mixxx master → convolver subs: 4 links (mono fan-out)"

# Mixxx headphones → USBStreamer direct (bypass convolver)
# Ch 3 (Headphone L) → USBStreamer ch 5
# Ch 4 (Headphone R) → USBStreamer ch 6
link "${MIXXX_NODE}:out_2" "${USB_NODE}:playback_AUX4"
link "${MIXXX_NODE}:out_3" "${USB_NODE}:playback_AUX5"
echo "Mixxx headphones → USBStreamer: 2 links"

echo "DJ routing complete: 12 links active"
