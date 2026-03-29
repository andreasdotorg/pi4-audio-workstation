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

# Resolve playwright browser path from Nix store.
# In nix develop, PLAYWRIGHT_BROWSERS_PATH is already set by shellHook.
# Outside nix develop, resolve it from nixpkgs.
if [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ]; then
    PLAYWRIGHT_BROWSERS_PATH=$(nix eval --raw nixpkgs#playwright-driver.browsers.outPath 2>/dev/null) || {
        echo "ERROR: Cannot resolve playwright browsers. Run from 'nix develop' or ensure nix is available." >&2
        exit 1
    }
fi

export PLAYWRIGHT_BROWSERS_PATH
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# Resolve mcp-server-playwright binary.
# In nix develop, it's on PATH. Outside, resolve from nixpkgs.
if ! command -v mcp-server-playwright &>/dev/null; then
    MCP_BIN=$(nix eval --raw nixpkgs#playwright-mcp.outPath 2>/dev/null)/bin/mcp-server-playwright || {
        echo "ERROR: Cannot resolve playwright-mcp. Run from 'nix develop' or ensure nix is available." >&2
        exit 1
    }
    if [ ! -x "$MCP_BIN" ]; then
        echo "Fetching playwright-mcp..."
        nix build --no-link nixpkgs#playwright-mcp 2>&1
    fi
else
    MCP_BIN=mcp-server-playwright
fi

exec "$MCP_BIN" \
    --headless \
    --viewport-size "1280x720" \
    "$@"
