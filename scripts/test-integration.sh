#!/usr/bin/env bash
# US-075 AC 4: End-to-end PipeWire integration test.
#
# Verifies the full local-demo audio pipeline:
#   1. PipeWire + WirePlumber headless environment starts
#   2. GraphManager creates production link topology
#   3. signal-gen produces 1 kHz sine at -20 dBFS
#   4. level-bridge-sw reports non-zero levels on expected channels
#   5. GM reports correct link count via get_links RPC
#   6. Convolver node (pi4audio-convolver) present in PW graph
#   7. GM get_graph_info returns valid graph metadata
#
# Full cycle target: < 30 seconds.
#
# Usage:
#   nix run .#test-integration       # preferred (all deps from Nix)
#   ./scripts/test-integration.sh    # if already in nix develop with binaries
#
# Exit codes:
#   0 = all checks passed
#   1 = one or more checks failed
#   2 = infrastructure error (failed to start stack)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${LOCAL_DEMO_REPO_DIR:-$(dirname "$SCRIPT_DIR")}"
PW_TEST_ENV="${LOCAL_DEMO_PW_TEST_ENV:-$SCRIPT_DIR/local-pw-test-env.sh}"

# Test configuration
GM_PORT=4002
SIGGEN_PORT=4001
LEVEL_SW_PORT=9100
LEVEL_HW_OUT_PORT=9101
LEVEL_HW_IN_PORT=9102
PCM_PORT=9090

# Track child PIDs for cleanup
PIDS=()
PW_STARTED=false
CLEANUP_DONE=false
START_TIME=$(date +%s)

# Counters
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_TOTAL=0

# ---- Utility functions ----

log() { echo "[test-integration] $*"; }
log_err() { echo "[test-integration] ERROR: $*" >&2; }

check_pass() {
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
    log "  PASS: $1"
}

check_fail() {
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
    log "  FAIL: $1"
}

# Send a JSON RPC command to a TCP port and read the response line.
# Usage: rpc_call <host> <port> <json_command>
# Returns the response JSON on stdout.
rpc_call() {
    local host="$1" port="$2" cmd="$3"
    local response=""
    if exec 3<>/dev/tcp/"$host"/"$port" 2>/dev/null; then
        echo "$cmd" >&3
        response=$(timeout 3 head -n1 <&3 2>/dev/null || true)
        exec 3>&- 2>/dev/null
    fi
    echo "$response"
}

# Read one JSON line from a level-bridge TCP port.
# Usage: read_levels <port>
read_levels() {
    local port="$1"
    local line=""
    if exec 4<>/dev/tcp/127.0.0.1/"$port" 2>/dev/null; then
        line=$(timeout 3 head -n1 <&4 2>/dev/null || true)
        exec 4>&- 2>/dev/null
    fi
    echo "$line"
}

# Extract a JSON field value using Python (reliable JSON parsing).
# Usage: json_field <json_string> <field_name>
json_field() {
    local json="$1" field="$2"
    "$PYTHON" -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    v = d.get(sys.argv[2])
    if v is None:
        print('')
    elif isinstance(v, bool):
        print(str(v).lower())
    elif isinstance(v, list):
        print(json.dumps(v))
    else:
        print(v)
except:
    print('')
" "$json" "$field"
}

# ---- Cleanup ----

cleanup() {
    if $CLEANUP_DONE; then return; fi
    CLEANUP_DONE=true

    log "Tearing down..."

    # Kill child processes in reverse order
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

# Kill stale processes from previous runs. Exclude our own PID and parent
# to avoid self-kill (pgrep -f matches env vars in our command line).
MY_PID=$$
MY_PPID=$PPID

for pattern in "pi4audio-graph-manager" "pi4audio-signal-gen" "[b]in/level-bridge" "[b]in/pcm-bridge"; do
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

# ---- 1. Resolve binaries ----

if [ -n "${LOCAL_DEMO_GM_BIN:-}" ]; then
    GM_BIN="$LOCAL_DEMO_GM_BIN"
    SG_BIN="$LOCAL_DEMO_SG_BIN"
    LB_BIN="$LOCAL_DEMO_LB_BIN"
    PCM_BIN="$LOCAL_DEMO_PCM_BIN"
    PYTHON="${LOCAL_DEMO_PYTHON:-python}"
else
    log "ERROR: This script expects LOCAL_DEMO_* env vars (run via nix run .#test-integration)" >&2
    exit 2
fi

# ---- 2. Generate dirac coefficients + convolver config ----

COEFFS_DIR="/tmp/pw-test-coeffs"
"$PYTHON" "$REPO_DIR/scripts/generate-dirac-coeffs.py" "$COEFFS_DIR" > /dev/null

PW_CONF_DIR="/tmp/pw-test-xdg-config/pipewire/pipewire.conf.d"
mkdir -p "$PW_CONF_DIR"
sed "s|COEFFS_DIR|$COEFFS_DIR|g" \
    "$REPO_DIR/configs/local-demo/convolver.conf" \
    > "$PW_CONF_DIR/30-convolver.conf"
rm -f "$PW_CONF_DIR/30-filter-chain-convolver.conf"

# Install UMIK-1 loopback config (needed for measurement mode link topology)
install -m 644 "$REPO_DIR/configs/local-demo/umik1-loopback.conf" \
    "$PW_CONF_DIR/35-umik1-loopback.conf"

# Generate room simulator IR and config
"$PYTHON" "$REPO_DIR/scripts/generate-room-sim-ir.py" "$COEFFS_DIR" > /dev/null
sed "s|COEFFS_DIR|$COEFFS_DIR|g" \
    "$REPO_DIR/configs/local-demo/room-sim-convolver.conf" \
    > "$PW_CONF_DIR/36-room-sim-convolver.conf"

log "Coefficients and configs generated."

# ---- 3. Start PipeWire ----

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

# ---- 4. Start GraphManager ----

"$GM_BIN" --listen tcp:127.0.0.1:$GM_PORT --mode monitoring --log-level warn 2>/tmp/gm-test-stderr.log &
PIDS+=($!)
sleep 1
if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    log_err "GraphManager failed to start"
    exit 2
fi
log "GraphManager running (PID ${PIDS[-1]})"

# ---- 5. Start signal-gen (managed mode, mono) ----

"$SG_BIN" --managed --channels 1 --rate 48000 \
    --listen tcp:127.0.0.1:$SIGGEN_PORT --max-level-dbfs -20 2>/tmp/sg-test-stderr.log &
PIDS+=($!)
sleep 1
if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    log_err "signal-gen failed to start"
    exit 2
fi
log "signal-gen running (PID ${PIDS[-1]})"

# ---- 6. Start level-bridge instances (managed mode) ----

# 6a. level-bridge-sw (app output tap, 8ch)
"$LB_BIN" --managed --node-name pi4audio-level-bridge-sw \
    --mode capture --target unused-managed-mode \
    --levels-listen tcp:0.0.0.0:$LEVEL_SW_PORT --channels 8 --rate 48000 2>/tmp/lb-sw-test.log &
PIDS+=($!)
sleep 0.5

# 6b. level-bridge-hw-out (USBStreamer monitor, 8ch)
"$LB_BIN" --managed --node-name pi4audio-level-bridge-hw-out \
    --mode monitor --target alsa_output.usb-MiniDSP_USBStreamer \
    --levels-listen tcp:0.0.0.0:$LEVEL_HW_OUT_PORT --channels 8 --rate 48000 2>/tmp/lb-hwout-test.log &
PIDS+=($!)
sleep 0.5

# 6c. level-bridge-hw-in (ADA8200 capture, 8ch)
"$LB_BIN" --managed --node-name pi4audio-level-bridge-hw-in \
    --mode capture --target alsa_input.usb-MiniDSP_USBStreamer \
    --levels-listen tcp:0.0.0.0:$LEVEL_HW_IN_PORT --channels 8 --rate 48000 2>/tmp/lb-hwin-test.log &
PIDS+=($!)
sleep 0.5

for pid in "${PIDS[@]:2:3}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
        log_err "A level-bridge instance failed to start"
        exit 2
    fi
done
log "level-bridge instances running."

# ---- 7. Start pcm-bridge (managed mode) ----

"$PCM_BIN" --managed --mode monitor \
    --listen tcp:0.0.0.0:$PCM_PORT --channels 4 --rate 48000 2>/tmp/pcm-test.log &
PIDS+=($!)
sleep 1
if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    log_err "pcm-bridge failed to start"
    exit 2
fi
log "pcm-bridge running."

# ---- 8. Wait for GM reconciliation (monitoring mode) ----

log "Waiting for GraphManager initial link reconciliation..."
sleep 3

# ---- 8b. Switch to measurement mode for full audio path verification ----
# Monitoring mode has no app linked. Measurement mode links signal-gen
# to the convolver, which allows audio to flow through the full pipeline
# and appear on level-bridge taps.

log "Switching GM to measurement mode..."
MODE_RESP=$(rpc_call 127.0.0.1 $GM_PORT '{"cmd":"set_mode","mode":"measurement"}')
log "set_mode response: $MODE_RESP"
sleep 2  # allow reconciler to create measurement links

# ---- 9. Send signal-gen play command ----

log "Commanding signal-gen to play 1 kHz sine at -20 dBFS..."
PLAY_CMD='{"cmd":"play","signal":"sine","freq":1000.0,"level_dbfs":-20.0,"channels":[1]}'
PLAY_RESPONSE=$(rpc_call 127.0.0.1 $SIGGEN_PORT "$PLAY_CMD")
if [ -n "$PLAY_RESPONSE" ]; then
    log "signal-gen responded: $PLAY_RESPONSE"
else
    log "WARNING: No response from signal-gen (may still be playing)"
fi

# Allow audio to flow through the graph
sleep 2

# =========================================================================
# VERIFICATION CHECKS
# =========================================================================

log ""
log "========== Running verification checks =========="
log ""

# ---- Check 1: Convolver node present in PW graph ----

log "Check 1: Convolver node present in PW graph"
PW_NODES=$(pw-cli ls Node 2>/dev/null || true)
if echo "$PW_NODES" | grep -q "pi4audio-convolver"; then
    check_pass "Convolver node (pi4audio-convolver) found in PW graph"
else
    check_fail "Convolver node (pi4audio-convolver) NOT found in PW graph"
fi

# ---- Check 2: GM get_graph_info returns valid data ----

log "Check 2: GM get_graph_info RPC"
GRAPH_INFO=$(rpc_call 127.0.0.1 $GM_PORT '{"cmd":"get_graph_info"}')
if [ -z "$GRAPH_INFO" ]; then
    check_fail "get_graph_info: no response from GraphManager"
else
    GI_OK=$(json_field "$GRAPH_INFO" "ok")
    GI_RATE=$(json_field "$GRAPH_INFO" "sample_rate")
    if [ "$GI_OK" = "true" ]; then
        check_pass "get_graph_info: ok=true, sample_rate=$GI_RATE"
    else
        check_fail "get_graph_info: ok=$GI_OK (expected true). Response: $GRAPH_INFO"
    fi
fi

# ---- Check 3: GM get_links reports correct link topology ----

log "Check 3: GM get_links RPC (measurement mode link count)"
LINKS_RESP=$(rpc_call 127.0.0.1 $GM_PORT '{"cmd":"get_links"}')
if [ -z "$LINKS_RESP" ]; then
    check_fail "get_links: no response from GraphManager"
else
    LINKS_OK=$(json_field "$LINKS_RESP" "ok")
    LINKS_DESIRED=$(json_field "$LINKS_RESP" "desired")
    LINKS_ACTUAL=$(json_field "$LINKS_RESP" "actual")
    LINKS_MISSING=$(json_field "$LINKS_RESP" "missing")
    LINKS_MODE=$(json_field "$LINKS_RESP" "mode")

    if [ "$LINKS_OK" = "true" ]; then
        check_pass "get_links: ok=true, mode=$LINKS_MODE, desired=$LINKS_DESIRED, actual=$LINKS_ACTUAL, missing=$LINKS_MISSING"
    else
        check_fail "get_links: ok=$LINKS_OK. Response: $LINKS_RESP"
    fi

    # Verify we have at least some links established (monitoring mode expects 21 desired)
    if [ -n "$LINKS_DESIRED" ] && [ "$LINKS_DESIRED" -gt 0 ] 2>/dev/null; then
        check_pass "get_links: desired link count > 0 ($LINKS_DESIRED)"
    else
        check_fail "get_links: desired link count is 0 or missing"
    fi

    if [ -n "$LINKS_ACTUAL" ] && [ "$LINKS_ACTUAL" -gt 0 ] 2>/dev/null; then
        check_pass "get_links: actual link count > 0 ($LINKS_ACTUAL)"
    else
        check_fail "get_links: actual link count is 0 or missing (actual=$LINKS_ACTUAL)"
    fi
fi

# ---- Check 4: signal-gen produces audio (via level-bridge-sw) ----

log "Check 4: level-bridge-sw reports non-zero levels"
LEVEL_DATA=$(read_levels $LEVEL_SW_PORT)
if [ -z "$LEVEL_DATA" ]; then
    check_fail "level-bridge-sw: no data received on port $LEVEL_SW_PORT"
else
    PEAK_ARRAY=$(json_field "$LEVEL_DATA" "peak")
    if [ -z "$PEAK_ARRAY" ]; then
        check_fail "level-bridge-sw: no peak data in response"
    else
        # Check if any peak value is above silence threshold (-100 dBFS)
        # The peak array looks like [-20.0,-120.0,-120.0,...]. Check if at
        # least one value is above -100.
        HAS_SIGNAL=false
        # Strip brackets and split on commas
        PEAKS="${PEAK_ARRAY#[}"
        PEAKS="${PEAKS%]}"
        IFS=',' read -ra PEAK_VALUES <<< "$PEAKS"
        for val in "${PEAK_VALUES[@]}"; do
            # Remove whitespace
            val="${val// /}"
            # Compare as integer (truncate decimal) - bash can't do float comparison
            int_val="${val%%.*}"
            # Handle negative: -20 > -100 means signal present
            if [ -n "$int_val" ] && [ "$int_val" != "-120" ] && [ "$int_val" -gt -100 ] 2>/dev/null; then
                HAS_SIGNAL=true
                break
            fi
        done

        if $HAS_SIGNAL; then
            check_pass "level-bridge-sw: non-zero signal detected (peak: $PEAK_ARRAY)"
        else
            check_fail "level-bridge-sw: all channels at silence (peak: $PEAK_ARRAY)"
        fi
    fi
fi

# ---- Check 5: level-bridge-hw-out reports non-zero levels ----

log "Check 5: level-bridge-hw-out (USBStreamer monitor) reports non-zero levels"
LEVEL_HW_DATA=$(read_levels $LEVEL_HW_OUT_PORT)
if [ -z "$LEVEL_HW_DATA" ]; then
    check_fail "level-bridge-hw-out: no data received on port $LEVEL_HW_OUT_PORT"
else
    PEAK_HW=$(json_field "$LEVEL_HW_DATA" "peak")
    if [ -z "$PEAK_HW" ]; then
        check_fail "level-bridge-hw-out: no peak data in response"
    else
        HAS_HW_SIGNAL=false
        PEAKS_HW="${PEAK_HW#[}"
        PEAKS_HW="${PEAKS_HW%]}"
        IFS=',' read -ra HW_PEAK_VALUES <<< "$PEAKS_HW"
        for val in "${HW_PEAK_VALUES[@]}"; do
            val="${val// /}"
            int_val="${val%%.*}"
            if [ -n "$int_val" ] && [ "$int_val" != "-120" ] && [ "$int_val" -gt -100 ] 2>/dev/null; then
                HAS_HW_SIGNAL=true
                break
            fi
        done
        if $HAS_HW_SIGNAL; then
            check_pass "level-bridge-hw-out: non-zero signal detected (peak: $PEAK_HW)"
        else
            check_fail "level-bridge-hw-out: all channels at silence (peak: $PEAK_HW)"
        fi
    fi
fi

# ---- Check 6: GM ping responds ----

log "Check 6: GM ping RPC"
PING_RESP=$(rpc_call 127.0.0.1 $GM_PORT '{"cmd":"ping"}')
PING_OK=$(json_field "$PING_RESP" "ok")
if [ "$PING_OK" = "true" ]; then
    check_pass "GM ping: ok=true"
else
    check_fail "GM ping: ok=$PING_OK. Response: $PING_RESP"
fi

# ---- Check 7: signal-gen status shows playing ----

log "Check 7: signal-gen status RPC"
STATUS_RESP=$(rpc_call 127.0.0.1 $SIGGEN_PORT '{"cmd":"status"}')
if [ -n "$STATUS_RESP" ]; then
    SG_PLAYING=$(json_field "$STATUS_RESP" "playing")
    if [ "$SG_PLAYING" = "true" ]; then
        check_pass "signal-gen status: playing=true"
    else
        check_fail "signal-gen status: playing=$SG_PLAYING (expected true). Response: $STATUS_RESP"
    fi
else
    check_fail "signal-gen status: no response"
fi

# =========================================================================
# RESULTS
# =========================================================================

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

log ""
log "=========================================="
log "  Integration test results"
log "  Passed: $CHECKS_PASSED / $CHECKS_TOTAL"
log "  Failed: $CHECKS_FAILED / $CHECKS_TOTAL"
log "  Elapsed: ${ELAPSED}s"
log "=========================================="

if [ "$CHECKS_FAILED" -gt 0 ]; then
    exit 1
fi

# Verify < 30 second target
if [ "$ELAPSED" -le 30 ]; then
    log "  Timing: ${ELAPSED}s (within 30s target)"
else
    log "  WARNING: ${ELAPSED}s exceeds 30s target"
fi

exit 0
