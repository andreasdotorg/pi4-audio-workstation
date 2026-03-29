#!/usr/bin/env bash
# US-077 DoD #2: Capture headless browser screenshots of dashboard meters
# with a steady-state 1 kHz sine signal running through the local-demo stack.
#
# Starts: PW test env + GM + signal-gen + level-bridge (x3) + pcm-bridge + web-ui
# Then:   Switches to measurement mode, plays 1 kHz sine, captures screenshots
# Output: /tmp/mugge-screenshots/dashboard-meters.png
#         /tmp/mugge-screenshots/dashboard-full.png
#
# Usage:
#   nix run .#capture-screenshot     # preferred
#   ./scripts/screenshot-local-demo.sh  # if deps already available

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${LOCAL_DEMO_REPO_DIR:-$(dirname "$SCRIPT_DIR")}"
PW_TEST_ENV="${LOCAL_DEMO_PW_TEST_ENV:-$SCRIPT_DIR/local-pw-test-env.sh}"

# Track child PIDs for cleanup
PIDS=()
PW_STARTED=false
CLEANUP_DONE=false

log() { echo "[screenshot] $*"; }
log_err() { echo "[screenshot] ERROR: $*" >&2; }

cleanup() {
    if $CLEANUP_DONE; then return; fi
    CLEANUP_DONE=true
    log "Tearing down..."
    for (( i=${#PIDS[@]}-1 ; i>=0 ; i-- )); do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            pkill -P "$pid" 2>/dev/null || true
            kill "$pid" 2>/dev/null || true
        fi
    done
    sleep 0.3
    for (( i=${#PIDS[@]}-1 ; i>=0 ; i-- )); do
        local pid="${PIDS[$i]}"
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    for pid in "${PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
    if $PW_STARTED; then
        "$PW_TEST_ENV" stop 2>/dev/null || true
    fi
    log "Cleanup complete."
}

trap cleanup EXIT INT TERM

# ---- Pre-flight ----
MY_PID=$$
MY_PPID=$PPID
for pattern in "pi4audio-graph-manager" "pi4audio-signal-gen" "[b]in/level-bridge" "[b]in/pcm-bridge" "uvicorn app.main"; do
    stale_pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    for p in $stale_pids; do
        if [ "$p" != "$MY_PID" ] && [ "$p" != "$MY_PPID" ]; then
            log "Killing stale process: $pattern (PID $p)"
            kill "$p" 2>/dev/null || true
        fi
    done
done
"$PW_TEST_ENV" stop 2>/dev/null || true
sleep 0.5

# ---- Resolve binaries ----
if [ -n "${LOCAL_DEMO_GM_BIN:-}" ]; then
    GM_BIN="$LOCAL_DEMO_GM_BIN"
    SG_BIN="$LOCAL_DEMO_SG_BIN"
    LB_BIN="$LOCAL_DEMO_LB_BIN"
    PCM_BIN="$LOCAL_DEMO_PCM_BIN"
    PYTHON="${LOCAL_DEMO_PYTHON:-python}"
    E2E_PYTHON="${LOCAL_DEMO_E2E_PYTHON:-$PYTHON}"
else
    log_err "This script expects LOCAL_DEMO_* env vars (run via nix run .#capture-screenshot)"
    exit 2
fi

# ---- Generate coefficients + convolver config ----
COEFFS_DIR="/tmp/pw-test-coeffs"
"$PYTHON" "$REPO_DIR/scripts/generate-dirac-coeffs.py" "$COEFFS_DIR" > /dev/null

PW_CONF_DIR="/tmp/pw-test-xdg-config/pipewire/pipewire.conf.d"
mkdir -p "$PW_CONF_DIR"
sed "s|COEFFS_DIR|$COEFFS_DIR|g" \
    "$REPO_DIR/configs/local-demo/convolver.conf" \
    > "$PW_CONF_DIR/30-convolver.conf"
rm -f "$PW_CONF_DIR/30-filter-chain-convolver.conf"
install -m 644 "$REPO_DIR/configs/local-demo/umik1-loopback.conf" \
    "$PW_CONF_DIR/35-umik1-loopback.conf"
"$PYTHON" "$REPO_DIR/scripts/generate-room-sim-ir.py" "$COEFFS_DIR" > /dev/null
sed "s|COEFFS_DIR|$COEFFS_DIR|g" \
    "$REPO_DIR/configs/local-demo/room-sim-convolver.conf" \
    > "$PW_CONF_DIR/36-room-sim-convolver.conf"
log "Coefficients and configs generated."

# ---- Start PipeWire ----
log "Starting PipeWire test environment..."
"$PW_TEST_ENV" start > /dev/null 2>&1
PW_STARTED=true
eval "$("$PW_TEST_ENV" env)"

for i in $(seq 1 20); do
    if [ -e "$XDG_RUNTIME_DIR/pipewire-0" ]; then break; fi
    sleep 0.25
done
if [ ! -e "$XDG_RUNTIME_DIR/pipewire-0" ]; then
    log_err "PipeWire socket not found"
    exit 2
fi
log "PipeWire ready."

# ---- Start services ----
GM_PORT=4002
SIGGEN_PORT=4001

"$GM_BIN" --listen tcp:127.0.0.1:$GM_PORT --mode monitoring --log-level warn 2>/tmp/gm-screenshot.log &
PIDS+=($!)
sleep 1

"$SG_BIN" --managed --channels 1 --rate 48000 \
    --listen tcp:127.0.0.1:$SIGGEN_PORT --max-level-dbfs -20 2>/tmp/sg-screenshot.log &
PIDS+=($!)
sleep 1

"$LB_BIN" --managed --node-name pi4audio-level-bridge-sw \
    --mode capture --target unused-managed-mode \
    --levels-listen tcp:127.0.0.1:9100 --channels 8 --rate 48000 2>/tmp/lb-sw-screenshot.log &
PIDS+=($!)
sleep 0.5

"$LB_BIN" --managed --node-name pi4audio-level-bridge-hw-out \
    --mode monitor --target alsa_output.usb-MiniDSP_USBStreamer \
    --levels-listen tcp:127.0.0.1:9101 --channels 8 --rate 48000 2>/tmp/lb-hwout-screenshot.log &
PIDS+=($!)
sleep 0.5

"$LB_BIN" --managed --node-name pi4audio-level-bridge-hw-in \
    --mode capture --target alsa_input.usb-MiniDSP_USBStreamer \
    --levels-listen tcp:127.0.0.1:9102 --channels 8 --rate 48000 2>/tmp/lb-hwin-screenshot.log &
PIDS+=($!)
sleep 0.5

# For screenshot captures, run pcm-bridge in non-managed capture mode
# targeting the convolver output (Audio/Source). In local-demo measurement
# mode, there is no app (Mixxx/Reaper) to tap, so we capture directly from
# the convolver output to give the spectrum ch0+ch1 data.
"$PCM_BIN" --mode capture --target pi4audio-convolver-out \
    --listen tcp:127.0.0.1:9090 --channels 4 --rate 48000 2>/tmp/pcm-screenshot.log &
PIDS+=($!)
sleep 1

log "All audio services running."

# ---- Wait for GM reconciliation ----
sleep 3

# ---- Switch to measurement mode ----
log "Switching GM to measurement mode..."
if exec 3<>/dev/tcp/127.0.0.1/$GM_PORT 2>/dev/null; then
    echo '{"cmd":"set_mode","mode":"measurement"}' >&3
    timeout 2 head -n1 <&3 2>/dev/null || true
    exec 3>&- 2>/dev/null
fi
sleep 2

# ---- Play 1 kHz sine ----
log "Playing 1 kHz sine at -20 dBFS..."
if exec 3<>/dev/tcp/127.0.0.1/$SIGGEN_PORT 2>/dev/null; then
    echo '{"cmd":"play","signal":"sine","freq":1000.0,"level_dbfs":-20.0,"channels":[1]}' >&3
    timeout 2 head -n1 <&3 2>/dev/null || true
    exec 3>&- 2>/dev/null
fi
sleep 2

# ---- Start web-ui ----
log "Starting web-ui on port 8080..."
export PI_AUDIO_MOCK=0
export PI4AUDIO_GM_HOST=127.0.0.1
export PI4AUDIO_GM_PORT=4002
export PI4AUDIO_LEVELS_HOST=127.0.0.1
export PI4AUDIO_LEVELS_SW_PORT=9100
export PI4AUDIO_LEVELS_HW_OUT_PORT=9101
export PI4AUDIO_LEVELS_HW_IN_PORT=9102
export PI4AUDIO_SKIP_GM_RECOVERY=1
export PI4AUDIO_SIGGEN=1
export PI4AUDIO_PCM_CHANNELS=4
export PI4AUDIO_MEASUREMENT_ATTENUATION_DB=-20
export PI4AUDIO_RECORDING_PEAK_CEILING_DBFS=20
export PI4AUDIO_MIC_CLIP_THRESHOLD_DBFS=0
export PI4AUDIO_RECORDING_DC_CEILING=0.1
export PI4AUDIO_TARGET_SPL_DB=90
export PI4AUDIO_HARD_LIMIT_SPL_DB=100
export PI4AUDIO_FILTER_OUTPUT_DIR="/tmp/pi4audio-demo/filters"
export PI4AUDIO_SESSION_DIR="/tmp/pi4audio-demo/sessions"
export PI4AUDIO_PW_CONF_DIR="$XDG_CONFIG_HOME/pipewire/pipewire.conf.d"
export PI4AUDIO_COEFFS_DIR="$COEFFS_DIR"
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
"$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8080 2>/tmp/webui-screenshot.log &
PIDS+=($!)
sleep 3

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    log_err "web-ui failed to start"
    exit 2
fi
log "Web UI running on http://localhost:8080"

# ---- Capture screenshots ----
log "Capturing screenshots with headless browser..."
if "$E2E_PYTHON" "$REPO_DIR/scripts/capture-ui-screenshot.py" 2>/tmp/screenshot-playwright.log; then
    log "Screenshots captured successfully."
    ls -la /tmp/mugge-screenshots/ 2>/dev/null || true
    exit 0
else
    log_err "Screenshot capture failed. Playwright log:"
    cat /tmp/screenshot-playwright.log 2>/dev/null || true
    exit 1
fi
