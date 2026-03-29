#!/usr/bin/env python3
"""Capture headless browser screenshots of the mugge web UI dashboard.

US-077 DoD #2: Screenshot evidence of timestamp-driven meter rendering
with a steady-state 1 kHz sine signal.

Prerequisites:
  - Web UI running on http://localhost:8080 (e.g., via `nix run .#local-demo`)
  - Signal-gen playing a 1 kHz sine (local-demo does this automatically at 440 Hz;
    the test-integration script uses 1 kHz)
  - Playwright browsers available (set PLAYWRIGHT_BROWSERS_PATH)

Usage:
  # Via Nix (preferred — handles all deps):
  nix run .#capture-screenshot

  # Manual (if local-demo is already running):
  PLAYWRIGHT_BROWSERS_PATH=... python scripts/capture-ui-screenshot.py

Output:
  /tmp/mugge-screenshots/dashboard-meters.png
  /tmp/mugge-screenshots/dashboard-spectrum.png
"""

import os
import platform
import sys
import time
from pathlib import Path


def _find_full_chrome():
    """Return the full chrome binary path from PLAYWRIGHT_BROWSERS_PATH.

    On aarch64, headless_shell crashes (F-120). Use the full chrome binary.
    """
    browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if not browsers:
        return None
    browsers_dir = Path(browsers)
    if not browsers_dir.exists():
        return None
    for entry in sorted(browsers_dir.iterdir()):
        if entry.name.startswith("chromium-") and "headless" not in entry.name:
            chrome = entry / "chrome-linux" / "chrome"
            if chrome.exists():
                return str(chrome)
    return None


def main():
    url = os.environ.get("MUGGE_UI_URL", "http://localhost:8080")
    out_dir = Path(os.environ.get("MUGGE_SCREENSHOT_DIR", "/tmp/mugge-screenshots"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Import playwright here so the script fails clearly if not available.
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not available. Run via 'nix run .#capture-screenshot'.")
        sys.exit(1)

    print(f"[screenshot] Connecting to {url}")
    print(f"[screenshot] Output dir: {out_dir}")

    # F-120: On aarch64, headless_shell crashes. Use the full chrome binary.
    launch_args = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
        ],
    }
    if platform.machine() == "aarch64":
        chrome = _find_full_chrome()
        if chrome:
            print(f"[screenshot] aarch64: using full chrome at {chrome}")
            launch_args["executable_path"] = chrome

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_args)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            device_scale_factor=2,  # retina-quality screenshots
        )
        page = context.new_page()

        # Navigate to the dashboard (default tab).
        page.goto(url, timeout=15000)
        page.wait_for_load_state("networkidle")
        print("[screenshot] Page loaded.")

        # Wait for WebSocket connection indicator to turn green.
        # The connection dot (#conn-dot) gets class 'connected' when WS is up.
        try:
            page.wait_for_selector("#conn-dot.connected", timeout=10000)
            print("[screenshot] WebSocket connected.")
        except Exception:
            print("[screenshot] WARNING: WebSocket connection indicator not found. "
                  "Proceeding anyway.")

        # Wait for level data to appear in meters. The dashboard canvases
        # render at ~30Hz once data flows. Give it a few seconds to stabilize.
        print("[screenshot] Waiting 8s for meter + spectrum data to stabilize...")
        time.sleep(8)

        # Screenshot 1: Full dashboard view with meters.
        path_dashboard = out_dir / "dashboard-meters.png"
        page.screenshot(path=str(path_dashboard), full_page=False)
        print(f"[screenshot] Saved: {path_dashboard}")

        # Screenshot 2: Click on the spectrum area if visible, or just
        # capture the current view which should include the spectrum canvas.
        # The dashboard has both meters and spectrum in the default view.
        path_spectrum = out_dir / "dashboard-full.png"
        page.screenshot(path=str(path_spectrum), full_page=True)
        print(f"[screenshot] Saved: {path_spectrum}")

        context.close()
        browser.close()

    print(f"[screenshot] Done. Screenshots in {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
