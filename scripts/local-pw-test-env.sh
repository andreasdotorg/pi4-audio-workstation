#!/bin/bash
# Local PipeWire test environment — mirrors production audio topology.
# Starts PipeWire (NO WirePlumber) with a null audio sink that replicates
# the Pi's production USBStreamer node name, port layout, and channel
# assignment so GraphManager can reconcile the local graph identically
# to production. GM is the sole link manager (D-039) — no session manager.
#
# Usage:
#   ./scripts/local-pw-test-env.sh start   # Start PipeWire daemon
#   ./scripts/local-pw-test-env.sh stop    # Stop PipeWire
#   ./scripts/local-pw-test-env.sh status  # Show current state
#   ./scripts/local-pw-test-env.sh env     # Print env vars for sourcing
#
# Requires: nix (PipeWire fetched from nixpkgs)
#
# Architecture:
#   PipeWire daemon (custom config, no dbus, no ALSA, no WirePlumber) with:
#   - alsa_output.usb-MiniDSP_USBStreamer: 8ch null Audio/Sink (graph driver)
#   - Filter-chain convolver: injected by local-demo.sh (separate drop-in)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Runtime paths
PW_RUNTIME_DIR="/tmp/pw-runtime-$(id -u)"
XDG_CONFIG_DIR="/tmp/pw-test-xdg-config"
PW_PIDFILE="/tmp/pw-test-pipewire.pid"

# Resolve nix store paths (cached after first run)
resolve_nix_paths() {
    if [ -z "${PW_STORE:-}" ]; then
        PW_STORE=$(nix eval --raw nixpkgs#pipewire.outPath 2>/dev/null) || {
            echo "ERROR: Cannot resolve pipewire from nixpkgs. Is nix available?" >&2
            exit 1
        }
    fi

    # Ensure package is in the store
    if [ ! -d "$PW_STORE/bin" ]; then
        echo "Fetching pipewire..."
        nix build --no-link nixpkgs#pipewire 2>&1
    fi
}

# Set environment variables for PipeWire
setup_env() {
    resolve_nix_paths
    export XDG_RUNTIME_DIR="$PW_RUNTIME_DIR"
    export SPA_PLUGIN_DIR="$PW_STORE/lib/spa-0.2"
    export PIPEWIRE_MODULE_DIR="$PW_STORE/lib/pipewire-0.3"
    export XDG_CONFIG_HOME="$XDG_CONFIG_DIR"
    export XDG_DATA_DIRS="$PW_STORE/share:${XDG_DATA_DIRS:-/usr/share}"
    # Don't override PIPEWIRE_CONFIG_DIR -- use PW defaults from nix store
    unset PIPEWIRE_CONFIG_DIR 2>/dev/null || true
}

# Create config files
create_configs() {
    mkdir -p "$PW_RUNTIME_DIR"
    mkdir -p "$XDG_CONFIG_DIR/pipewire/pipewire.conf.d"
    mkdir -p "$XDG_CONFIG_DIR/pipewire/client.conf.d"

    # PipeWire: disable dbus, create production-matching USBStreamer node.
    # Node name and port layout match the Pi's production topology so
    # GraphManager's routing table resolves all endpoints correctly.
    # No WirePlumber — GM is the sole link manager (D-039).
    cat > "$XDG_CONFIG_DIR/pipewire/pipewire.conf.d/00-headless-test.conf" << 'EOF'
# Headless test environment — production topology with null audio nodes.
# Node names match GraphManager's compiled routing table (routing.rs).
# No WirePlumber — GM manages all links (D-039).
context.properties = {
    support.dbus = false
}

context.objects = [
    # USBStreamer replacement: 8ch null Audio/Sink, graph clock driver.
    # Production: alsa_output.usb-MiniDSP_USBStreamer-00.pro-output-0
    # GM uses Prefix("alsa_output.usb-MiniDSP_USBStreamer") match.
    # Ports: playback_AUX0..AUX7 (ch 1-4 speakers, 5-6 HP, 7-8 IEM).
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "alsa_output.usb-MiniDSP_USBStreamer"
            media.class      = Audio/Sink
            object.linger    = true
            node.driver      = true
            audio.channels   = 8
            audio.rate       = 48000
            audio.position   = [ AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 ]
            node.autoconnect = false
            session.suspend-timeout-seconds = 0
            node.pause-on-idle = false
        }
    }
]

# NOTE: The filter-chain convolver config is injected by local-demo.sh
# as a separate drop-in file (convolver.conf). It uses the real PipeWire
# convolver with dirac (passthrough) coefficients, mirroring the
# production filter-chain structure exactly.
EOF

    # Client tools: disable dbus
    cat > "$XDG_CONFIG_DIR/pipewire/client.conf.d/00-headless-test.conf" << 'EOF'
context.properties = {
    support.dbus = false
}
EOF
}

# Start PipeWire (no WirePlumber — GM is the sole link manager)
cmd_start() {
    # Check if already running
    if [ -f "$PW_PIDFILE" ] && kill -0 "$(cat "$PW_PIDFILE")" 2>/dev/null; then
        echo "PipeWire already running (PID $(cat "$PW_PIDFILE"))"
        return 0
    fi

    setup_env
    create_configs

    # Clean stale sockets
    rm -f "$PW_RUNTIME_DIR/pipewire"*

    echo "Starting PipeWire daemon..."
    "$PW_STORE/bin/pipewire" 2>/tmp/pw-test-stderr.log &
    local pw_pid=$!
    echo "$pw_pid" > "$PW_PIDFILE"
    sleep 2

    if ! kill -0 "$pw_pid" 2>/dev/null; then
        echo "ERROR: PipeWire failed to start. Logs:" >&2
        cat /tmp/pw-test-stderr.log >&2
        return 1
    fi
    echo "  PipeWire running (PID $pw_pid)"

    echo ""
    echo "Local PipeWire test environment ready (no WirePlumber — GM manages links)."
    echo ""
    echo "To use pw-cli/pw-dump/pw-link, source the env vars:"
    echo "  eval \"\$($(realpath "${BASH_SOURCE[0]}") env)\""
    echo ""
    cmd_status
}

# Stop all processes
cmd_stop() {
    local stopped=0
    if [ -f "$PW_PIDFILE" ]; then
        local pw_pid
        pw_pid=$(cat "$PW_PIDFILE")
        if kill -0 "$pw_pid" 2>/dev/null; then
            kill "$pw_pid" 2>/dev/null
            echo "Stopped PipeWire (PID $pw_pid)"
            stopped=1
        fi
        rm -f "$PW_PIDFILE"
    fi
    # Also kill any stray processes
    pkill -u "$(id -u)" -x pipewire 2>/dev/null || true
    rm -f "$PW_RUNTIME_DIR/pipewire"*

    if [ "$stopped" -eq 0 ]; then
        echo "No running PipeWire test environment found."
    fi
}

# Show status
cmd_status() {
    setup_env

    local pw_alive=false
    if [ -f "$PW_PIDFILE" ] && kill -0 "$(cat "$PW_PIDFILE")" 2>/dev/null; then
        pw_alive=true
    fi

    echo "PipeWire:    $(if $pw_alive; then echo "running (PID $(cat "$PW_PIDFILE"))"; else echo "stopped"; fi)"

    if $pw_alive; then
        echo ""
        echo "Nodes:"
        timeout 3 "$PW_STORE/bin/pw-dump" 2>/dev/null | grep '"node.name"' | sed 's/.*"node.name": "\(.*\)".*/  - \1/' || true
        echo ""
        echo "Ports:"
        timeout 3 "$PW_STORE/bin/pw-link" -o 2>&1 | sed 's/^/  [out] /' || true
        timeout 3 "$PW_STORE/bin/pw-link" -i 2>&1 | sed 's/^/  [in]  /' || true
        echo ""
        echo "Links:"
        timeout 3 "$PW_STORE/bin/pw-link" -l 2>&1 | grep '|' | sed 's/^/  /' || true
        if ! timeout 3 "$PW_STORE/bin/pw-link" -l 2>&1 | grep -q '|'; then
            echo "  (none)"
        fi
    fi
}

# Print environment variables for sourcing
cmd_env() {
    resolve_nix_paths
    cat << ENVEOF
export XDG_RUNTIME_DIR="$PW_RUNTIME_DIR"
export SPA_PLUGIN_DIR="$PW_STORE/lib/spa-0.2"
export PIPEWIRE_MODULE_DIR="$PW_STORE/lib/pipewire-0.3"
export XDG_CONFIG_HOME="$XDG_CONFIG_DIR"
export XDG_DATA_DIRS="$PW_STORE/share:\${XDG_DATA_DIRS:-/usr/share}"
unset PIPEWIRE_CONFIG_DIR 2>/dev/null || true
export PATH="$PW_STORE/bin:\$PATH"
ENVEOF
}

# Main
case "${1:-help}" in
    start)  cmd_start ;;
    stop)   cmd_stop ;;
    status) cmd_status ;;
    env)    cmd_env ;;
    *)
        echo "Usage: $0 {start|stop|status|env}"
        echo ""
        echo "  start   Start PipeWire headless test environment (no WirePlumber)"
        echo "  stop    Stop all test PipeWire processes"
        echo "  status  Show running state, nodes, ports, links"
        echo "  env     Print env vars (eval to set up shell for pw-cli etc.)"
        exit 1
        ;;
esac
