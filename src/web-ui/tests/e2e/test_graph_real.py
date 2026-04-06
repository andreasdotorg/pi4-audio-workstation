"""E2E Playwright tests for US-095: Graph Viz — Truthful PW Topology.

Validates that the graph SVG rendered in the browser faithfully represents
the real PipeWire topology returned by the API.  These tests run against
local-demo (not mock server) so the data comes from a real PipeWire
instance with GraphManager managing links.

AD Gate 1 criteria:
    1. Node count in SVG matches real topology API response
    2. Convolver internal expansion renders correctly
    3. Link count correlates with API data
    4. Real production node names appear in SVG

Auto-skipped when local-demo is not reachable at LOCAL_DEMO_URL
(default http://localhost:8080).

Usage:
    # Start local-demo in another terminal:
    nix run .#local-demo

    # Run the tests:
    cd src/web-ui
    python -m pytest tests/integration/test_graph_truthful.py -v
"""

import json
import os
import re
import socket
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.browser, pytest.mark.slow]

# Timeouts
UI_UPDATE_TIMEOUT_MS = 15_000
GRAPH_RENDER_TIMEOUT_MS = 10_000


# ---------------------------------------------------------------------------
# Fixtures (same pattern as test_production_replica.py)
# ---------------------------------------------------------------------------

def _probe_server(url: str) -> bool:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def local_demo_url():
    url = os.environ.get("LOCAL_DEMO_URL", "http://localhost:8080")
    if not _probe_server(url):
        pytest.skip(
            f"Local-demo server not reachable at {url}. "
            f"Start it with: nix run .#local-demo")
    return url


@pytest.fixture()
def demo_page(browser, local_demo_url):
    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    pg = context.new_page()
    console_errors = []
    pg.on(
        "console",
        lambda msg: console_errors.append(msg.text)
        if msg.type == "error" else None,
    )
    pg.goto(local_demo_url)
    pg.wait_for_timeout(2000)
    yield pg
    context.close()
    real_errors = [
        e for e in console_errors
        if "/ws/siggen" not in e and "WebSocket" not in e
    ]
    if real_errors:
        print(f"[graph-truthful E2E] JS console errors (non-fatal): {real_errors}")


@pytest.fixture(autouse=True)
def _ensure_standby(local_demo_url):
    _set_mode(local_demo_url, "standby")
    yield
    _set_mode(local_demo_url, "standby")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _switch_tab(page, view_name: str):
    page.locator(f'.nav-tab[data-view="{view_name}"]').click()
    expect(page.locator(f"#view-{view_name}")).to_have_class(
        re.compile(r".*\bactive\b.*"))


def _wait_for_graph_render(page, timeout_ms=GRAPH_RENDER_TIMEOUT_MS):
    page.wait_for_function(
        "document.querySelectorAll('#gv-svg .gv-node').length > 0",
        timeout=timeout_ms,
    )


def _api_get(base_url, path, timeout=10):
    resp = urllib.request.urlopen(f"{base_url}{path}", timeout=timeout)
    return json.loads(resp.read())


def _api_post(base_url, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body else b""
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def _set_mode(base_url, mode: str) -> bool:
    """US-140: test-tool API waits for settlement server-side."""
    try:
        if mode == "measurement":
            _api_post(base_url, "/api/v1/test-tool/ensure-measurement-mode")
        else:
            _api_post(base_url, "/api/v1/test-tool/restore-mode",
                       {"mode": mode})
        return True
    except urllib.error.HTTPError as e:
        if e.code == 502:
            pytest.skip("GM not connected -- cannot switch mode")
        raise
    except Exception:
        return False


def _get_topology(base_url) -> dict:
    return _api_get(base_url, "/api/v1/graph/topology")


def _classify_node(node: dict) -> str:
    """Replicate graph.js classifyNode() logic in Python.

    Returns the classification string: source, dsp, output, capture,
    utility, skip, or other.  Only source/dsp/output/capture/utility
    nodes are rendered in the SVG.
    """
    mc = (node.get("media_class") or "").lower()
    name = (node.get("name") or "").lower()

    if "midi" in mc:
        return "skip"
    if "video" in mc:
        return "skip"
    if name == "pi4audio-convolver":
        return "dsp"
    if "graphmanager" in name:
        return "skip"
    if "stream/output" in mc:
        return "source"
    if "stream/input" in mc:
        return "utility"
    if mc == "audio/source":
        return "capture"
    if mc == "audio/sink":
        return "output"
    if mc == "audio/duplex":
        return "output"
    return "other"


_RENDERED_CLASSES = {"source", "dsp", "output", "capture", "utility"}


def _classifiable_nodes(topo: dict) -> list[dict]:
    """Return topology nodes that the graph.js renderer would display.

    graph.js only renders nodes classified as source, dsp, output,
    capture, or utility.  Nodes classified as "skip" (MIDI, Video,
    GraphManager) or "other" (empty/unknown media_class) are dropped.
    """
    return [n for n in topo.get("nodes", [])
            if _classify_node(n) in _RENDERED_CLASSES]


def _get_svg_node_count(page) -> int:
    return page.evaluate(
        "document.querySelectorAll('#gv-svg .gv-node').length")


def _get_svg_link_count(page) -> int:
    return page.evaluate(
        "document.querySelectorAll('#gv-svg .gv-link').length")


def _get_svg_internal_node_count(page) -> int:
    return page.evaluate(
        "document.querySelectorAll('#gv-svg [id^=\"gv-int-\"]').length")


def _get_svg_text_content(page) -> str:
    """Get all text content from the SVG for name matching."""
    return page.evaluate("""() => {
        const svg = document.getElementById('gv-svg');
        return svg ? svg.textContent : '';
    }""")


# ---------------------------------------------------------------------------
# 1. Node Count: SVG matches API topology
# ---------------------------------------------------------------------------


class TestNodeCountTruthfulness:
    """AD criterion 1: Node count in SVG matches real topology API."""

    def test_dj_node_count_matches_api(self, demo_page, local_demo_url):
        """In DJ mode, SVG node count matches classifiable API nodes."""
        _set_mode(local_demo_url, "dj")
        demo_page.wait_for_timeout(2000)

        _switch_tab(demo_page, "graph")
        _wait_for_graph_render(demo_page)
        # Allow poll cycle to refresh with DJ topology
        demo_page.wait_for_timeout(6000)
        _wait_for_graph_render(demo_page)

        topo = _get_topology(local_demo_url)
        api_nodes = _classifiable_nodes(topo)
        svg_node_count = _get_svg_node_count(demo_page)

        # SVG may show internal expansion nodes (convolver + gain sub-nodes)
        # in addition to the top-level classifiable nodes.  The convolver
        # node itself is replaced by its internal sub-nodes when expanded.
        has_internal = any(
            n.get("name") == "pi4audio-convolver"
            and "internal" in (n or {})
            for n in topo.get("nodes", [])
        )
        internal_count = _get_svg_internal_node_count(demo_page)

        # When internal expansion is active, the convolver is replaced by
        # N internal sub-nodes.  So expected = classifiable - 1 + internal_count.
        if has_internal and internal_count > 0:
            expected = len(api_nodes) - 1 + internal_count
        else:
            expected = len(api_nodes)

        assert svg_node_count == expected, (
            f"SVG shows {svg_node_count} nodes but API has "
            f"{len(api_nodes)} classifiable nodes "
            f"(internal expansion: {internal_count} sub-nodes). "
            f"API nodes: {[n['name'] for n in api_nodes]}")

    def test_standby_node_count_matches_api(self, demo_page, local_demo_url):
        """In standby mode, SVG node count matches classifiable API nodes."""
        _switch_tab(demo_page, "graph")
        _wait_for_graph_render(demo_page)
        demo_page.wait_for_timeout(6000)
        _wait_for_graph_render(demo_page)

        topo = _get_topology(local_demo_url)
        api_nodes = _classifiable_nodes(topo)
        svg_node_count = _get_svg_node_count(demo_page)

        has_internal = any(
            n.get("name") == "pi4audio-convolver"
            and "internal" in (n or {})
            for n in topo.get("nodes", [])
        )
        internal_count = _get_svg_internal_node_count(demo_page)

        if has_internal and internal_count > 0:
            expected = len(api_nodes) - 1 + internal_count
        else:
            expected = len(api_nodes)

        assert svg_node_count == expected, (
            f"SVG shows {svg_node_count} nodes but API has "
            f"{len(api_nodes)} classifiable nodes "
            f"(internal: {internal_count}). "
            f"API nodes: {[n['name'] for n in api_nodes]}")


# ---------------------------------------------------------------------------
# 2. Convolver Internal Expansion
# ---------------------------------------------------------------------------


class TestConvolverInternalExpansion:
    """AD criterion 2: Convolver internal topology renders correctly."""

    def test_internal_nodes_present_in_dj(self, demo_page, local_demo_url):
        """DJ mode SVG contains convolver + gain internal sub-nodes."""
        _set_mode(local_demo_url, "dj")
        demo_page.wait_for_timeout(2000)

        _switch_tab(demo_page, "graph")
        _wait_for_graph_render(demo_page)
        demo_page.wait_for_timeout(6000)
        _wait_for_graph_render(demo_page)

        topo = _get_topology(local_demo_url)
        convolver_node = next(
            (n for n in topo["nodes"]
             if n.get("name") == "pi4audio-convolver"),
            None,
        )
        if convolver_node is None:
            pytest.skip("No pi4audio-convolver node in topology")

        internal = convolver_node.get("internal")
        if internal is None:
            pytest.skip("Convolver has no internal topology data")

        # Count expected internal nodes from API
        api_internal_nodes = internal.get("nodes", [])
        api_convolver_count = sum(
            1 for n in api_internal_nodes if n.get("label") == "convolver")
        api_gain_count = sum(
            1 for n in api_internal_nodes if n.get("label") == "linear")

        # Count SVG internal nodes
        svg_internal_count = _get_svg_internal_node_count(demo_page)

        assert svg_internal_count == len(api_internal_nodes), (
            f"SVG has {svg_internal_count} internal nodes but API reports "
            f"{len(api_internal_nodes)} ({api_convolver_count} convolvers + "
            f"{api_gain_count} gains)")

    def test_internal_links_rendered(self, demo_page, local_demo_url):
        """Internal links (convolver -> gain) render in the SVG."""
        _set_mode(local_demo_url, "dj")
        demo_page.wait_for_timeout(2000)

        _switch_tab(demo_page, "graph")
        _wait_for_graph_render(demo_page)
        demo_page.wait_for_timeout(6000)
        _wait_for_graph_render(demo_page)

        topo = _get_topology(local_demo_url)
        convolver_node = next(
            (n for n in topo["nodes"]
             if n.get("name") == "pi4audio-convolver"),
            None,
        )
        if convolver_node is None or "internal" not in convolver_node:
            pytest.skip("No convolver internal topology")

        api_internal_links = convolver_node["internal"].get("links", [])

        # graph.js only renders links where BOTH endpoints resolve to a
        # rendered node.  Links to nodes classified as "other" or "skip"
        # are silently dropped (resolveOutputPort/resolveInputPort return
        # null).  Count only "renderable" external links.
        rendered_ids = {n["id"] for n in _classifiable_nodes(topo)}
        renderable_external = sum(
            1 for lk in topo.get("links", [])
            if lk.get("output_node") in rendered_ids
            and lk.get("input_node") in rendered_ids
        )

        svg_total_links = _get_svg_link_count(demo_page)

        # SVG total = renderable external + internal links
        expected_total = renderable_external + len(api_internal_links)
        # Allow small tolerance (port resolution may differ slightly)
        assert abs(svg_total_links - expected_total) <= 3, (
            f"SVG links ({svg_total_links}) should be close to "
            f"renderable external ({renderable_external}) + "
            f"internal ({len(api_internal_links)}) = {expected_total}")


# ---------------------------------------------------------------------------
# 3. Link Count Correlation
# ---------------------------------------------------------------------------


class TestLinkCountCorrelation:
    """AD criterion 3: Link count in SVG correlates with API data."""

    def test_dj_link_count_correlates(self, demo_page, local_demo_url):
        """In DJ mode, SVG link count accounts for external + internal links."""
        _set_mode(local_demo_url, "dj")
        demo_page.wait_for_timeout(2000)

        _switch_tab(demo_page, "graph")
        _wait_for_graph_render(demo_page)
        demo_page.wait_for_timeout(6000)
        _wait_for_graph_render(demo_page)

        topo = _get_topology(local_demo_url)

        # Only count external links where both endpoints are on rendered
        # nodes — graph.js drops links to "other"/"skip" nodes.
        rendered_ids = {n["id"] for n in _classifiable_nodes(topo)}
        renderable_external = sum(
            1 for lk in topo.get("links", [])
            if lk.get("output_node") in rendered_ids
            and lk.get("input_node") in rendered_ids
        )

        # Count internal links from convolver expansion
        api_internal_links = 0
        for node in topo.get("nodes", []):
            if node.get("name") == "pi4audio-convolver":
                internal = node.get("internal", {})
                api_internal_links = len(internal.get("links", []))
                break

        expected_total = renderable_external + api_internal_links
        svg_link_count = _get_svg_link_count(demo_page)

        # SVG link count should closely match expected renderable links
        assert abs(svg_link_count - expected_total) <= 3, (
            f"SVG shows {svg_link_count} links but expected ~{expected_total} "
            f"({renderable_external} renderable external + "
            f"{api_internal_links} internal)")

        # Sanity: should have at least some links
        assert svg_link_count >= 5, (
            f"SVG shows only {svg_link_count} links — DJ mode should have "
            f"a meaningful number of rendered links")

    def test_dj_has_more_api_links_than_standby(
            self, demo_page, local_demo_url):
        """DJ mode topology has more API links than standby.

        Note: In local-demo, Mixxx has empty media_class so its links
        are not rendered in the SVG.  The link count difference is only
        visible at the API level, not in the rendered SVG.  This test
        validates that the API reports a meaningful topology change on
        mode switch, which the graph viz faithfully renders (the extra
        DJ links connect to "other" nodes that graph.js intentionally
        skips).
        """
        standby_topo = _get_topology(local_demo_url)
        standby_api_links = len(standby_topo.get("links", []))

        _set_mode(local_demo_url, "dj")
        _switch_tab(demo_page, "graph")
        # Wait for SVG mode label to update to DJ — confirms graph re-render
        demo_page.wait_for_function(
            """() => {
                const label = document.getElementById('gv-mode-label');
                return label && label.textContent.trim().toUpperCase() === 'DJ';
            }""",
            timeout=UI_UPDATE_TIMEOUT_MS,
        )
        _wait_for_graph_render(demo_page)

        # US-140: _set_mode now blocks until reconciler settlement,
        # so links should already be in place.
        dj_topo = _get_topology(local_demo_url)
        dj_api_links = len(dj_topo.get("links", []))

        assert dj_api_links > standby_api_links, (
            f"DJ mode ({dj_api_links} API links) should have more links "
            f"than standby ({standby_api_links})")


# ---------------------------------------------------------------------------
# 4. Production Node Names in SVG
# ---------------------------------------------------------------------------


class TestProductionNodeNames:
    """AD criterion 4: Real production node names appear in SVG text."""

    # These are the core production node names that must appear in any
    # mode (they are always-on infrastructure nodes).
    ALWAYS_PRESENT_NAMES = [
        "pi4audio-convolver",
    ]

    # These names appear in the API topology and should be represented
    # in the SVG text (possibly shortened by graph.js's shortName()).
    DJ_MODE_EXPECTED_FRAGMENTS = [
        "convolver",      # pi4audio-convolver (or its internal sub-nodes)
        "USBStreamer",     # alsa_output.usb-miniDSP_USBStreamer_B -> "USBStreamer"
    ]

    def test_convolver_name_in_svg(self, demo_page, local_demo_url):
        """Convolver-related text appears in the SVG."""
        _set_mode(local_demo_url, "dj")
        demo_page.wait_for_timeout(2000)

        _switch_tab(demo_page, "graph")
        _wait_for_graph_render(demo_page)
        demo_page.wait_for_timeout(6000)
        _wait_for_graph_render(demo_page)

        svg_text = _get_svg_text_content(demo_page)

        # The convolver is either shown as a single node (label contains
        # "convolver") or expanded into internal sub-nodes (conv_left_hp, etc.)
        # Either way, some convolver-related text must appear.
        has_convolver = (
            "convolver" in svg_text.lower()
            or "conv_" in svg_text.lower()
            or "left hp" in svg_text.lower()
            or "right hp" in svg_text.lower()
        )
        assert has_convolver, (
            f"No convolver-related text found in SVG. "
            f"SVG text (first 500 chars): {svg_text[:500]}")

    def test_production_names_match_api(self, demo_page, local_demo_url):
        """Node names from API topology appear in SVG text content."""
        _set_mode(local_demo_url, "dj")
        demo_page.wait_for_timeout(2000)

        _switch_tab(demo_page, "graph")
        _wait_for_graph_render(demo_page)
        demo_page.wait_for_timeout(6000)
        _wait_for_graph_render(demo_page)

        topo = _get_topology(local_demo_url)
        svg_text = _get_svg_text_content(demo_page)
        svg_text_lower = svg_text.lower()

        api_nodes = _classifiable_nodes(topo)
        matched = []
        unmatched = []

        for node in api_nodes:
            name = node.get("name", "")
            desc = node.get("description", "")
            # graph.js uses description || shortName(name) as the label.
            # Check if either the name, description, or a shortened form
            # appears in the SVG text.
            found = False
            for candidate in [name, desc]:
                if not candidate:
                    continue
                if candidate.lower() in svg_text_lower:
                    found = True
                    break
            if not found:
                # Try shortName() logic: strip alsa_ prefix, extract USB name
                import re as _re
                short = _re.sub(r'^alsa_(output|input)\.', '', name)
                usb_match = _re.search(r'usb-([^.]+)', short)
                if usb_match:
                    short = usb_match.group(1).replace('_', ' ')
                short = _re.sub(r'-\d{10,}.*$', '', short)
                if short.lower() in svg_text_lower:
                    found = True
            if found:
                matched.append(name)
            else:
                unmatched.append(name)

        # At least 60% of classifiable nodes should be found in SVG text.
        # Some nodes may have truncated labels (ellipsis) so exact match
        # is not always possible.
        match_ratio = len(matched) / max(len(api_nodes), 1)
        assert match_ratio >= 0.6, (
            f"Only {len(matched)}/{len(api_nodes)} API node names found in SVG. "
            f"Matched: {matched}. Unmatched: {unmatched}")

    def test_dj_source_nodes_visible(self, demo_page, local_demo_url):
        """In DJ mode, Stream/Output/Audio source nodes appear in SVG.

        Note: The Mixxx node itself has empty media_class (pw-jack JACK
        clients don't get media.class set by PipeWire) and is classified
        as "other" by graph.js, so it does NOT render.  This is a known
        classification bug — see defect F-246.  This test verifies that
        other classified source nodes (convolver-out, signal-gen) render.
        """
        _set_mode(local_demo_url, "dj")
        demo_page.wait_for_timeout(2000)

        _switch_tab(demo_page, "graph")
        _wait_for_graph_render(demo_page)
        demo_page.wait_for_timeout(6000)
        _wait_for_graph_render(demo_page)

        topo = _get_topology(local_demo_url)
        svg_text = _get_svg_text_content(demo_page)
        svg_text_lower = svg_text.lower()

        # Find Stream/Output/Audio source nodes (classifiable as "source")
        source_nodes = [
            n for n in topo["nodes"]
            if (n.get("media_class") or "").lower() == "stream/output/audio"
        ]
        assert source_nodes, "No Stream/Output/Audio nodes in DJ topology"

        # At least one source node's name or description should appear in SVG
        found_any = False
        for node in source_nodes:
            name = node.get("name", "")
            desc = node.get("description", "")
            for candidate in [name, desc]:
                if candidate and candidate.lower() in svg_text_lower:
                    found_any = True
                    break
            if not found_any:
                # Try shortName() extraction
                short = re.sub(r'^alsa_(output|input)\.', '', name)
                short = re.sub(r'-\d{10,}.*$', '', short)
                if short.lower() in svg_text_lower:
                    found_any = True
            if found_any:
                break

        assert found_any, (
            f"No DJ source node found in SVG text. "
            f"Source nodes: {[(n['name'], n.get('description')) for n in source_nodes]}. "
            f"SVG text (first 500): {svg_text[:500]}")

    def test_mode_label_matches_api(self, demo_page, local_demo_url):
        """SVG mode label matches the API topology mode."""
        _set_mode(local_demo_url, "dj")
        demo_page.wait_for_timeout(2000)

        _switch_tab(demo_page, "graph")
        _wait_for_graph_render(demo_page)
        demo_page.wait_for_timeout(6000)
        _wait_for_graph_render(demo_page)

        topo = _get_topology(local_demo_url)
        api_mode = topo.get("mode", "").upper()

        label = demo_page.locator("#gv-mode-label")
        expect(label).to_be_attached()
        label_text = label.text_content().strip().upper()

        assert api_mode in label_text or label_text in api_mode, (
            f"SVG mode label '{label_text}' does not match "
            f"API mode '{api_mode}'")
