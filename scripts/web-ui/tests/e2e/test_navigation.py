"""Navigation tests for the D-020 Web UI.

Verifies that all four tabs are visible, clickable, and switch views correctly.
"""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

_ACTIVE_RE = re.compile(r".*\bactive\b.*")
_NOT_ACTIVE_RE = re.compile(r"^(?!.*\bactive\b).*$")


def test_all_tabs_visible(page):
    """All four navigation tabs (Monitor, Measure, System, MIDI) are visible."""
    for label in ("Monitor", "Measure", "System", "MIDI"):
        tab = page.locator(f'.nav-tab[data-view="{label.lower()}"]')
        expect(tab).to_be_visible()
        expect(tab).to_have_text(label)


def test_default_view_is_monitor(page):
    """The Monitor view is active by default on initial page load."""
    monitor_tab = page.locator('.nav-tab[data-view="monitor"]')
    expect(monitor_tab).to_have_class(_ACTIVE_RE)

    monitor_view = page.locator("#view-monitor")
    expect(monitor_view).to_have_class(_ACTIVE_RE)


def test_click_measure_tab(page):
    """Clicking the Measure tab shows the Measure view."""
    page.locator('.nav-tab[data-view="measure"]').click()

    measure_view = page.locator("#view-measure")
    expect(measure_view).to_have_class(_ACTIVE_RE)

    # Monitor view should no longer be active
    monitor_view = page.locator("#view-monitor")
    expect(monitor_view).to_have_class(_NOT_ACTIVE_RE)


def test_click_system_tab(page):
    """Clicking the System tab shows the System view."""
    page.locator('.nav-tab[data-view="system"]').click()

    system_view = page.locator("#view-system")
    expect(system_view).to_have_class(_ACTIVE_RE)


def test_click_midi_tab(page):
    """Clicking the MIDI tab shows the MIDI view."""
    page.locator('.nav-tab[data-view="midi"]').click()

    midi_view = page.locator("#view-midi")
    expect(midi_view).to_have_class(_ACTIVE_RE)


def test_switch_back_to_monitor(page):
    """Switching away from Monitor and back restores it."""
    page.locator('.nav-tab[data-view="system"]').click()
    page.locator('.nav-tab[data-view="monitor"]').click()

    monitor_view = page.locator("#view-monitor")
    expect(monitor_view).to_have_class(_ACTIVE_RE)

    monitor_tab = page.locator('.nav-tab[data-view="monitor"]')
    expect(monitor_tab).to_have_class(_ACTIVE_RE)
