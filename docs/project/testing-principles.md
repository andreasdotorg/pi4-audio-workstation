# Testing Principles

**Read this before writing any test, reviewing any PR, or modifying local-demo.**

This document defines the foundational testing beliefs for this project.
Everything in the testing process (`testing-process.md`) and the test strategy
(`test-strategy.md`) derives from these principles. If a practice contradicts
a principle, the principle wins.

---

## Principle 1: Test tiers have precise definitions

Each test tier has a specific scope, mock boundary, and coverage expectation.
There are no gray areas.

### Unit tests

**Scope:** One component in isolation.

- Everything outside the component under test MAY be mocked.
- Everything inside the component MUST be real — no mocking internal logic.
- Coverage must be comprehensive: all code paths within the component.
  Happy cases, failure cases, edge cases, error handling, boundary
  conditions — everything.
- A unit test answers: "Does this component do the right thing when given
  these inputs?"

### Integration tests

**Scope:** The boundary between exactly two components.

- Everything outside those two components MAY be mocked.
- The interaction between the two components MUST be real.
- Coverage must be comprehensive: all parts of the boundary. Every message
  format, every error response, every edge case in the protocol between the
  two components.
- A boundary that is happy-path-only tested is not tested.
- An integration test answers: "Do these two components talk to each other
  correctly in all cases?"

### End-to-end tests

**Scope:** The complete user path, from browser to hardware (or hardware
substitute).

- E2E tests exercise: browser → web UI → backend → services → PipeWire.
- **If it doesn't go through the browser, it is NOT an E2E test.**
- The only mocks permitted are the hardware substitutions defined in
  Principle 2 (the mock boundary).
- E2E tests must assert on **user-observable outcomes**. "WebSocket connects"
  tests plumbing. "Spectrum shows non-zero data after connecting" tests what
  the user sees. If the feature were broken from the user's perspective,
  would the test fail? If not, the test is insufficient.
- An E2E test answers: "Does this feature work for the user?"

### Environment portability

**E2E tests must run in three environments without modification:**

1. **Local-demo** (developer machine) — hardware replaced by PW adapter
   nodes per the mock boundary (Principle 2). This is the daily development
   and CI target.
2. **Real Pi with loopback cable** — USBStreamer output looped back to
   USBStreamer input, UMIK-1 physically present. Proves the software works
   with real ALSA devices and real RT scheduling.
3. **Real Pi with full audio hardware** — speakers, amplifier, room.
   The production environment. Proves the system works end-to-end including
   acoustics.

The same test code runs in all three environments. The environment determines
which PipeWire nodes are present and what signals they carry — the tests
don't change. If a test only works in local-demo but not on the Pi, the test
or the local-demo setup is wrong.

### Directory placement is binding

| Directory | Tier | Browser? | Real stack? |
|-----------|------|----------|-------------|
| `src/web-ui/tests/unit/` | Unit | No | No |
| `src/web-ui/tests/integration/` | Browser integration | Yes | No (mocked backend) |
| `tests/service-integration/` | Service integration | No | Yes (real services) |
| `src/web-ui/tests/e2e/` | E2E | Yes | Yes (full stack) |

A test in `tests/e2e/` with no Playwright `page` fixture is miscategorized.
A test that connects directly to backend TCP/RPC/WebSocket without a browser
is a service integration test, not E2E.

**Governing decisions:** L-E2E-AUDIT, L-US120.

---

## Principle 2: The mock boundary is at the hardware interface (D-057)

**Only physical hardware may be mocked in integration and E2E tests.
Everything else must be real.**

The local-demo environment substitutes these devices — and NOTHING else:

| Hardware | Substitution | Constraint |
|----------|-------------|------------|
| USBStreamer output (DAC/amp) | PW null-sink adapter node | Same node name pattern, same channel count (8), same sample rate |
| USBStreamer input (ADC/preamp) | PW null-source adapter node | Same node name pattern, same channel count (8), same sample rate |
| UMIK-1 measurement mic | Room-sim convolver output | Same node name, same channel count (1), same sample rate |
| Mixxx DJ software | Signal source (pw-jack client) | Same node name ("Mixxx"), same channel count (8), same format |

**Everything above the PW adapter nodes runs identically in local-demo and
production.** This includes:

- PipeWire (real audio graph, real links, real port negotiation)
- PipeWire filter-chain / convolver (real FIR convolution, real coefficients)
- GraphManager (real reconciler, real mode transitions, real link management)
- pcm-bridge (all instances — real TCP, real PCM streaming, real PW capture)
- level-bridge (all instances — real TCP, real level computation, real PW capture)
- signal-gen (real RPC, real PW audio output)
- Web UI backend (real API, real WebSocket, real data flow)

**Why:** Bugs caught in local-demo must be real bugs, not mock artifacts. The
venue session (D-049 Revision) proved that mock-only testing misses real
integration failures. If local-demo diverges from production, tests pass
locally but fail on the Pi — and nobody knows until a gig.

**The corollary:** If local-demo's software configuration differs from
production's (different node targets, different channel counts, different
instance configurations), that is a mock boundary violation even if the
binary is "real." The pcm-bridge binary is real, but pointing it at a
different node with a different channel count makes it a different thing.

**Enforcement:** Any change to `scripts/local-demo.sh` or to production
service configuration (`nix/nixos/production.nix`) must be reviewed against
this table. If a local-demo service instance doesn't match its production
counterpart's configuration (minus the hardware substitution), it's a defect.

**Governing decision:** D-057 addendum (owner directive).

---

## Principle 3: No mock theater

**Tests must test real behavior, not verify that mocks return what they were
told to return.**

- Mocks may ONLY replace external system boundaries (hardware, network, OS)
  in unit and integration tests — and only the hardware boundary in E2E.
- A test that only asserts a mock was called is not a valid test.
- If changing the implementation would not fail the test, the test is
  meaningless.
- `MOCK_MODE` early returns in production handlers ARE mocks — if your handler
  has a mock-mode branch, you MUST have tests that exercise the real branch.

**The regression test:** Every test must answer: "If I introduce a bug in the
implementation, will this test catch it?" If the answer is no, the test
provides false confidence and must be rewritten.

**Governing decisions:** Owner directive (2026-03-22), L-042, L-US120.

---

## Principle 4: The artifact must exist

**If your work produces a build artifact (SD card image, package, deployable
binary), the artifact must build successfully before you declare done, and
before anyone reviews it.**

- `nix eval` (T0) proves the expression evaluates. It does NOT prove the
  artifact builds. Lazy evaluation hides most errors until build time.
- Build evidence means: the exact build command, the output (size, format,
  key properties), and post-build verification.
- "T0 passes" is not build evidence.
- A PR that produces an artifact cannot be approved without build evidence.
- If you cannot build (remote builder down, cross-arch constraints), report
  the blocker. Do not declare done.

**Why:** A custom image builder was approved by all 7 reviewers without ever
being built. The build failed. This principle exists to make that impossible.

**Governing lesson:** L-F273-BUILD.

---

## Principle 5: Reviews are collaborative, not isolated

**Reviewers read the code themselves, demand evidence, and talk to each other.**

- The orchestrator connects reviewers to the branch/PR and to the worker. The
  orchestrator does NOT summarize changes or relay test results for reviewers.
- Reviewers who receive a summary instead of a pointer to the actual work MUST
  request the raw evidence before approving.
- Reviewers MAY and SHOULD message each other during review. If a concern
  touches another reviewer's domain, raise it directly.
- The AD challenges other reviewers: "Have you verified this was built/tested?"
- "No concerns in my domain" is valid — but only after examining the diff.

**Governing lesson:** L-F273-BUILD.

---

## Where to find the details

| Topic | Document |
|-------|----------|
| Testing governance (who decides, gates, failure triage) | `testing-process.md` |
| Test strategy (what to test, tiers, tooling) | `test-strategy.md` |
| Test protocol template (formal test plans) | `test-protocol-template.md` |
| How to run tests (commands, Nix) | `docs/guide/howto/development.md` |
| Mock boundary decision record | `decisions/D-057.md` addendum |
| Local-demo architecture | `scripts/local-demo.sh` header comment |
