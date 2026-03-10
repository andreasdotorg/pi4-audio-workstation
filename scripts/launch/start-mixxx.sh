#!/bin/bash
#
# start-mixxx.sh — Launch Mixxx through PipeWire's JACK bridge
#
# Verifies the PipeWire JACK bridge is ready before launching Mixxx.
# If the bridge is not ready after retries, exits with an error rather
# than allowing Mixxx to silently fall back to ALSA (see F-021, D-026).
#
# Pi destination: /home/ela/bin/start-mixxx (chmod +x)

set -euo pipefail

MAX_RETRIES=10
RETRY_INTERVAL=1

# Ensure XDG_RUNTIME_DIR is set (required when launched via SSH or early boot)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# --- PipeWire JACK bridge readiness probe (D-026) ---

attempt=0
while [ "$attempt" -lt "$MAX_RETRIES" ]; do
    if pw-jack jack_lsp > /dev/null 2>&1; then
        echo "JACK bridge ready, launching Mixxx"
        exec pw-jack mixxx "$@"
    fi
    attempt=$((attempt + 1))
    echo "Waiting for PipeWire JACK bridge (attempt ${attempt}/${MAX_RETRIES})..."
    sleep "$RETRY_INTERVAL"
done

echo "ERROR: PipeWire JACK bridge not ready after ${MAX_RETRIES} attempts. Aborting." >&2
echo "Check that PipeWire is running: systemctl --user status pipewire" >&2
exit 1
