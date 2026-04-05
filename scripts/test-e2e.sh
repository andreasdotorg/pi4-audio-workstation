#!/usr/bin/env bash
# Real E2E test runner — starts local-demo stack, runs pytest, tears down.
#
# Starts the full local-demo stack (PipeWire + GM + signal-gen + pcm-bridge +
# level-bridge + web UI) with PI_AUDIO_MOCK=0, waits for health, runs the
# E2E test suite (src/web-ui/tests/e2e/), and tears down on exit.
#
# Only physical audio hardware is absent — everything else is real.
#
# Usage:
#   nix run .#test-e2e               # preferred (all deps from Nix)
#   ./scripts/test-e2e.sh            # if already in nix develop
#
# Exit codes:
#   0 = all tests passed
#   1 = test failure(s)
#   2 = infrastructure error (stack failed to start)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${LOCAL_DEMO_REPO_DIR:-$(dirname "$SCRIPT_DIR")}"
LOCAL_DEMO="${LOCAL_DEMO_SH:-$REPO_DIR/scripts/local-demo.sh}"
BASH_BIN="${LOCAL_DEMO_BASH:-bash}"
PYTHON="${LOCAL_DEMO_PYTHON:-python}"
E2E_PYTHON="${LOCAL_DEMO_E2E_PYTHON:-$PYTHON}"

# US-131: Discover web UI port from manifest or env var.
# LOCAL_DEMO_INSTANCE_ID flows through to local-demo.sh automatically.
INSTANCE_ID="${LOCAL_DEMO_INSTANCE_ID:-0}"
MANIFEST_FILE="/tmp/local-demo-inst-${INSTANCE_ID}.json"

_read_manifest_port() {
    local key="$1" default="$2"
    if [ -f "$MANIFEST_FILE" ]; then
        "$PYTHON" -c "
import json
m = json.load(open('$MANIFEST_FILE'))
print(m['ports']['$key'])
" 2>/dev/null && return
    fi
    echo "$default"
}

WEB_UI_PORT="${LOCAL_DEMO_WEBUI_PORT:-$((8080 + INSTANCE_ID * 100))}"
LOCAL_DEMO_URL="http://localhost:${WEB_UI_PORT}"

CLEANUP_DONE=false

log() { echo "[test-e2e] $*"; }
log_err() { echo "[test-e2e] ERROR: $*" >&2; }

cleanup() {
    if $CLEANUP_DONE; then return; fi
    CLEANUP_DONE=true
    log "Tearing down local-demo stack..."
    "$BASH_BIN" "$LOCAL_DEMO" stop 2>/dev/null || true
    log "Cleanup complete."
}

trap cleanup EXIT INT TERM

# ---- 1. Start local-demo stack ----

log "Starting local-demo stack (PI_AUDIO_MOCK=0)..."
"$BASH_BIN" "$LOCAL_DEMO" start || {
    log_err "local-demo start failed"
    exit 2
}

# Source PW env so any pw-cli calls in tests work
eval "$("$BASH_BIN" "$LOCAL_DEMO" env)"

# Re-read actual web UI port from manifest (may differ from computed default
# if env var overrides were used during local-demo start).
if [ -f "$MANIFEST_FILE" ]; then
    MANIFEST_PORT=$("$PYTHON" -c "import json; print(json.load(open('$MANIFEST_FILE'))['ports']['webui'])" 2>/dev/null || true)
    if [ -n "$MANIFEST_PORT" ]; then
        WEB_UI_PORT="$MANIFEST_PORT"
        LOCAL_DEMO_URL="http://localhost:${WEB_UI_PORT}"
    fi
fi

# ---- 2. Wait for web UI health ----

log "Waiting for web UI at ${LOCAL_DEMO_URL}..."
DEADLINE=$((SECONDS + 30))
while [ $SECONDS -lt $DEADLINE ]; do
    if curl -sf "${LOCAL_DEMO_URL}/" >/dev/null 2>&1; then
        log "Web UI is reachable."
        break
    fi
    sleep 1
done

if ! curl -sf "${LOCAL_DEMO_URL}/" >/dev/null 2>&1; then
    log_err "Web UI not reachable after 30s"
    exit 2
fi

# Allow services to stabilize (GM reconciler, level-bridges)
sleep 2

# ---- 3. Run E2E tests ----

log "Running E2E tests..."
export LOCAL_DEMO_URL
cd "$REPO_DIR/src/web-ui"
"$E2E_PYTHON" -m pytest tests/e2e/ -v --tb=short "$@"
