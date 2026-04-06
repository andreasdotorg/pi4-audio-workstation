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

# Helper: read a port from the manifest, falling back to a default.
_read_manifest_port() {
    local key="$1" default="$2"
    if [ -n "${LOCAL_DEMO_MANIFEST:-}" ] && [ -f "$LOCAL_DEMO_MANIFEST" ]; then
        "$PYTHON" -c "
import json
m = json.load(open('$LOCAL_DEMO_MANIFEST'))
print(m['ports']['$key'])
" 2>/dev/null && return
    fi
    echo "$default"
}

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

START_LOG=$(mktemp /tmp/test-e2e-start-XXXXXX.log)
log "Starting local-demo stack (PI_AUDIO_MOCK=0)..."
"$BASH_BIN" "$LOCAL_DEMO" start >"$START_LOG" 2>&1 || {
    log_err "local-demo start failed"
    cat "$START_LOG"
    rm -f "$START_LOG"
    exit 2
}
cat "$START_LOG"

# Extract the manifest path from start output. The start command prints:
#   [local-demo] Manifest written to /tmp/local-demo-<PID>.json
# We must set LOCAL_DEMO_MANIFEST before calling env, because env runs in a
# different process (different $$) and would compute a wrong manifest path.
export LOCAL_DEMO_MANIFEST
LOCAL_DEMO_MANIFEST=$(sed -n 's/.*Manifest written to //p' "$START_LOG")
rm -f "$START_LOG"
if [ -z "$LOCAL_DEMO_MANIFEST" ] || [ ! -f "$LOCAL_DEMO_MANIFEST" ]; then
    log_err "Could not find manifest from start output"
    exit 2
fi
log "Using manifest: $LOCAL_DEMO_MANIFEST"

# Source PW env (includes LOCAL_DEMO_MANIFEST) so pw-cli calls + manifest work
eval "$("$BASH_BIN" "$LOCAL_DEMO" env)"

# Read all ports from the manifest and export for conftest.py.
# _read_manifest_port uses LOCAL_DEMO_MANIFEST (set by eval above).
export LOCAL_DEMO_URL="http://localhost:$(_read_manifest_port webui 8080)"
export GM_PORT=$(_read_manifest_port gm 4002)
export SIGGEN_PORT=$(_read_manifest_port siggen 4001)
export LEVEL_SW_PORT=$(_read_manifest_port level_sw 9100)
export LEVEL_HW_OUT_PORT=$(_read_manifest_port level_hw_out 9101)
export PCM_PORT=$(_read_manifest_port pcm 9090)

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
cd "$REPO_DIR/src/web-ui"
"$E2E_PYTHON" -m pytest tests/e2e/ -v --tb=short "$@"
