# L-QE-002: Integration Tests Mislabeled as E2E

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

The QE had approved the test suite (34/34 pass) and recommended owner
acceptance. The owner should never have been asked to validate a broken
deliverable.

## Root Cause

**The tests labeled "E2E" are actually integration tests — they run against
a fully mocked backend, not the real stack.**

"End-to-end" means the real stack, end to end. Tests that mock PipeWire,
GraphManager, and all audio services are integration tests: they verify
frontend-backend contract, routing, input validation, and UI behavior
against mock data. This is valuable and necessary work — but it is not E2E.

The FastAPI server started by the test fixture (`conftest.py`) inherits the
default `PI_AUDIO_MOCK=1` environment variable (`main.py:67` defaults to
`"1"` when unset). In mock mode:

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

**The problem was not that mock-backend tests exist.** They are necessary.
The problem was that they were labeled "E2E" and accepted as proof of
end-to-end functionality. The QE approved "34/34 E2E pass" as sufficient
evidence because the label implied end-to-end coverage. It was not.

## Impact

- **US-113 acceptance blocked.** Owner refused to review until real E2E
  tests run against the correct stack.
- **False confidence.** 34/34 passing "E2E" tests gave the QE and team
  confidence that the config tab worked. It did not work on the real stack.
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
are correct for integration tests. They do not define E2E tests.

Section 3.3 (The Regression Test) asks: "If I introduce a bug in the
implementation, will this test catch it?" For the `/api/v1/config` endpoint,
the answer is **no** — any bug in `pw_dump()` parsing, `find_gain_node()`,
`find_convolver_node()`, or any real PipeWire interaction is invisible to
the mock-backend integration tests.

## Correct Terminology

| Current name | Correct name | What it tests | Runner |
|-------------|-------------|---------------|--------|
| `test-e2e` (old) | **Integration tests** (browser) | FastAPI + Chromium + frontend JS against mock backends | `nix run .#test-integration-browser` (renamed) |
| (does not exist) | **E2E tests** | Full stack: PipeWire + GM + services + web UI + browser | `nix run .#test-e2e` (to build) |
| `test-integration` | **Integration tests** (PipeWire) | Headless PW + GM + audio pipeline, no browser | `nix run .#test-integration` (existing) |
| `test-unit` | **Unit tests** | Python unit tests, mock mode | `nix run .#test-unit` (unchanged) |

### Integration Tests (browser) — renamed from `test-e2e` to `test-integration-browser`

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

### E2E Tests — missing, needs implementation

- **Environment:** Linux with headless PipeWire + GM + signal-gen +
  pcm-bridge + level-bridge (same stack as `nix run .#local-demo`).
- **What's real:** Everything in integration PLUS real PipeWire daemon,
  real GraphManager with real `pw-dump`/`pw-link` calls, real pcm-bridge
  level metering, real WebSocket data from live audio graph.
- **What's mocked:** Only physical audio hardware (USBStreamer, UMIK-1,
  amplifiers, speakers). The null ALSA sink used by local-demo replaces
  the USBStreamer — this is the **only legitimate mock in E2E**.
- **Value:** Catches the exact class of bug that blocked US-113 — real
  PipeWire data parsing failures, GM state machine issues, mock-production
  divergence. This is the **real regression gate**.
- **Limitation:** Linux-only (PipeWire required). Slower startup (~10s for
  the full stack). Cannot test on macOS.

## Process Improvement

### Mock Boundary by Test Type

| Component | Unit | Integration (browser) | Integration (PW) | E2E |
|-----------|------|----------------------|-------------------|-----|
| FastAPI server | Real | Real | N/A | Real |
| Chromium browser | N/A | Real | N/A | Real |
| Frontend JS/HTML/CSS | N/A | Real | N/A | Real |
| Route handlers | Partial | Real | N/A | Real |
| Business logic | Real | Real | N/A | Real |
| PipeWire daemon | **Mocked** | **Mocked** | **Real** | **Real** |
| GraphManager | **Mocked** | **Mocked** | **Real** | **Real** |
| pw-dump / pw-cli | **Mocked** | **Mocked** | **Real** | **Real** |
| pcm-bridge / level-bridge | **Mocked** | **Mocked** | **Real** | **Real** |
| signal-gen | N/A | N/A | **Real** | **Real** |
| WebSocket data | **Mocked** | **Mocked** | N/A | **Real** |
| USBStreamer hardware | N/A | N/A | **Mocked** (null sink) | **Mocked** (null sink) |
| Physical audio devices | N/A | N/A | N/A | N/A |

### Implementation Plan

1. **Rename `test-e2e` to `test-integration-browser`** (or similar) in
   `flake.nix`. This is the most important change — it corrects the label
   so the team and QE do not confuse integration tests with E2E.

2. **Build real E2E runner** as `nix run .#test-e2e` that:
   - Starts the local-demo stack (headless PipeWire + GM + all services)
   - Sets `PI_AUDIO_MOCK=0`
   - Waits for stack health (GM responsive, PW graph stable)
   - Runs Playwright tests against the live server
   - Tears down the stack on completion

3. **E2E test selection:** Not all integration tests need to also run as
   E2E. Tests that only exercise UI behavior (rendering, input validation,
   JS events) are sufficient at the integration level. E2E is required for
   tests that exercise:
   - `/api/v1/config` (reads pw-dump)
   - `/api/v1/graph/*` (reads GM state)
   - WebSocket data display (monitoring, system views)
   - Any endpoint that calls `pw_dump()`, `pw-cli`, or `pw-metadata`
   - Venue/gate operations when GM state persistence matters

4. **Gate integration:**

   | Change category | Required tests |
   |----------------|----------------|
   | UI-only (HTML/CSS/JS, no backend) | Integration (browser) |
   | Backend business logic (no PW interaction) | Unit + Integration (browser) |
   | PipeWire interaction code (collectors, pw-dump) | Unit + Integration (browser) + **E2E** |
   | GM RPC handling | Unit + Integration (browser) + **E2E** |
   | Full-stack features (venue/gate with live GM) | Unit + Integration (browser) + **E2E** |

5. **CI integration:** E2E tests require Linux + PipeWire. The self-hosted
   runner (future US-070 enhancement) can run E2E. GitHub-hosted runners
   may not have PipeWire — E2E would be skipped there with a clear marker.

### QE Gate Change

**Before this learning:** QE approved "E2E" tests based on pass/fail
against the mock stack. The label "E2E" created false confidence that
end-to-end functionality was verified.

**After this learning:**
- The QE must use correct terminology: mock-backend browser tests are
  **integration tests**, not E2E.
- For stories touching PipeWire interaction code: **E2E evidence required.**
  "34/34 integration tests pass" is necessary but insufficient — worker
  must also demonstrate the feature works against the real stack.
- For stories touching only UI/business logic: integration tests are
  sufficient.
- The QE must classify each story's test requirements by type and demand
  appropriate evidence before approving.

### Immediate Action (before E2E runner exists)

Until `nix run .#test-e2e` (real-stack) is implemented, the manual
equivalent is:
1. Worker runs `nix run .#local-demo`
2. Worker manually verifies the affected feature works in the browser
3. Worker provides screenshot or command output as evidence
4. QE reviews the evidence

This is essentially what Gate 2 (Pi hardware validation) does, but on the
local machine instead of the Pi. It catches the class of bugs that
integration tests miss without requiring Pi hardware.

## QE Self-Assessment

The QE's US-113 review correctly identified:
- No mock theater (MockGraphManagerClient is a legitimate system boundary
  mock for integration tests)
- Real code paths exercised within the integration test scope
  (venue_routes.py, venue.py, venue.js)
- Value assertions on computed data (not just structure checks)
- Security coverage (path traversal, XSS, D-009)

The QE failed to identify:
- The tests labeled "E2E" were actually integration tests. The QE accepted
  the label at face value and treated integration test results as E2E
  evidence. This was the core error.
- The config tab's `/api/v1/config` endpoint had **zero** test coverage
  (not even at the integration level). This pre-existing gap should have
  been flagged.
- The mock-backend integration tests exercise fundamentally different code
  paths than the real stack. The QE should have questioned whether
  "PI_AUDIO_MOCK=1" testing could ever constitute E2E evidence.

## References

- `src/web-ui/tests/integration/conftest.py:137-138` — mock server env (no PI_AUDIO_MOCK set)
- `src/web-ui/app/main.py:67` — MOCK_MODE defaults to "1"
- `src/web-ui/app/config_routes.py:126-127` — mock path bypass in get_config()
- `scripts/local-demo.sh:596` — PI_AUDIO_MOCK=0 in local-demo
- `docs/project/testing-process.md` Section 3 — mock theater rules
- `scripts/test-integration.sh` — existing real-stack integration test (no browser)
