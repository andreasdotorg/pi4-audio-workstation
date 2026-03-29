#!/usr/bin/env bash
# nixos-smoke-test.sh — Post-deployment smoke test for the Pi 4 Audio Workstation
#
# Verifies that the NixOS deployment is functional: PipeWire RT scheduling,
# convolver node, FIR files, custom services, and web UI. Run on the Pi
# after nixos-anywhere initial install or nixos-rebuild switch.
#
# Usage:
#   ssh root@<pi-ip> bash /path/to/nixos-smoke-test.sh
#   # or copy to Pi and run as the 'ela' user (most checks need ela's user services)
#
# Exit codes:
#   0 — all checks passed
#   1 — one or more checks failed
#
# T-072-13a (US-072: NixOS Build)

set -euo pipefail

PASS=0
FAIL=0
WARN=0

pass() { printf "  PASS  %s\n" "$1"; ((PASS++)); }
fail() { printf "  FAIL  %s\n" "$1"; ((FAIL++)); }
warn() { printf "  WARN  %s\n" "$1"; ((WARN++)); }

section() { printf "\n=== %s ===\n" "$1"; }

# ── 1. Kernel ──────────────────────────────────────────────────────────
section "Kernel"

if uname -r | grep -q "PREEMPT_RT\|rt"; then
    pass "PREEMPT_RT kernel: $(uname -r)"
else
    # Check /proc/version for RT indicator
    if grep -qi "PREEMPT_RT" /proc/version 2>/dev/null; then
        pass "PREEMPT_RT kernel (from /proc/version): $(uname -r)"
    else
        fail "Kernel is NOT PREEMPT_RT: $(uname -r)"
    fi
fi

# ── 2. PipeWire running ───────────────────────────────────────────────
section "PipeWire"

PW_PID=$(pgrep -u ela -x pipewire 2>/dev/null || true)
if [ -n "$PW_PID" ]; then
    pass "PipeWire running (PID $PW_PID)"
else
    fail "PipeWire not running for user ela"
fi

# ── 3. PipeWire RT scheduling (SCHED_FIFO 88) ─────────────────────────
if [ -n "$PW_PID" ]; then
    CHRT_OUT=$(chrt -p "$PW_PID" 2>/dev/null || true)
    if echo "$CHRT_OUT" | grep -q "SCHED_FIFO" && echo "$CHRT_OUT" | grep -q "priority: 88"; then
        pass "PipeWire at SCHED_FIFO priority 88"
    else
        fail "PipeWire scheduling: $CHRT_OUT (expected SCHED_FIFO/88)"
    fi
fi

# ── 4. WirePlumber running ────────────────────────────────────────────
WP_PID=$(pgrep -u ela -x wireplumber 2>/dev/null || true)
if [ -n "$WP_PID" ]; then
    pass "WirePlumber running (PID $WP_PID)"
else
    fail "WirePlumber not running for user ela"
fi

# ── 5. Convolver node loaded ──────────────────────────────────────────
section "Audio pipeline"

if sudo -u ela XDG_RUNTIME_DIR="/run/user/$(id -u ela)" pw-cli ls Node 2>/dev/null | grep -qi "convolver"; then
    pass "Convolver node present in PipeWire graph"
else
    fail "Convolver node NOT found in PipeWire graph"
fi

# ── 6. FIR coefficient files ──────────────────────────────────────────
COEFFS_DIR="/etc/pi4audio/coeffs"
EXPECTED_FILES=(
    "combined_left_hp.wav"
    "combined_right_hp.wav"
    "combined_sub1_lp.wav"
    "combined_sub2_lp.wav"
)

if [ -d "$COEFFS_DIR" ]; then
    pass "FIR coefficients directory exists: $COEFFS_DIR"
    for f in "${EXPECTED_FILES[@]}"; do
        if [ -f "$COEFFS_DIR/$f" ]; then
            pass "FIR file present: $f"
        else
            fail "FIR file missing: $COEFFS_DIR/$f"
        fi
    done
else
    fail "FIR coefficients directory missing: $COEFFS_DIR"
fi

# ── 7. Custom systemd user services ──────────────────────────────────
section "Systemd user services"

# Run systemctl as ela user
run_userctl() {
    sudo -u ela XDG_RUNTIME_DIR="/run/user/$(id -u ela)" systemctl --user "$@" 2>/dev/null
}

SERVICES=(
    "pipewire.service"
    "wireplumber.service"
    "pi4audio-graph-manager.service"
    "pi4audio-signal-gen.service"
    "pi4-audio-webui.service"
)

# pcm-bridge and level-bridge are instance-based
INSTANCE_SERVICES=(
    "pcm-bridge-monitor.service"
    "pcm-bridge-capture-usb.service"
    "level-bridge-sw.service"
    "level-bridge-hw-out.service"
    "level-bridge-hw-in.service"
)

for svc in "${SERVICES[@]}" "${INSTANCE_SERVICES[@]}"; do
    STATE=$(run_userctl is-active "$svc" || true)
    if [ "$STATE" = "active" ]; then
        pass "Service active: $svc"
    else
        fail "Service not active ($STATE): $svc"
    fi
done

# ── 8. GraphManager RPC ──────────────────────────────────────────────
section "Service health checks"

if curl -sf --max-time 5 http://127.0.0.1:4002/health >/dev/null 2>&1; then
    pass "GraphManager RPC responsive (port 4002)"
else
    fail "GraphManager RPC not responding on port 4002"
fi

# ── 9. signal-gen RPC ────────────────────────────────────────────────
if curl -sf --max-time 5 http://127.0.0.1:4001/health >/dev/null 2>&1; then
    pass "signal-gen RPC responsive (port 4001)"
else
    fail "signal-gen RPC not responding on port 4001"
fi

# ── 10. Level metering ports ─────────────────────────────────────────
for port in 9100 9101 9102; do
    if timeout 3 bash -c "echo '' > /dev/tcp/127.0.0.1/$port" 2>/dev/null; then
        pass "Level-bridge TCP responsive on port $port"
    else
        fail "Level-bridge TCP not responding on port $port"
    fi
done

# ── 11. Web UI ───────────────────────────────────────────────────────
if curl -skf --max-time 5 https://127.0.0.1:8080/ >/dev/null 2>&1; then
    pass "Web UI accessible (HTTPS port 8080)"
elif curl -sf --max-time 5 http://127.0.0.1:8080/ >/dev/null 2>&1; then
    pass "Web UI accessible (HTTP port 8080)"
else
    fail "Web UI not responding on port 8080"
fi

# ── 12. Firmware partition ───────────────────────────────────────────
section "Firmware"

if mountpoint -q /boot/firmware 2>/dev/null; then
    pass "Firmware partition mounted at /boot/firmware"
    if [ -f /boot/firmware/config.txt ]; then
        pass "config.txt present on firmware partition"
    else
        fail "config.txt missing from /boot/firmware"
    fi
    if [ -f /boot/firmware/u-boot-rpi4.bin ]; then
        pass "U-Boot binary present on firmware partition"
    else
        fail "u-boot-rpi4.bin missing from /boot/firmware"
    fi
else
    fail "Firmware partition not mounted at /boot/firmware"
fi

# ── 13. No xruns (quick check) ──────────────────────────────────────
section "Quick xrun check (10 seconds)"

if [ -n "$PW_PID" ]; then
    # Count xruns in PipeWire journal from the last 10 seconds
    XRUN_COUNT=$(journalctl --user -u pipewire.service --since "10 seconds ago" 2>/dev/null \
        | grep -ci "xrun" || true)
    if [ "$XRUN_COUNT" -eq 0 ]; then
        pass "No xruns in last 10 seconds"
    else
        warn "Found $XRUN_COUNT xrun(s) in last 10 seconds"
    fi
else
    warn "Skipping xrun check (PipeWire not running)"
fi

# ── Summary ──────────────────────────────────────────────────────────
section "Summary"
printf "  Passed: %d\n" "$PASS"
printf "  Failed: %d\n" "$FAIL"
printf "  Warnings: %d\n" "$WARN"

if [ "$FAIL" -gt 0 ]; then
    printf "\nSMOKE TEST FAILED (%d failure(s))\n" "$FAIL"
    exit 1
else
    printf "\nSMOKE TEST PASSED\n"
    exit 0
fi
