#!/usr/bin/env bash
# Wrapper script for playwright-mcp — launches the MCP server with Nix-managed
# Chromium browsers in headless mode. Used by Claude Code's MCP integration
# (US-109) so QE agents can drive a browser for exploratory testing.
#
# Usage (via MCP config in .claude/settings.json):
#   { "command": "./scripts/playwright-mcp.sh" }
#
# Or manually:
#   ./scripts/playwright-mcp.sh

set -euo pipefail

export PLAYWRIGHT_BROWSERS_PATH=$(nix eval --raw nixpkgs#playwright-driver.browsers.outPath 2>/dev/null) || {
    echo "ERROR: Cannot resolve playwright browsers. Ensure nix is available." >&2
    exit 1
}
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

exec nix run nixpkgs#playwright-mcp -- \
    --headless \
    --viewport-size "1280x720" \
    "$@"
