#!/usr/bin/env bash
# US-077 DoD #2: Capture headless browser screenshots of dashboard meters
# with a steady-state 1 kHz sine signal running through the local-demo stack.
#
# Starts the full local-demo stack, switches to measurement mode, plays
# 1 kHz sine, captures screenshots via Playwright, then tears down.
#
# Output: /tmp/mugge-screenshots/dashboard-meters.png
#         /tmp/mugge-screenshots/dashboard-full.png
#
# Usage:
#   nix run .#capture-screenshot     # preferred
#   ./scripts/screenshot-local-demo.sh  # if deps already available

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${LOCAL_DEMO_REPO_DIR:-$(dirname "$SCRIPT_DIR")}"
LOCAL_DEMO="$SCRIPT_DIR/local-demo.sh"

PYTHON="${LOCAL_DEMO_PYTHON:-python}"
E2E_PYTHON="${LOCAL_DEMO_E2E_PYTHON:-$PYTHON}"

CLEANUP_DONE=false

log() { echo "[screenshot] $*"; }
log_err() { echo "[screenshot] ERROR: $*" >&2; }

cleanup() {
    if $CLEANUP_DONE; then return; fi
    CLEANUP_DONE=true
    log "Tearing down..."
    "$LOCAL_DEMO" stop 2>/dev/null || true
    log "Cleanup complete."
}

trap cleanup EXIT INT TERM

# ---- Start the full local-demo stack ----
log "Starting full local-demo stack..."
"$LOCAL_DEMO" start || {
    log_err "local-demo start failed"
    exit 2
}

# Source PW env so pw-cli commands work
eval "$("$LOCAL_DEMO" env)"

# US-131: Instance-aware port configuration.
INSTANCE_ID="${LOCAL_DEMO_INSTANCE_ID:-0}"
PORT_OFFSET=$((INSTANCE_ID * 100))
MANIFEST_FILE="/tmp/local-demo-inst-${INSTANCE_ID}.json"

GM_PORT=$((4002 + PORT_OFFSET))
SIGGEN_PORT=$((4001 + PORT_OFFSET))

# Re-read from manifest if available
if [ -f "$MANIFEST_FILE" ]; then
    _mp() { "$PYTHON" -c "import json; print(json.load(open('$MANIFEST_FILE'))['ports']['$1'])" 2>/dev/null || echo "$2"; }
    GM_PORT=$(_mp gm "$GM_PORT")
    SIGGEN_PORT=$(_mp siggen "$SIGGEN_PORT")
fi

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
