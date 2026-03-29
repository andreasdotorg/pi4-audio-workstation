# User Stories

Stories with acceptance criteria and Definition of Done.

## Testing Definition of Done (D-024, owner mandate 2026-03-10)

**All tasks and stories involving significant testing** must satisfy both phases
below. DoD is NOT reached until QE approves both. This applies retroactively to
all in-progress testing tasks (TK-039, T3d, any validation task).

### Phase 1: Test Protocol (approved BEFORE execution)

A test protocol document must be written and QE-approved before the test runs.
The document must include:

- **Test type:** Hypothesis test or feature validation (explicitly stated)
- **Test setup justification:** Why this setup, these parameters, this configuration
- **Prerequisites:** Git commit to deploy, configs required, Pi state expected
- **Procedure:** Executable script reference (per D-023) or step-by-step commands
- **Pass/fail criteria:** Quantitative where possible (xrun count, CPU %, latency ms)
- **Evidence requirements:** What data must be captured (logs, metrics, screenshots)
- **QE sign-off:** Quality Engineer approves the protocol before execution begins

### Phase 2: Test Execution Record (approved AFTER completion)

A test execution record must be written and QE-approved after the test completes.
The record must include:

- **Who:** Who executed the test (worker name or human)
- **What:** Exact test executed (script path, git commit deployed)
- **When:** Date/time of execution
- **How:** Any deviations from protocol, environmental conditions
- **Outcome:** PASS/FAIL with justification for the judgement
- **Raw evidence:** Log files, metric captures, screenshots as applicable
- **QE sign-off:** Quality Engineer approves the execution record and outcome

### Process

1. Test author writes protocol -> QE reviews and approves
2. Worker executes test per approved protocol -> captures evidence
3. Test author writes execution record -> QE reviews and approves
4. Only after both QE approvals: task/story DoD criteria for that test are met

### Automated Regression (owner directive 2026-03-15)

All tests MUST be part of the project's automated regression suite (runnable via
`nix run .#test-*`). One-shot validation scripts that are not
wired into the regression harness do NOT satisfy DoD. Specifically:

- Every test must catch regressions on every commit — not just validate once
- Every bug fix must include a regression test that would have caught the bug
- A fix without a regression test is incomplete
- Tests that cannot run headlessly (e.g., perceptual audio quality) must be explicitly
  marked as manual-only with justification; all others must be automated

### UX Visual Verification Gate (owner directive 2026-03-21)

**All stories that modify the web UI** must include a UX screenshot review step
before deployment to the Pi. This gate was added after the US-051 status bar was
deployed without the UX specialist ever seeing the rendered result.

**Requirements:**

- A screenshot of the **actual rendered UI** (browser or Playwright capture) must
  be provided to the UX specialist for review before DEPLOY phase
- The screenshot must show the change in context (full page, not just the changed
  element) at the minimum supported viewport width (1280px)
- The UX specialist must explicitly sign off: APPROVED or NEEDS CHANGES
- If NEEDS CHANGES, the feedback must be addressed and a new screenshot provided
  before re-review
- This is a **blocking gate** — no UI change proceeds to DEPLOY without UX sign-off
  on the visual result

**Applies to:** Any story or defect fix that modifies files in `src/web-ui/static/`
(HTML, CSS, JS that affect rendering). Does not apply to backend-only changes,
test-only changes, or documentation.

### Local-Demo Verification Gate (QE recommendation 2026-03-25)

**All stories and defect fixes touching web UI, pcm-bridge, signal-gen, or
WebSocket code** must include a local-demo verification step before the worker
reports "done."

**Background:** E2E tests run against a mock server that returns synthetic
data. This bypasses the real data pipeline (PipeWire → pcm-bridge → TCP →
Python relay → WebSocket → JS rendering) where all recent bugs (F-098,
F-101, F-102, F-103, F-105) were found. The mock server masks timing,
framing, and data-flow issues that only manifest with real audio data.

**Requirements:**

- The worker MUST run `nix run .#local-demo` and verify the affected
  feature visually (spectrum displays audio, meters show levels, test tab
  controls work) before reporting "done"
- If the local-demo stack cannot start (PipeWire unavailable, port
  conflicts), the worker must report this as a blocker — NOT skip the
  verification
- Screenshot or brief description of what was verified should be included
  in the completion report
- This gate supplements (does not replace) `nix run .#test-*` automated
  tests

**Applies to:** Any story or defect fix that modifies files in:
- `src/web-ui/` (Python backend or static JS/CSS/HTML)
- `src/pcm-bridge/` (level data or PCM streaming)
- `src/signal-gen/` (signal generation or RPC)
- `src/graph-manager/` (link routing that affects data flow to web UI)
- `scripts/local-demo.sh` or `configs/local-demo/`

---

## Tier 0 — Core Software Installation

CamillaDSP, Mixxx, and Reaper are not yet installed on the Pi 4B (verified
2026-03-08). This tier covers installing the core software stack that all
other stories depend on.

