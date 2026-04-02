# L-QE-002: E2E Tests Run Against Mock Stack, Not Real Stack

**Date:** 2026-04-02
**Severity:** Process failure — blocked owner acceptance of US-113
**Author:** Quality Engineer
**Status:** Open — process improvement required

---

## What Happened

The owner attempted to validate US-113 (venue selection + audio gate) via
`nix run .#local-demo`. Two errors appeared immediately:

1. GraphManager warning: `Gain integrity: parse error: JSON parse error:
   expected value at line 1612 column 11`
2. Web UI config tab: "Channel gains in config show Failed to load config:
   HTTP 502"

The QE had approved US-113 Phase 5 E2E tests (34/34 pass) and recommended
owner acceptance. The owner should never have been asked to validate a
broken deliverable.

## Root Cause

**The E2E test suite runs against a mock stack, not the real audio stack.**

The FastAPI server started by the E2E test fixture (`conftest.py`) inherits
the default `PI_AUDIO_MOCK=1` environment variable (`main.py:67` defaults
to `"1"` when unset). In mock mode:

- `config_routes.py:get_config()` returns `_mock_config_response()` — a
  hardcoded dict. It never calls `pw_dump()`. The 502 path is unreachable.
- `venue_routes.py` uses `MockGraphManagerClient` instead of a real TCP
  connection to GraphManager on port 4002.
- `ws_system.py`, `ws_monitoring.py` use mock data generators instead of
  real PipeWire/pcm-bridge data.
- All 13 modules that check `MOCK_MODE` bypass their real code paths.

Meanwhile, `nix run .#local-demo` sets `PI_AUDIO_MOCK=0` and starts a real
headless PipeWire instance, real GraphManager, real signal-gen, real
pcm-bridge, and real level-bridge. The web UI runs against real PipeWire
data via `pw-dump`. When the GM produced malformed JSON, `pw_dump()` failed
and the `/api/v1/config` endpoint returned 502.

**The E2E tests and local-demo exercise fundamentally different code paths.**
The tests verify the mock paths work. They never verify the real paths work.

## Impact

- **US-113 acceptance blocked.** Owner refused to review until E2E runs
  against the correct stack.
- **False confidence.** 34/34 passing tests gave the QE and team confidence
  that the config tab worked. It did not work on the real stack.
- **Owner trust.** The owner was presented a broken deliverable after the
  QE recommended acceptance. This erodes trust in the QE gate.

## What the Project Rules Say

`testing-process.md` Section 3.1 defines legitimate mock targets:

> Mocks replace **external system boundaries** — things that are unavailable
> or unsafe in the test environment:
> - PipeWire daemon (pw-cli, pw-dump) — Not available in Nix sandbox
> - Audio hardware (USBStreamer, UMIK-1) — Not available in test environment
> - Network services (GraphManager RPC) — May not be running

These rules were written for the `nix flake check` pure sandbox and
`nix run .#test-unit` context, where PipeWire truly is unavailable. They
do not account for E2E tests that *could* run against a real PipeWire
instance via the local-demo stack.

Section 3.3 (The Regression Test) asks: "If I introduce a bug in the
implementation, will this test catch it?" For the `/api/v1/config` endpoint,
the answer is **no** — any bug in `pw_dump()` parsing, `find_gain_node()`,
`find_convolver_node()`, or any real PipeWire interaction is invisible to
the mock-mode E2E tests.

## Analysis: Two Tiers of E2E

The project currently has one E2E tier that mocks everything except the
FastAPI server, browser, and JS frontend. This is useful but insufficient.
There should be two tiers:

### Tier 1: Mock-backend E2E (current — `nix run .#test-e2e`)

- **Environment:** Nix sandbox, no PipeWire daemon, no GM, no audio hardware.
- **What's real:** FastAPI route handlers, Pydantic validation, business
  logic (venue.py, config_routes.py mock path), frontend JS in Chromium,
  HTML/CSS rendering.
- **What's mocked:** PipeWire (pw-dump, pw-cli, pw-metadata),
  GraphManager RPC, pcm-bridge levels, system collectors, WebSocket
  data sources.
- **Value:** Catches UI rendering bugs, routing errors, input validation
  failures, JS errors, frontend-backend contract violations.
- **Blind spots:** Cannot catch pw-dump parse errors, GM RPC protocol
  mismatches, real PipeWire state machine issues, mock-production data
  divergence (F-056, F-057 precedent).

### Tier 2: Real-stack E2E (missing — needs implementation)

- **Environment:** Linux with headless PipeWire + GM + signal-gen +
  pcm-bridge + level-bridge (same stack as `nix run .#local-demo`).
- **What's real:** Everything in Tier 1 PLUS real PipeWire daemon,
  real GraphManager with real `pw-dump`/`pw-link` calls, real pcm-bridge
  level metering, real WebSocket data from live audio graph.
- **What's mocked:** Only physical audio hardware (USBStreamer, UMIK-1,
  amplifiers, speakers). The null ALSA sink used by local-demo replaces
  the USBStreamer — this is the only legitimate mock.
- **Value:** Catches the exact class of bug that blocked US-113 — real
  PipeWire data parsing failures, GM state machine issues, mock-production
  divergence. This is the **real regression gate**.
- **Limitation:** Linux-only (PipeWire required). Slower startup (~10s for
  the full stack). Cannot test on macOS.

## Process Improvement

### Rule: E2E Mock Boundary for Each Tier

| Component | Tier 1 (mock-backend) | Tier 2 (real-stack) |
|-----------|----------------------|---------------------|
| FastAPI server | Real | Real |
| Chromium browser | Real | Real |
| Frontend JS/HTML/CSS | Real | Real |
| Route handlers | Real | Real |
| Business logic (venue.py, etc.) | Real | Real |
| Input validation | Real | Real |
| PipeWire daemon | **Mocked** (PI_AUDIO_MOCK=1) | **Real** (headless) |
| GraphManager | **Mocked** (MockGraphManagerClient) | **Real** (binary) |
| pw-dump / pw-cli | **Mocked** (mock responses) | **Real** (live PW) |
| pcm-bridge / level-bridge | **Mocked** (mock data) | **Real** (binaries) |
| signal-gen | **Not started** | **Real** (binary) |
| WebSocket data | **Mocked** (MockDataGenerator) | **Real** (live data) |
| USBStreamer hardware | N/A | **Mocked** (null ALSA sink) |
| Physical audio devices | N/A | N/A |

### Implementation Plan

1. **Tier 2 test runner:** Create `nix run .#test-e2e-real` that:
   - Starts the local-demo stack (headless PipeWire + GM + all services)
   - Waits for stack health (GM responsive, PW graph stable)
   - Runs Playwright tests with `PI_AUDIO_MOCK=0` against the live server
   - Tears down the stack on completion

2. **Tier 2 test selection:** Not all E2E tests need Tier 2. Tests that
   exercise mock-only paths (UI rendering, input validation, JS behavior)
   run fine at Tier 1. Tier 2 is required for tests that exercise:
   - `/api/v1/config` (reads pw-dump)
   - `/api/v1/graph/*` (reads GM state)
   - WebSocket data display (monitoring, system views)
   - Any endpoint that calls `pw_dump()`, `pw-cli`, or `pw-metadata`
   - Venue/gate operations when GM state persistence matters

3. **Gate integration:** Tier 2 becomes part of Gate 1 for stories that
   modify collectors, PipeWire interaction code, or GM RPC handling.
   Tier 1 remains sufficient for UI-only and business-logic-only changes.

4. **CI integration:** Tier 2 tests require Linux + PipeWire. The
   self-hosted runner (future US-070 enhancement) can run Tier 2.
   GitHub-hosted runners may not have PipeWire — Tier 2 would be
   skipped there with a clear marker.

### QE Gate Change

**Before this learning:** QE approved E2E tests based on pass/fail against
the mock stack. The QE verified no mock theater (mocks only at system
boundaries) and verified real code paths were exercised.

**After this learning:** The QE must additionally verify:
- For stories touching PipeWire interaction code: Tier 2 evidence required.
  "34/34 pass on mock stack" is insufficient — worker must also demonstrate
  the feature works on `nix run .#local-demo`.
- For stories touching only UI/business logic: Tier 1 remains sufficient.
- The QE must classify each story's test requirements as Tier 1, Tier 2,
  or both, and demand appropriate evidence before approving.

### Immediate Action (before Tier 2 runner exists)

Until `nix run .#test-e2e-real` is implemented, the manual equivalent is:
1. Worker runs `nix run .#local-demo`
2. Worker manually verifies the affected feature works in the browser
3. Worker provides screenshot or command output as evidence
4. QE reviews the evidence

This is essentially what Gate 2 (Pi hardware validation) does, but on the
local machine instead of the Pi. It catches the class of bugs that Tier 1
misses without requiring Pi hardware.

## QE Self-Assessment

The QE's US-113 review correctly identified:
- No mock theater (MockGraphManagerClient is a legitimate system boundary mock)
- Real code paths exercised (venue_routes.py, venue.py, venue.js)
- Value assertions on computed data (not just structure checks)
- Security coverage (path traversal, XSS, D-009)

The QE failed to identify:
- The config tab's `/api/v1/config` endpoint had **zero** E2E test coverage
  (not even at Tier 1). This pre-existing gap should have been flagged.
- The entire E2E suite runs against mock backends, meaning no test exercises
  the `pw_dump()` real path. The QE accepted "mock at system boundaries" as
  sufficient without questioning whether those boundaries could be pushed
  further outward (to physical hardware only, not PipeWire).
- The mock theater rules in `testing-process.md` Section 3.1 were designed
  for the pure Nix sandbox. The QE did not question whether those rules
  were appropriate for E2E tests that could run against a real stack.

## References

- `src/web-ui/tests/e2e/conftest.py:137-138` — mock server env (no PI_AUDIO_MOCK set)
- `src/web-ui/app/main.py:67` — MOCK_MODE defaults to "1"
- `src/web-ui/app/config_routes.py:126-127` — mock path bypass in get_config()
- `scripts/local-demo.sh:596` — PI_AUDIO_MOCK=0 in local-demo
- `docs/project/testing-process.md` Section 3 — mock theater rules
- `scripts/test-integration.sh` — existing real-stack integration test (no browser)
