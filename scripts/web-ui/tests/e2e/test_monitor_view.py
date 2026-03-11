"""Dashboard view tests for the D-020 Web UI.

Verifies the dense single-screen dashboard: health bar, level meter groups
(Main, PA Sends, Monitor Sends, Source), LUFS placeholder, SPL hero,
silent channel dimming, and WebSocket data flow.

Stage 1 scope: meters + health bar + LUFS placeholder panel + SPL hero.
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


def test_health_bar_cpu_gauge_updates(page):
    """CPU gauge in health bar updates from '--' within 3 s."""
    cpu_text = page.locator("#hb-cpu-gauge-text")
    expect(cpu_text).not_to_have_text("--", timeout=3000)


def test_health_bar_mem_gauge_updates(page):
    """Memory gauge in health bar updates from '--' within 3 s."""
    mem_text = page.locator("#hb-mem-gauge-text")
    expect(mem_text).not_to_have_text("--", timeout=3000)


def test_health_bar_temp_gauge_updates(page):
    """Temperature gauge in health bar updates from '--' within 3 s."""
    temp_text = page.locator("#hb-temp-gauge-text")
    expect(temp_text).not_to_have_text("--", timeout=3000)


def test_health_bar_dsp_load_gauge_updates(page):
    """DSP Load gauge in health bar updates from '--' within 3 s."""
    load_text = page.locator("#hb-dsp-load-gauge-text")
    expect(load_text).not_to_have_text("--", timeout=3000)


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

def test_main_meters_present(page):
    """MAIN meter group has 2 canvas elements (ML, MR)."""
    canvases = page.locator("#meters-main canvas")
    expect(canvases).to_have_count(2)


def test_source_meters_present(page):
    """SOURCE meter group has 6 canvas elements (Src3-Src8)."""
    canvases = page.locator("#meters-source canvas")
    expect(canvases).to_have_count(6)


def test_source_group_always_visible(page):
    """SOURCE group is always visible (no auto-hide)."""
    group = page.locator("#group-source")
    expect(group).to_be_visible()


def test_pa_meters_present(page):
    """PA Sends meter group has 4 canvas elements."""
    canvases = page.locator("#meters-pa canvas")
    expect(canvases).to_have_count(4)


def test_monitor_meters_present(page):
    """Monitor Sends meter group has 4 canvas elements."""
    canvases = page.locator("#meters-monitor canvas")
    expect(canvases).to_have_count(4)


def test_main_group_label(page):
    """MAIN group has the 'MAIN' label."""
    label = page.locator(".meter-group-label-main")
    expect(label).to_be_visible()
    expect(label).to_have_text("MAIN")


def test_source_group_label(page):
    """SOURCE group has the 'SOURCE' label."""
    label = page.locator(".meter-group-label-source")
    expect(label).to_have_count(1)
    expect(label).to_have_text("SOURCE")


def test_pa_group_label(page):
    """PA Sends group has the 'PA SENDS' label."""
    label = page.locator("#group-pa .meter-group-label")
    expect(label).to_have_text("PA SENDS")


def test_monitor_group_label(page):
    """Monitor Sends group has the 'MONITOR SENDS' label."""
    label = page.locator("#group-monitor .meter-group-label")
    expect(label).to_have_text("MONITOR SENDS")


def test_channel_labels_main(page):
    """MAIN group has ML and MR labels."""
    labels = page.locator("#meters-main .meter-label")
    expect(labels.first).to_have_text("ML")


def test_channel_labels_pa(page):
    """PA Sends group has SatL as first label (satellite speakers)."""
    labels = page.locator("#meters-pa .meter-label")
    expect(labels.first).to_have_text("SatL")


def test_channel_labels_monitor(page):
    """Monitor Sends group has abbreviated channel labels."""
    labels = page.locator("#meters-monitor .meter-label")
    expect(labels.first).to_have_text("EL")


# -- Silent channel dimming --

def test_no_signal_overlay_exists(page):
    """Each meter channel has a 'NO SIG' overlay element."""
    # Check MAIN group (2 channels) + SOURCE (6) + PA (4) + MONITOR (4) = 16
    overlays = page.locator(".meter-no-signal")
    expect(overlays).to_have_count(16)


def test_no_signal_overlay_hidden_by_default(page):
    """NO SIG overlays are hidden by default (not visible until .silent class)."""
    # The .meter-no-signal has display:none by default
    overlay = page.locator("#meters-main .meter-no-signal").first
    expect(overlay).not_to_be_visible()


def test_meters_not_silent_initially(page):
    """Meter channels should not have .silent class on initial load."""
    page.wait_for_timeout(1000)  # Wait 1s, well under 5s threshold
    silent = page.locator(".meter-channel.silent")
    expect(silent).to_have_count(0)


# -- SPL hero --

def test_spl_hero_visible(page):
    """The SPL hero display is visible in the right panel."""
    spl = page.locator(".spl-hero")
    expect(spl).to_be_visible()


def test_spl_hero_label(page):
    """SPL hero has the 'SPL' label."""
    label = page.locator(".spl-hero-label")
    expect(label).to_have_text("SPL")


def test_spl_hero_placeholder(page):
    """SPL hero shows '--' placeholder when no data."""
    value = page.locator("#spl-value")
    expect(value).to_have_text("--")


def test_spl_health_bar_element(page):
    """SPL element exists in the health bar."""
    spl = page.locator("#hb-spl")
    expect(spl).to_have_count(1)


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

def test_main_db_readout_updates(page):
    """MAIN meter dB readout updates from '-inf' within 3 s."""
    db_readout = page.locator("#meters-main-db-0")
    expect(db_readout).not_to_have_text("-inf", timeout=3000)


def test_pa_db_readout_updates(page):
    """PA meter dB readout updates from '-inf' within 3 s."""
    db_readout = page.locator("#meters-pa-db-0")
    expect(db_readout).not_to_have_text("-inf", timeout=3000)
