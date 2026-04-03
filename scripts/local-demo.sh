#!/usr/bin/env bash
# Local demo stack — launches the full pi4-audio workstation locally.
#
# Starts:  PipeWire + WirePlumber → GraphManager → signal-gen → level-bridge (x4) → pcm-bridge → web-ui
# Cleanup: Ctrl+C kills all child processes (foreground mode) or `stop` subcommand (background mode)
#
# The PipeWire test environment mirrors the Pi's production topology with
# a null audio sink matching the USBStreamer name, a real filter-chain
# convolver with production-identical config, and GraphManager as the
# sole link manager (D-039). WirePlumber activates nodes and creates ports
# but does not auto-link (managed streams have no AUTOCONNECT). signal-gen
# and pcm-bridge run in managed mode.
#
# Usage:
#   nix run .#local-demo              # foreground (all deps resolved by Nix)
#   nix run .#local-demo -- start     # daemonized background mode
#   nix run .#local-demo -- stop      # stop background stack
#   nix run .#local-demo -- status    # show running state
#   nix run .#local-demo -- env       # print PW env vars for sourcing
#   ./scripts/local-demo.sh           # if already in nix develop
#
# Prerequisites:
#   - PipeWire + WirePlumber available (via Nix or system)
#   - Rust binaries built (script builds them automatically via nix build)
#   - Python with FastAPI/uvicorn (provided by nix run .#local-demo)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${LOCAL_DEMO_REPO_DIR:-$(dirname "$SCRIPT_DIR")}"

# Runtime paths (shared between start/stop/status)
PW_RUNTIME_DIR="/tmp/pw-runtime-$(id -u)"
XDG_CONFIG_DIR="/tmp/pw-test-xdg-config"
PW_PIDFILE="/tmp/pw-test-pipewire.pid"
WP_PIDFILE="/tmp/pw-test-wireplumber.pid"
STATE_FILE="/tmp/local-demo-state.env"

# Track child PIDs for cleanup
PIDS=()
CLEANUP_DONE=false
BACKGROUND_MODE=false

# ---- Background mode helper ----
# In background (start) mode, disown processes so they survive when the
# launching shell exits. Additionally, cmd_start() traps SIGHUP to
# prevent nix run's exit from killing backgrounded children.
# In foreground mode, keep them in the job table so `wait` works for
# Ctrl+C cleanup.
maybe_disown() {
    if $BACKGROUND_MODE; then
        disown "$1"
    fi
}

# ---- Resolve nix store paths ----
resolve_nix_paths() {
    if [ -z "${PW_STORE:-}" ]; then
        PW_STORE=$(nix eval --raw nixpkgs#pipewire.outPath 2>/dev/null) || {
            echo "ERROR: Cannot resolve pipewire from nixpkgs. Is nix available?" >&2
            exit 1
        }
    fi

    if [ -z "${WP_STORE:-}" ]; then
        WP_STORE=$(nix eval --raw nixpkgs#wireplumber.outPath 2>/dev/null) || {
            echo "ERROR: Cannot resolve wireplumber from nixpkgs. Is nix available?" >&2
            exit 1
        }
    fi

    if [ ! -d "$PW_STORE/bin" ]; then
        echo "Fetching pipewire..."
        nix build --no-link nixpkgs#pipewire 2>&1
    fi
    if [ ! -d "$WP_STORE/bin" ]; then
        echo "Fetching wireplumber..."
        nix build --no-link nixpkgs#wireplumber 2>&1
    fi
}

# ---- Set PW environment variables ----
setup_pw_env() {
    resolve_nix_paths
    export XDG_RUNTIME_DIR="$PW_RUNTIME_DIR"
    export SPA_PLUGIN_DIR="$PW_STORE/lib/spa-0.2"
    export PIPEWIRE_MODULE_DIR="$PW_STORE/lib/pipewire-0.3"
    export XDG_CONFIG_HOME="$XDG_CONFIG_DIR"
    export XDG_DATA_DIRS="$WP_STORE/share:$PW_STORE/share:${XDG_DATA_DIRS:-/usr/share}"
    export WIREPLUMBER_MODULE_DIR="$WP_STORE/lib/wireplumber-0.5"
    unset PIPEWIRE_CONFIG_DIR 2>/dev/null || true
    export PATH="$PW_STORE/bin:$WP_STORE/bin:$PATH"
}

# ---- Create PW/WP config files ----
create_pw_configs() {
    mkdir -p "$PW_RUNTIME_DIR"
    mkdir -p "$XDG_CONFIG_DIR/pipewire/pipewire.conf.d"
    mkdir -p "$XDG_CONFIG_DIR/pipewire/client.conf.d"

    # PipeWire: disable dbus, create production-matching USBStreamer nodes.
    # US-075 Bug #4: quantum matches production (256/256/1024/force-256).
    cat > "$XDG_CONFIG_DIR/pipewire/pipewire.conf.d/00-headless-test.conf" << 'EOF'
# Headless test environment — production topology with null audio nodes.
# Node names match GraphManager's compiled routing table (routing.rs).
# WirePlumber handles node activation; GM manages all links (D-039).
context.properties = {
    support.dbus = false
    default.clock.rate          = 48000
    default.clock.quantum       = 256
    default.clock.min-quantum   = 256
    default.clock.max-quantum   = 1024
    default.clock.force-quantum = 256
    # F-210: increase link buffer pool to prevent "out of buffers" with 7+ streams.
    link.max-buffers            = 16
}

context.objects = [
    # USBStreamer capture replacement: 8ch null Audio/Source.
    # GM uses Prefix("alsa_input.usb-MiniDSP_USBStreamer") match.
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "alsa_input.usb-MiniDSP_USBStreamer"
            media.class      = Audio/Source
            object.linger    = true
            node.driver      = true
            audio.channels   = 8
            audio.rate       = 48000
            audio.position   = [ AUX0 AUX1 AUX2 AUX3 AUX4 AUX5 AUX6 AUX7 ]
            node.autoconnect = false
            node.always-process = true
            node.latency     = 256/48000
            session.suspend-timeout-seconds = 0
            node.pause-on-idle = false
        }
    }
    # UMIK-1: replaced by room-sim filter-chain Audio/Source (US-075 Bug #1).
    # The room-sim-convolver.conf playback side produces the UMIK-1 node.
    # No separate loopback module needed.

    # ADA8200 ADC capture: replaced by loopback module (US-111 T-111-05).
    # Injected by local-demo.sh as ada8200-in-loopback.conf drop-in.
]
EOF

    # Client tools: disable dbus
    cat > "$XDG_CONFIG_DIR/pipewire/client.conf.d/00-headless-test.conf" << 'EOF'
context.properties = {
    support.dbus = false
}
EOF

    # WirePlumber: node activation only, no linking policy (F-210).
    mkdir -p "$XDG_CONFIG_DIR/wireplumber/wireplumber.conf.d"
    cat > "$XDG_CONFIG_DIR/wireplumber/wireplumber.conf.d/90-local-demo-policy.conf" << 'EOF'
wireplumber.profiles = {
  main = {
    policy.standard = disabled
    policy.node = required
    support.standard-event-source = required
  }
}
EOF
}

# ---- Start PipeWire + WirePlumber ----
start_pw() {
    setup_pw_env
    create_pw_configs

    # Check if already running
    local pw_running=false wp_running=false
    if [ -f "$PW_PIDFILE" ] && kill -0 "$(cat "$PW_PIDFILE")" 2>/dev/null; then
        pw_running=true
    fi
    if [ -f "$WP_PIDFILE" ] && kill -0 "$(cat "$WP_PIDFILE")" 2>/dev/null; then
        wp_running=true
    fi
    if $pw_running && $wp_running; then
        echo "[local-demo] PipeWire already running (PID $(cat "$PW_PIDFILE"))"
        return 0
    fi
    if $pw_running || $wp_running; then
        echo "[local-demo] Partial state detected — restarting..."
        stop_pw
    fi

    # Clean stale sockets
    rm -f "$PW_RUNTIME_DIR/pipewire"*

    echo "[local-demo] Starting PipeWire daemon..."
    "$PW_STORE/bin/pipewire" 2>/tmp/pw-test-stderr.log &
    local pw_pid=$!
    echo "$pw_pid" > "$PW_PIDFILE"
    PIDS+=($pw_pid)
    maybe_disown $pw_pid
    sleep 2

    if ! kill -0 "$pw_pid" 2>/dev/null; then
        echo "[local-demo] ERROR: PipeWire failed to start. Logs:" >&2
        cat /tmp/pw-test-stderr.log >&2
        return 1
    fi
    echo "[local-demo] PipeWire running (PID $pw_pid)"

    echo "[local-demo] Starting WirePlumber (node activation only, no linking policy)..."
    "$WP_STORE/bin/wireplumber" 2>/tmp/wp-test-stderr.log &
    local wp_pid=$!
    echo "$wp_pid" > "$WP_PIDFILE"
    PIDS+=($wp_pid)
    maybe_disown $wp_pid
    sleep 2

    if ! kill -0 "$wp_pid" 2>/dev/null; then
        echo "[local-demo] ERROR: WirePlumber failed to start. Logs:" >&2
        cat /tmp/wp-test-stderr.log >&2
        return 1
    fi
    echo "[local-demo] WirePlumber running (PID $wp_pid)"

    # Wait for PipeWire socket
    for i in $(seq 1 10); do
        if [ -e "$XDG_RUNTIME_DIR/pipewire-0" ]; then
            break
        fi
        sleep 0.5
    done
    if [ ! -e "$XDG_RUNTIME_DIR/pipewire-0" ]; then
        echo "[local-demo] ERROR: PipeWire socket not found at $XDG_RUNTIME_DIR/pipewire-0" >&2
        return 1
    fi
    echo "[local-demo] PipeWire ready."
}

# ---- Stop PipeWire + WirePlumber ----
stop_pw() {
    if [ -f "$WP_PIDFILE" ]; then
        local wp_pid
        wp_pid=$(cat "$WP_PIDFILE")
        if kill -0 "$wp_pid" 2>/dev/null; then
            kill "$wp_pid" 2>/dev/null
            echo "[local-demo] Stopped WirePlumber (PID $wp_pid)"
        fi
        rm -f "$WP_PIDFILE"
    fi
    pkill -u "$(id -u)" -x wireplumber 2>/dev/null || true

    if [ -f "$PW_PIDFILE" ]; then
        local pw_pid
        pw_pid=$(cat "$PW_PIDFILE")
        if kill -0 "$pw_pid" 2>/dev/null; then
            kill "$pw_pid" 2>/dev/null
            echo "[local-demo] Stopped PipeWire (PID $pw_pid)"
        fi
        rm -f "$PW_PIDFILE"
    fi
    pkill -u "$(id -u)" -x pipewire 2>/dev/null || true
    rm -f "$PW_RUNTIME_DIR/pipewire"*
}

# ---- Pre-flight cleanup (F-100) ----
DEMO_PROCESS_PATTERNS=(
    "pi4audio-graph-manager"
    "pi4audio-signal-gen"
    "bin/level-bridge"
    "bin/pcm-bridge"
    "mixxx-substitute"
    "uvicorn app.main:app.*8080"
)

REQUIRED_PORTS=(4001 4002 9090 9100 9101 9102 8080)

preflight_cleanup() {
    echo "[local-demo] Pre-flight cleanup: checking for stale processes..."
    local found_stale=false

    for pattern in "${DEMO_PROCESS_PATTERNS[@]}"; do
        local live_pids
        live_pids=$(pgrep -f "$pattern" 2>/dev/null | while read -r p; do
            if [ -d "/proc/$p" ] && ! grep -q '(Z)' "/proc/$p/status" 2>/dev/null; then
                echo "$p"
            fi
        done || true)
        if [ -n "$live_pids" ]; then
            found_stale=true
            echo "[local-demo]   Killing stale: $pattern (PIDs: $live_pids)"
            for p in $live_pids; do
                kill "$p" 2>/dev/null || true
            done
        fi
    done

    stop_pw 2>/dev/null || true

    if $found_stale; then
        sleep 1
        for pattern in "${DEMO_PROCESS_PATTERNS[@]}"; do
            local survivors
            survivors=$(pgrep -f "$pattern" 2>/dev/null | while read -r p; do
                if [ -d "/proc/$p" ] && ! grep -q '(Z)' "/proc/$p/status" 2>/dev/null; then
                    echo "$p"
                fi
            done || true)
            if [ -n "$survivors" ]; then
                echo "[local-demo]   Force-killing: $pattern"
                for p in $survivors; do
                    kill -9 "$p" 2>/dev/null || true
                done
            fi
        done
        sleep 0.5
    fi

    # Verify all required ports are free
    local blocked=false
    for port in "${REQUIRED_PORTS[@]}"; do
        local hex_port
        hex_port=$(printf '%04X' "$port")
        local listening
        listening=$(awk -v hp=":${hex_port}" '$2 ~ hp && $4 == "0A" {print $2}' /proc/net/tcp 2>/dev/null | head -1 || true)
        if [ -n "$listening" ]; then
            echo "[local-demo] ERROR: Port $port still has a listener" >&2
            blocked=true
        fi
    done

    if $blocked; then
        echo "[local-demo] ERROR: Cannot start — ports still in use after cleanup." >&2
        echo "[local-demo] Kill the above processes manually and retry." >&2
        exit 1
    fi

    if $found_stale; then
        echo "[local-demo] Pre-flight cleanup complete — stale processes removed."
    else
        echo "[local-demo] Pre-flight cleanup complete — no stale processes found."
    fi
}

# ---- Resolve binaries ----
resolve_binaries() {
    if [ -n "${LOCAL_DEMO_GM_BIN:-}" ]; then
        GM_BIN="$LOCAL_DEMO_GM_BIN"
        SG_BIN="$LOCAL_DEMO_SG_BIN"
        LB_BIN="$LOCAL_DEMO_LB_BIN"
        PCM_BIN="$LOCAL_DEMO_PCM_BIN"
        PYTHON="${LOCAL_DEMO_PYTHON:-python3}"
        PW_JACK="${LOCAL_DEMO_PW_JACK:-pw-jack}"
        echo "[local-demo] Using pre-resolved binary paths from nix."
    else
        echo "[local-demo] Resolving Rust binaries via nix build..."
        local ARCH
        ARCH=$(nix eval --raw nixpkgs#system 2>/dev/null || echo "aarch64-linux")
        resolve_binary() {
            local pkg="$1"
            local bin_name="$2"
            local store_path
            store_path=$(nix build ".#packages.${ARCH}.$pkg" --no-link --print-out-paths 2>/dev/null) || {
                echo "[local-demo] ERROR: Failed to build $pkg" >&2
                exit 1
            }
            echo "$store_path/bin/$bin_name"
        }
        GM_BIN=$(resolve_binary graph-manager pi4audio-graph-manager)
        SG_BIN=$(resolve_binary signal-gen pi4audio-signal-gen)
        LB_BIN=$(resolve_binary level-bridge level-bridge)
        PCM_BIN=$(resolve_binary pcm-bridge pcm-bridge)
        PYTHON="python3"
        PW_JACK="pw-jack"
    fi

    echo "  graph-manager: $GM_BIN"
    echo "  signal-gen:    $SG_BIN"
    echo "  level-bridge:  $LB_BIN"
    echo "  pcm-bridge:    $PCM_BIN"
}

# ---- Install configs ----
install_configs() {
    # Convolver coefficients directory — same path the measurement pipeline
    # writes to (PI4AUDIO_COEFFS_DIR).
    COEFFS_DIR="/tmp/pi4audio-demo/coeffs"
    ROOM_SIM_DIR="/tmp/pw-test-room-sim"
    PW_CONF_DIR="$XDG_CONFIG_DIR/pipewire/pipewire.conf.d"
    mkdir -p "$PW_CONF_DIR" "$COEFFS_DIR" "$ROOM_SIM_DIR"

    # F-226, D-063: Generate Dirac passthrough coefficients if none exist.
    # Without coefficient WAVs the convolver filter-chain won't load, which
    # breaks the entire signal path (signal-gen → convolver → room-sim → UMIK-1).
    # generates 5 files: dirac.wav (identity for HP/IEM ch 5-8) + 4 combined_*.wav
    # (passthrough defaults for speaker ch 0-3, overwritten by measurements).
    # All 16384 samples at 48 kHz — uniform tap length per D-063.
    # F-236: Also check dirac.wav exists and files are not stubs (>1000 bytes).
    # Stale 48-byte WAV headers from a previous session fool ls but cause the
    # filter-chain convolver to fail silently at runtime.
    local _need_regen=0
    if ! ls "$COEFFS_DIR"/combined_*.wav 1>/dev/null 2>&1; then
        _need_regen=1
    elif ! [ -f "$COEFFS_DIR/dirac.wav" ]; then
        _need_regen=1
    elif [ "$(stat -c%s "$COEFFS_DIR/dirac.wav" 2>/dev/null || echo 0)" -lt 1000 ]; then
        _need_regen=1
    fi
    if [ "$_need_regen" -eq 1 ]; then
        echo "[local-demo] Generating Dirac passthrough coefficients (F-226, D-063)..."
        "$PYTHON" "$REPO_DIR/scripts/generate-dirac.py" "$COEFFS_DIR"
        echo "[local-demo] Dirac passthrough coefficients generated in $COEFFS_DIR"
    fi

    # Install convolver config with resolved coefficient paths.
    sed "s|COEFFS_DIR|$COEFFS_DIR|g" \
        "$REPO_DIR/configs/local-demo/convolver.conf" \
        > "$PW_CONF_DIR/30-convolver.conf"
    echo "[local-demo] Convolver config installed (coefficients in $COEFFS_DIR)"

    # Remove stale deploy-generated convolver config from previous measurement sessions.
    rm -f "$PW_CONF_DIR/30-filter-chain-convolver.conf"

    # US-075 Bug #1: UMIK-1 loopback no longer needed — room-sim filter-chain
    # produces the UMIK-1 Audio/Source directly via internal mixer summing.
    rm -f "$PW_CONF_DIR/35-umik1-loopback.conf"

    # US-111 T-111-05: Install ADA8200 ADC capture loopback config.
    install -m 644 "$REPO_DIR/configs/local-demo/ada8200-in-loopback.conf" \
        "$PW_CONF_DIR/37-ada8200-in-loopback.conf"
    echo "[local-demo] ADA8200 loopback config installed (8ch ADC capture)"

    # F-159/US-111/US-075: Generate per-channel room simulator IRs and install config.
    # The room-sim filter-chain applies per-channel synthetic room IRs, sums via
    # internal mixer builtin to mono, and outputs as UMIK-1 Audio/Source.
    # Room-sim IRs are in a separate directory from convolver coefficients —
    # they're a hardware mock (permitted), not a filter pipeline mock.
    echo "[local-demo] Generating per-channel room simulator impulse responses..."
    "$PYTHON" "$REPO_DIR/scripts/generate-room-sim-ir.py" --per-channel "$ROOM_SIM_DIR"
    sed "s|COEFFS_DIR|$ROOM_SIM_DIR|g" \
        "$REPO_DIR/configs/local-demo/room-sim-convolver.conf" \
        > "$PW_CONF_DIR/36-room-sim-convolver.conf"
    echo "[local-demo] Room-sim config installed (4ch per-channel IRs → mixer → UMIK-1)"
}

# ---- Start all services ----
start_services() {
    # ---- GraphManager ----
    # US-075 Bug #2b: standby mode (not measurement).
    echo ""
    echo "[local-demo] Starting GraphManager (port 4002, standby mode)..."
    "$GM_BIN" --listen tcp:127.0.0.1:4002 --mode standby --log-level info &
    PIDS+=($!)
    maybe_disown $!
    sleep 1

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo "[local-demo] ERROR: GraphManager failed to start" >&2
        exit 1
    fi
    echo "[local-demo] GraphManager running (PID ${PIDS[-1]})"

    # ---- signal-gen (managed mode) ----
    echo ""
    echo "[local-demo] Starting signal-gen (port 4001, managed mode, mono)..."
    "$SG_BIN" \
        --managed \
        --channels 1 \
        --rate 48000 \
        --listen tcp:127.0.0.1:4001 \
        --max-level-dbfs -20 &
    PIDS+=($!)
    maybe_disown $!
    sleep 1

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo "[local-demo] ERROR: signal-gen failed to start" >&2
        exit 1
    fi
    echo "[local-demo] signal-gen running (PID ${PIDS[-1]})"

    # ---- level-bridge-sw (managed mode) ----
    echo ""
    echo "[local-demo] Starting level-bridge-sw (levels on port 9100, managed mode)..."
    "$LB_BIN" \
        --managed \
        --node-name pi4audio-level-bridge-sw \
        --mode capture \
        --target unused-managed-mode \
        --levels-listen tcp:0.0.0.0:9100 \
        --channels 8 \
        --rate 48000 &
    PIDS+=($!)
    maybe_disown $!
    sleep 1

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo "[local-demo] ERROR: level-bridge-sw failed to start" >&2
        exit 1
    fi
    echo "[local-demo] level-bridge-sw running (PID ${PIDS[-1]})"

    # ---- level-bridge-hw-out (managed mode, US-075 Bug #6) ----
    # Taps USBStreamer room-sim monitor_AUX0-7 ports for hardware output metering.
    echo ""
    echo "[local-demo] Starting level-bridge-hw-out (levels on port 9101, managed mode)..."
    "$LB_BIN" \
        --managed \
        --node-name pi4audio-level-bridge-hw-out \
        --mode monitor \
        --target unused-managed-mode \
        --levels-listen tcp:0.0.0.0:9101 \
        --channels 8 \
        --rate 48000 &
    PIDS+=($!)
    maybe_disown $!
    sleep 1

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo "[local-demo] ERROR: level-bridge-hw-out failed to start" >&2
        exit 1
    fi
    echo "[local-demo] level-bridge-hw-out running (PID ${PIDS[-1]})"

    # ---- level-bridge-hw-in (managed mode, US-075 Bug #6) ----
    # Taps ADA8200 capture_AUX0-7 ports for hardware input metering.
    echo ""
    echo "[local-demo] Starting level-bridge-hw-in (levels on port 9102, managed mode)..."
    "$LB_BIN" \
        --managed \
        --node-name pi4audio-level-bridge-hw-in \
        --mode capture \
        --target unused-managed-mode \
        --levels-listen tcp:0.0.0.0:9102 \
        --channels 8 \
        --rate 48000 &
    PIDS+=($!)
    maybe_disown $!
    sleep 1

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo "[local-demo] ERROR: level-bridge-hw-in failed to start" >&2
        exit 1
    fi
    echo "[local-demo] level-bridge-hw-in running (PID ${PIDS[-1]})"

    # ---- pcm-bridge (managed mode) ----
    echo ""
    echo "[local-demo] Starting pcm-bridge (PCM on port 9090, managed mode)..."
    "$PCM_BIN" \
        --managed \
        --mode monitor \
        --listen tcp:0.0.0.0:9090 \
        --channels 8 \
        --rate 48000 &
    PIDS+=($!)
    maybe_disown $!
    sleep 1

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo "[local-demo] ERROR: pcm-bridge failed to start" >&2
        exit 1
    fi
    echo "[local-demo] pcm-bridge running (PID ${PIDS[-1]})"

    # ---- Mixxx substitute (US-075 Bug #3) ----
    # JACK client named "Mixxx" with 8 output ports (out_0..out_7) matching
    # GM's routing table. Plays stereo mp3/wav on ch 1-2, silence on ch 3-8.
    # Must run under pw-jack for JACK-style port naming.
    MP3_FILE="$HOME/Claudia singt Cole Porter - I love Paris.mp3"
    echo ""
    echo "[local-demo] Starting Mixxx substitute (pw-jack JACK client, 8ch)..."
    MIXXX_ARGS=(--channels 8 --client-name Mixxx)
    if [ -f "$MP3_FILE" ]; then
        echo "[local-demo]   Audio source: $(basename "$MP3_FILE")"
        MIXXX_ARGS+=(--file "$MP3_FILE")
    else
        echo "[local-demo]   No mp3 found, Mixxx substitute will output silence."
    fi
    "$PW_JACK" "$PYTHON" "$REPO_DIR/scripts/mixxx-substitute.py" "${MIXXX_ARGS[@]}" &
    PIDS+=($!)
    maybe_disown $!
    sleep 2

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo "[local-demo] ERROR: Mixxx substitute failed to start" >&2
        exit 1
    fi
    echo "[local-demo] Mixxx substitute running (PID ${PIDS[-1]})"

    # ---- Wait for GM link creation ----
    sleep 2
    LINK_COUNT=$(pw-link -l 2>/dev/null | grep -c '^\s*|' || echo 0)
    echo ""
    echo "[local-demo] $LINK_COUNT link endpoints active (GM reconciler, standby mode)."

    # ---- web-ui ----
    echo ""
    echo "[local-demo] Starting web-ui (port 8080, real collectors)..."
    export PI_AUDIO_MOCK=0
    export PI4AUDIO_GM_HOST=127.0.0.1
    export PI4AUDIO_GM_PORT=4002
    export PI4AUDIO_LEVELS_HOST=127.0.0.1
    export PI4AUDIO_LEVELS_SW_PORT=9100
    export PI4AUDIO_LEVELS_HW_OUT_PORT=9101
    export PI4AUDIO_LEVELS_HW_IN_PORT=9102
    export PI4AUDIO_SKIP_GM_RECOVERY=1
    export PI4AUDIO_AUTH_DISABLED=1
    export PI4AUDIO_SIGGEN=1
    export PI4AUDIO_PCM_CHANNELS=8
    export PI4AUDIO_MEASUREMENT_ATTENUATION_DB=-20
    export PI4AUDIO_RECORDING_PEAK_CEILING_DBFS=20
    export PI4AUDIO_MIC_CLIP_THRESHOLD_DBFS=0
    export PI4AUDIO_RECORDING_DC_CEILING=0.1
    # Target must be achievable with signal-gen cap (-20 dBFS) through
    # venue gains (-20 dB).  At -28 dBFS the room-sim yields ~80 dB SPL.
    export PI4AUDIO_TARGET_SPL_DB=80
    export PI4AUDIO_HARD_LIMIT_SPL_DB=95
    export PI4AUDIO_FILTER_OUTPUT_DIR="/tmp/pi4audio-demo/filters"
    export PI4AUDIO_SESSION_DIR="/tmp/pi4audio-demo/sessions"
    export PI4AUDIO_PW_CONF_DIR="$XDG_CONFIG_HOME/pipewire/pipewire.conf.d"
    export PI4AUDIO_COEFFS_DIR="/tmp/pi4audio-demo/coeffs"
    export PI4AUDIO_SPEAKERS_DIR="/tmp/pi4audio-demo/speakers"
    export PI4AUDIO_HARDWARE_DIR="/tmp/pi4audio-demo/hardware"
    mkdir -p "$PI4AUDIO_FILTER_OUTPUT_DIR" "$PI4AUDIO_SESSION_DIR"
    mkdir -p "$PI4AUDIO_SPEAKERS_DIR/profiles" "$PI4AUDIO_SPEAKERS_DIR/identities"
    mkdir -p "$PI4AUDIO_HARDWARE_DIR/amplifiers" "$PI4AUDIO_HARDWARE_DIR/dacs"
    cp -n "$REPO_DIR"/configs/speakers/profiles/*.yml "$PI4AUDIO_SPEAKERS_DIR/profiles/" 2>/dev/null || true
    cp -n "$REPO_DIR"/configs/speakers/identities/*.yml "$PI4AUDIO_SPEAKERS_DIR/identities/" 2>/dev/null || true
    cp -n "$REPO_DIR"/configs/hardware/*.yml "$PI4AUDIO_HARDWARE_DIR/" 2>/dev/null || true
    cp -n "$REPO_DIR"/configs/hardware/amplifiers/*.yml "$PI4AUDIO_HARDWARE_DIR/amplifiers/" 2>/dev/null || true
    cp -n "$REPO_DIR"/configs/hardware/dacs/*.yml "$PI4AUDIO_HARDWARE_DIR/dacs/" 2>/dev/null || true

    cd "$REPO_DIR/src/web-ui"
    "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload &
    PIDS+=($!)
    maybe_disown $!
    sleep 2

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo "[local-demo] ERROR: web-ui failed to start" >&2
        exit 1
    fi
}

# ---- Save state for stop/status ----
save_state() {
    cat > "$STATE_FILE" << EOF
PIDS=(${PIDS[*]})
PW_PIDFILE="$PW_PIDFILE"
WP_PIDFILE="$WP_PIDFILE"
EOF
}

# ---- Print summary ----
print_summary() {
    echo ""
    echo "============================================================"
    echo "  Local demo stack is running!"
    echo ""
    echo "  Web UI:              http://localhost:8080"
    echo "  GraphManager:        tcp://127.0.0.1:4002 (RPC, standby mode)"
    echo "  signal-gen:          tcp://127.0.0.1:4001 (RPC, managed mode)"
    echo "  level-bridge-sw:     tcp://127.0.0.1:9100 (levels, app output tap)"
    echo "  level-bridge-hw-out: tcp://127.0.0.1:9101 (levels, USBStreamer monitor)"
    echo "  level-bridge-hw-in:  tcp://127.0.0.1:9102 (levels, ADA8200 capture)"
    echo "  pcm-bridge:          tcp://127.0.0.1:9090 (PCM, managed mode)"
    echo ""
    echo "  PW nodes:     alsa_output.usb-MiniDSP_USBStreamer-local-demo (room-sim sink, 8ch)"
    echo "                alsa_input.usb-MiniDSP_USBStreamer (null source)"
    echo "                alsa_input.usb-miniDSP_Umik-1 (room-sim mixer output, mono)"
    echo "                ada8200-in (loopback source, 8ch ADC capture)"
    echo "                ada8200-in-loopback-sink (loopback sink, 8ch)"
    echo "                pi4audio-convolver (filter-chain, loads from $COEFFS_DIR)"
    echo "                pi4audio-convolver-out (filter-chain output)"
    echo "                Mixxx (JACK client substitute, 8ch, pw-jack)"
    echo "  Audio: Mixxx substitute plays mp3 (switch to DJ mode for full routing)"
    echo ""
    echo "  PIDs: ${PIDS[*]}"
    echo "============================================================"
    echo ""
}

# ---- Foreground cleanup trap ----
cleanup() {
    if $CLEANUP_DONE; then return; fi
    CLEANUP_DONE=true

    echo ""
    echo "[local-demo] Shutting down..."

    for (( i=${#PIDS[@]}-1 ; i>=0 ; i-- )) ; do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            pkill -P "$pid" 2>/dev/null || true
            kill "$pid" 2>/dev/null || true
        fi
    done

    sleep 0.5

    for (( i=${#PIDS[@]}-1 ; i>=0 ; i-- )) ; do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            echo "[local-demo] Force-killing PID $pid..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    done

    for pid in "${PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
    done

    stop_pw
    rm -f "$STATE_FILE"
    echo "[local-demo] All processes stopped."
}

# ==== Subcommands ====

cmd_start() {
    BACKGROUND_MODE=true

    preflight_cleanup
    resolve_binaries
    install_configs
    start_pw
    start_services
    save_state
    print_summary

    echo "[local-demo] Stack started in background. Use '$0 stop' to shut down."
}

cmd_stop() {
    echo "[local-demo] Stopping local-demo stack..."

    # Load saved PIDs
    if [ -f "$STATE_FILE" ]; then
        # shellcheck disable=SC1090
        source "$STATE_FILE"
    fi

    # Kill service processes
    for (( i=${#PIDS[@]}-1 ; i>=0 ; i-- )) ; do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            pkill -P "$pid" 2>/dev/null || true
            kill "$pid" 2>/dev/null || true
        fi
    done
    sleep 0.5
    for (( i=${#PIDS[@]}-1 ; i>=0 ; i-- )) ; do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done

    # Also kill by pattern in case PIDs are stale
    for pattern in "${DEMO_PROCESS_PATTERNS[@]}"; do
        pkill -f "$pattern" 2>/dev/null || true
    done

    stop_pw
    rm -f "$STATE_FILE"
    echo "[local-demo] All processes stopped."
}

cmd_status() {
    setup_pw_env

    local pw_alive=false wp_alive=false
    if [ -f "$PW_PIDFILE" ] && kill -0 "$(cat "$PW_PIDFILE")" 2>/dev/null; then
        pw_alive=true
    fi
    if [ -f "$WP_PIDFILE" ] && kill -0 "$(cat "$WP_PIDFILE")" 2>/dev/null; then
        wp_alive=true
    fi

    echo "PipeWire:      $(if $pw_alive; then echo "running (PID $(cat "$PW_PIDFILE"))"; else echo "stopped"; fi)"
    echo "WirePlumber:   $(if $wp_alive; then echo "running (PID $(cat "$WP_PIDFILE"))"; else echo "stopped"; fi)"

    if [ -f "$STATE_FILE" ]; then
        # shellcheck disable=SC1090
        source "$STATE_FILE"
        local alive=0 dead=0
        for pid in "${PIDS[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                alive=$((alive + 1))
            else
                dead=$((dead + 1))
            fi
        done
        echo "Services:      $alive alive, $dead dead (of ${#PIDS[@]} tracked)"
    else
        echo "Services:      no state file found"
    fi

    if $pw_alive; then
        echo ""
        echo "Nodes:"
        timeout 3 pw-dump 2>/dev/null | grep '"node.name"' | sed 's/.*"node.name": "\(.*\)".*/  - \1/' || true
        echo ""
        echo "Links:"
        timeout 3 pw-link -l 2>&1 | grep '|' | sed 's/^/  /' || true
        if ! timeout 3 pw-link -l 2>&1 | grep -q '|'; then
            echo "  (none)"
        fi
    fi
}

cmd_env() {
    resolve_nix_paths
    cat << ENVEOF
export XDG_RUNTIME_DIR="$PW_RUNTIME_DIR"
export SPA_PLUGIN_DIR="$PW_STORE/lib/spa-0.2"
export PIPEWIRE_MODULE_DIR="$PW_STORE/lib/pipewire-0.3"
export WIREPLUMBER_MODULE_DIR="$WP_STORE/lib/wireplumber-0.5"
export XDG_CONFIG_HOME="$XDG_CONFIG_DIR"
export XDG_DATA_DIRS="$WP_STORE/share:$PW_STORE/share:\${XDG_DATA_DIRS:-/usr/share}"
unset PIPEWIRE_CONFIG_DIR 2>/dev/null || true
export PATH="$PW_STORE/bin:$WP_STORE/bin:\$PATH"
ENVEOF
}

cmd_foreground() {
    trap cleanup EXIT INT TERM

    preflight_cleanup
    resolve_binaries
    install_configs
    start_pw
    start_services
    print_summary

    echo "  Press Ctrl+C to stop all services."
    echo ""

    wait
}

# ==== Main dispatch ====

case "${1:-}" in
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    status)     cmd_status ;;
    env)        cmd_env ;;
    ""|foreground)  cmd_foreground ;;
    *)
        echo "Usage: $0 {start|stop|status|env|foreground}"
        echo ""
        echo "  start      Start all services in background (daemonized)"
        echo "  stop       Stop all services"
        echo "  status     Show running state, nodes, links"
        echo "  env        Print PW env vars (eval to set up shell)"
        echo "  foreground Start in foreground (Ctrl+C to stop) [default]"
        exit 1
        ;;
esac
