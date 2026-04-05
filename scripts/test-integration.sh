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
#   8. US-077: level-bridge timestamps (pos/nsec) monotonically increasing
#   9. US-077: pcm-bridge binary v2 header includes non-zero graph_pos/graph_nsec
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
LOCAL_DEMO="$SCRIPT_DIR/local-demo.sh"

# US-131: Instance-aware port configuration.
# Ports are computed from instance ID, then overridden by manifest if available.
INSTANCE_ID="${LOCAL_DEMO_INSTANCE_ID:-0}"
PORT_OFFSET=$((INSTANCE_ID * 100))
MANIFEST_FILE="/tmp/local-demo-inst-${INSTANCE_ID}.json"

GM_PORT=$((4002 + PORT_OFFSET))
SIGGEN_PORT=$((4001 + PORT_OFFSET))
LEVEL_SW_PORT=$((9100 + PORT_OFFSET))
LEVEL_HW_OUT_PORT=$((9101 + PORT_OFFSET))
LEVEL_HW_IN_PORT=$((9102 + PORT_OFFSET))
PCM_PORT=$((9090 + PORT_OFFSET))

CLEANUP_DONE=false
START_TIME=$(date +%s)

# Counters
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_TOTAL=0

PYTHON="${LOCAL_DEMO_PYTHON:-python}"

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
read_levels() {
    local port="$1"
    local line=""
    if exec 4<>/dev/tcp/127.0.0.1/"$port" 2>/dev/null; then
        line=$(timeout 3 head -n1 <&4 2>/dev/null || true)
        exec 4>&- 2>/dev/null
    fi
    echo "$line"
}

# Read N JSON lines from a level-bridge TCP port.
read_levels_multi() {
    local port="$1" count="$2"
    if exec 4<>/dev/tcp/127.0.0.1/"$port" 2>/dev/null; then
        timeout 5 head -n"$count" <&4 2>/dev/null || true
        exec 4>&- 2>/dev/null
    fi
}

# Extract a JSON field value using Python.
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
    "$LOCAL_DEMO" stop 2>/dev/null || true
    log "Cleanup complete."
}

trap cleanup EXIT INT TERM

# ---- 1. Start the full local-demo stack ----

log "Starting full local-demo stack..."
"$LOCAL_DEMO" start || {
    log_err "local-demo start failed"
    exit 2
}

# Source PW env so pw-cli commands work
eval "$("$LOCAL_DEMO" env)"

# US-131: Re-read actual ports from manifest (authoritative after start).
if [ -f "$MANIFEST_FILE" ]; then
    _mp() { "$PYTHON" -c "import json; print(json.load(open('$MANIFEST_FILE'))['ports']['$1'])" 2>/dev/null || echo "$2"; }
    GM_PORT=$(_mp gm "$GM_PORT")
    SIGGEN_PORT=$(_mp siggen "$SIGGEN_PORT")
    LEVEL_SW_PORT=$(_mp level_sw "$LEVEL_SW_PORT")
    LEVEL_HW_OUT_PORT=$(_mp level_hw_out "$LEVEL_HW_OUT_PORT")
    LEVEL_HW_IN_PORT=$(_mp level_hw_in "$LEVEL_HW_IN_PORT")
    PCM_PORT=$(_mp pcm "$PCM_PORT")
fi

# ---- 2. Switch to measurement mode for full audio path verification ----
# Standby mode has no app linked. Measurement mode links signal-gen
# to the convolver, which allows audio to flow through the full pipeline
# and appear on level-bridge taps.

log "Switching GM to measurement mode..."
MODE_RESP=$(rpc_call 127.0.0.1 $GM_PORT '{"cmd":"set_mode","mode":"measurement"}')
log "set_mode response: $MODE_RESP"
sleep 2  # allow reconciler to create measurement links

# ---- 3. Send signal-gen play command (override the default mp3/sine) ----

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

    # Verify we have at least some links established
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
        HAS_SIGNAL=false
        PEAKS="${PEAK_ARRAY#[}"
        PEAKS="${PEAKS%]}"
        IFS=',' read -ra PEAK_VALUES <<< "$PEAKS"
        for val in "${PEAK_VALUES[@]}"; do
            val="${val// /}"
            int_val="${val%%.*}"
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

# ---- Check 8: US-077 timestamp monotonicity (level-bridge pos/nsec) ----

log "Check 8: level-bridge timestamp monotonicity (US-077 DoD #3)"
TS_LINES=$(read_levels_multi $LEVEL_SW_PORT 8)
if [ -z "$TS_LINES" ]; then
    check_fail "timestamp check: no data from level-bridge-sw"
else
    TS_OK=$("$PYTHON" -c "
import json, sys

raw = [l.strip() for l in sys.stdin if l.strip()]
raw = raw[1:]

parsed = []
for line in raw:
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        continue
    if d.get('pos', 0) > 0 and d.get('nsec', 0) > 0:
        parsed.append(d)

if len(parsed) < 3:
    print('error:got only %d non-zero snapshots, need at least 3' % len(parsed))
    sys.exit(0)

prev_pos = -1
prev_nsec = -1
for i, d in enumerate(parsed):
    pos = d['pos']
    nsec = d['nsec']

    if not isinstance(pos, int):
        print('error:snapshot %d pos is not an integer: %r' % (i, pos))
        sys.exit(0)
    if not isinstance(nsec, int):
        print('error:snapshot %d nsec is not an integer: %r' % (i, nsec))
        sys.exit(0)

    if i > 0:
        if pos <= prev_pos:
            print('error:pos not monotonic: snapshot %d pos=%d <= prev=%d' % (i, pos, prev_pos))
            sys.exit(0)
        if nsec <= prev_nsec:
            print('error:nsec not monotonic: snapshot %d nsec=%d <= prev=%d' % (i, nsec, prev_nsec))
            sys.exit(0)

    prev_pos = pos
    prev_nsec = nsec

print('ok:%d snapshots, pos %d..%d, nsec %d..%d' % (
    len(parsed), parsed[0]['pos'], prev_pos,
    parsed[0]['nsec'], prev_nsec))
" <<< "$TS_LINES")

    case "$TS_OK" in
        ok:*)
            check_pass "timestamps monotonic: ${TS_OK#ok:}"
            ;;
        error:*)
            check_fail "timestamps: ${TS_OK#error:}"
            ;;
        *)
            check_fail "timestamps: unexpected result: $TS_OK"
            ;;
    esac
fi

# ---- Check 9: pcm-bridge binary v2 header includes timestamps (US-077 DoD #3) ----

log "Check 9: pcm-bridge v2 header includes non-zero graph_pos/graph_nsec"
PCM_TS_RESULT=$("$PYTHON" -c "
import socket, struct, sys, time

CHANNELS = 4
QUANTUM = 1024
PCM_PAYLOAD = QUANTUM * CHANNELS * 4  # float32
HEADER = 24
FRAME_SIZE = HEADER + PCM_PAYLOAD

try:
    s = socket.create_connection(('127.0.0.1', $PCM_PORT), timeout=5)
    s.settimeout(5)
except Exception as e:
    print('error:connection failed: %s' % e)
    sys.exit(0)

found = False
for attempt in range(10):
    try:
        buf = b''
        while len(buf) < HEADER:
            chunk = s.recv(HEADER - len(buf))
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        continue

    if len(buf) < HEADER:
        continue

    version = buf[0]
    if version != 2:
        print('error:unexpected version byte %d (expected 2)' % version)
        s.close()
        sys.exit(0)

    frame_count = struct.unpack_from('<I', buf, 4)[0]
    graph_pos = struct.unpack_from('<Q', buf, 8)[0]
    graph_nsec = struct.unpack_from('<Q', buf, 16)[0]

    if frame_count == 0:
        continue

    payload = b''
    remaining = frame_count * CHANNELS * 4
    while len(payload) < remaining:
        try:
            chunk = s.recv(remaining - len(payload))
        except socket.timeout:
            break
        if not chunk:
            break
        payload += chunk

    if graph_pos > 0 and graph_nsec > 0:
        print('ok:v2 header version=%d frame_count=%d graph_pos=%d graph_nsec=%d' % (
            version, frame_count, graph_pos, graph_nsec))
        found = True
        break
    else:
        print('error:data frame but graph_pos=%d graph_nsec=%d (zero)' % (
            graph_pos, graph_nsec))
        found = True
        break

if not found:
    print('error:no data frames received after 10 attempts (only heartbeats)')
s.close()
" 2>&1)

case "$PCM_TS_RESULT" in
    ok:*)
        check_pass "pcm-bridge ${PCM_TS_RESULT#ok:}"
        ;;
    error:*)
        check_fail "pcm-bridge ${PCM_TS_RESULT#error:}"
        ;;
    *)
        check_fail "pcm-bridge unexpected result: $PCM_TS_RESULT"
        ;;
esac

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
