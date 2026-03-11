"""Dashboard view tests for the D-020 Web UI.

Verifies the dense single-screen dashboard: health bar, level meter groups
(Capture, PA Sends, Monitor Sends), LUFS placeholder, and WebSocket data flow.

Stage 1 scope: meters + health bar + LUFS placeholder panel only.
"""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


# -- Health bar --

def test_health_bar_visible(page):
    """The health bar is visible in the dashboard."""
    health_bar = page.locator(".health-bar")
    expect(health_bar).to_be_visible()


def test_health_bar_dsp_state_updates(page):
    """DSP state in health bar updates from '--' within 3 s."""
    dsp_state = page.locator("#hb-dsp-state")
    expect(dsp_state).not_to_have_text("--", timeout=3000)


def test_health_bar_cpu_updates(page):
    """CPU percentage in health bar updates from '--' within 3 s."""
    cpu = page.locator("#hb-cpu")
    expect(cpu).not_to_have_text("--", timeout=3000)


def test_health_bar_mem_updates(page):
    """Memory in health bar updates from '--' within 3 s."""
    mem = page.locator("#hb-mem")
    expect(mem).not_to_have_text("--", timeout=3000)


# -- Nav bar indicators --

def test_mode_badge_visible(page):
    """The mode badge is visible in the nav bar."""
    badge = page.locator("#mode-badge")
    expect(badge).to_be_visible()


def test_mode_badge_updates(page):
    """Mode badge updates from '--' within 3 s."""
    badge = page.locator("#mode-badge")
    expect(badge).not_to_have_text("--", timeout=3000)


def test_nav_temp_updates(page):
    """Nav bar temperature updates from '--' within 3 s."""
    temp = page.locator("#nav-temp")
    expect(temp).not_to_have_text("--", timeout=3000)


# -- Meter groups --

def test_capture_meters_present(page):
    """Capture meter group has canvas elements."""
    canvases = page.locator("#meters-capture canvas")
    # 8 capture channels
    expect(canvases).to_have_count(8)


def test_pa_meters_present(page):
    """PA Sends meter group has 4 canvas elements."""
    canvases = page.locator("#meters-pa canvas")
    expect(canvases).to_have_count(4)


def test_monitor_meters_present(page):
    """Monitor Sends meter group has 4 canvas elements."""
    canvases = page.locator("#meters-monitor canvas")
    expect(canvases).to_have_count(4)


def test_capture_group_label(page):
    """Capture group has the 'CAPTURE' label."""
    label = page.locator(".meter-group-label-capture")
    expect(label).to_be_visible()
    expect(label).to_have_text("CAPTURE")


def test_pa_group_label(page):
    """PA Sends group has the 'PA SENDS' label."""
    label = page.locator("#group-pa .meter-group-label")
    expect(label).to_have_text("PA SENDS")


def test_monitor_group_label(page):
    """Monitor Sends group has the 'MONITOR SENDS' label."""
    label = page.locator("#group-monitor .meter-group-label")
    expect(label).to_have_text("MONITOR SENDS")


def test_channel_labels_capture(page):
    """Capture group has abbreviated channel labels."""
    labels = page.locator("#meters-capture .meter-label")
    expect(labels.first).to_have_text("InL")


def test_channel_labels_pa(page):
    """PA Sends group has abbreviated channel labels."""
    labels = page.locator("#meters-pa .meter-label")
    expect(labels.first).to_have_text("ML")


def test_channel_labels_monitor(page):
    """Monitor Sends group has abbreviated channel labels."""
    labels = page.locator("#meters-monitor .meter-label")
    expect(labels.first).to_have_text("EL")


# -- LUFS placeholder --

def test_lufs_panel_visible(page):
    """The LUFS panel placeholder is visible."""
    lufs = page.locator(".lufs-panel")
    expect(lufs).to_be_visible()


def test_lufs_shows_placeholder(page):
    """LUFS values show '--' placeholder."""
    short_term = page.locator("#lufs-short")
    expect(short_term).to_have_text("--")


# -- Meter dB readout updates --

def test_capture_db_readout_updates(page):
    """Capture meter dB readout updates from '-inf' within 3 s."""
    db_readout = page.locator("#meters-capture-db-0")
    expect(db_readout).not_to_have_text("-inf", timeout=3000)


def test_pa_db_readout_updates(page):
    """PA meter dB readout updates from '-inf' within 3 s."""
    db_readout = page.locator("#meters-pa-db-0")
    expect(db_readout).not_to_have_text("-inf", timeout=3000)
