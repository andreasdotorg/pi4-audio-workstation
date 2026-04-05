# HOWTO: Common Development Tasks

This guide covers the most common tasks that workers and developers perform on
the mugge project. It assumes you have already cloned the
repository and have Nix installed.

## 1. Nix Environment

The project uses Nix flakes (`flake.nix`) to provide a fully reproducible
Python 3.13 environment with all dependencies. There is no `requirements.txt`
or `pyproject.toml` for dependency management. The single source of truth for
all Python dependencies is `flake.nix`.

### 1.1 Running Tests and Commands

**`nix run .#<target>`** is the QA gate. It runs tests impurely against the
working tree (picks up uncommitted changes):

```sh
nix run .#test-unit             # Web UI unit tests (excludes e2e)
nix run .#test-room-correction  # Room correction DSP tests
nix run .#test-graph-manager    # GraphManager Rust tests (pure logic)
nix run .#test-integration-browser  # Playwright browser integration tests
nix run .#test-integration      # PipeWire integration test (Linux only, US-075)
nix run .#test-e2e              # Real E2E: full stack + browser (Linux only)
nix run .#test-all              # All suites sequentially
nix run .#local-demo            # Local dev stack (PipeWire + GM + web UI, Linux only)
```

### 1.2 Interactive Development

For editing, debugging, and REPL work, enter the development shell:

```sh
nix develop
```

This drops you into a shell with Python 3.13 and all flake dependencies
available. From here you can run pytest directly, start a REPL, use an editor,
or do any interactive work:

```sh
# Inside nix develop
python -m pytest src/room-correction/tests/ -v
python -m pytest src/web-ui/tests/ -v -k "not e2e"
```

### 1.3 What NOT to Do

Do not bypass Nix for test runs or dependency management:

- **Do not** use `.venv/bin/python -m pytest ...` -- impure, not reproducible
- **Do not** use `source .venv/bin/activate && pytest ...` -- same problem
- **Do not** run `pip install ...` into any venv -- breaks Nix reproducibility

The `.venv` directories exist as an implementation detail of the Nix
environment setup. They are not the intended interface for running code.


## 2. Test Suites

The project has four test suites, each in its own subdirectory (under `src/`
for product code, `scripts/` for utilities) with a `pytest.ini`.

### 2.1 Room Correction Unit Tests

Tests for the DSP pipeline: sweep generation, deconvolution, spatial averaging,
gain calibration, time alignment, filter generation, thermal ceiling, power
validation. 15 test files in `src/room-correction/tests/`.

```sh
nix run .#test-room-correction
```

### 2.2 Web UI Unit / Integration Tests

Tests for the FastAPI backend: server startup, collectors, measurement session
state machine, Phase 1 validation. Run in mock mode (`PI_AUDIO_MOCK=1`).
Located in `src/web-ui/tests/` (excluding the `e2e/` subdirectory).

```sh
nix run .#test-unit
```

### 2.3 Web UI Browser Integration Tests (Playwright)

Browser integration tests use Playwright (Chromium) to drive the web UI against a
session-scoped mock FastAPI server that starts automatically on a free port.
Located in `src/web-ui/tests/integration/`.

```sh
nix run .#test-integration-browser
```

**Visual regression tests** compare screenshots against reference images in
`src/web-ui/tests/integration/screenshots/`. After intentional UI changes,
regenerate reference screenshots and review the diffs before committing.

**Destructive tests** are marked `@pytest.mark.destructive` (they modify Pi
state) and are skipped by default. They require the `--destructive` flag.

**Tests against a real Pi** use the `pi_url` fixture and require the
`PI_AUDIO_URL` environment variable. Tests skip if it is unset.

### 2.4 MIDI Daemon and Driver Tests

Located in `src/midi/tests/` and `scripts/drivers/tests/` respectively.
These do not have individual `nix run` targets. They are included in:

- `nix run .#test-all` (runs all suites sequentially)

### 2.5 GraphManager Rust Tests

Rust-based logic tests for the GraphManager (reconciler, watchdog, routing
tables). Runs via `cargo test` inside the Nix environment.

```sh
nix run .#test-graph-manager
```

### 2.6 PipeWire Integration Test (US-075)

End-to-end test that starts a headless PipeWire instance with the full
production-replica audio pipeline (GraphManager, signal-gen, level-bridge,
pcm-bridge, filter-chain convolver) and verifies audio flow, link topology,
and graph metadata. Linux only — requires PipeWire.

```sh
nix run .#test-integration
```

The test verifies:
- Convolver node present in PW graph
- GM creates correct link topology (measurement mode, 29 desired links)
- signal-gen produces 1 kHz sine at -20 dBFS
- level-bridge reports non-zero levels on expected channels
- GM `get_graph_info` and `get_links` RPC respond correctly
- Full cycle completes in < 30 seconds

### 2.7 Running Everything

```sh
nix run .#test-all # All suites sequentially against working tree
```

### 2.8 Three-Gate Testing Process

The project uses a three-gate testing process (owner-approved, 2026-03-22):

| Gate | When | What | Who |
|------|------|------|-----|
| **Gate 1** | Every task | `nix run .#test-<suite>` (targeted suite for changed code) | Worker |
| **Gate 2** | Pre-merge / story-closing commits | `nix run .#test-all` (full suite including E2E) | Worker or CI |
| **Gate 3** | REVIEW phase | Pi acceptance testing | Owner |

**`nix run .#test-*` is the sole QA gate.** `nix flake check` is build
validation only. `nix develop` is for interactive exploration, not QA.

### 2.9 Rust Test Tiers (US-075 AC 7)

Rust tests use three tiers:

| Tier | Purpose | How | When |
|------|---------|-----|------|
| **Tier 1** | Dev loop (fast) | `nix run .#test-graph-manager` etc. Shell script `cargo test` wrappers. Non-hermetic, uses host state. | During development |
| **Tier 2** | QA gate (hermetic) | `nix flake check` runs `buildRustPackage` per crate. Hermetic, sandboxed, deterministic. | Pre-merge |
| **Tier 3** | PW integration | `nix run .#test-integration`. Real PipeWire instance with full audio pipeline. | Pre-merge on Linux |

**Tier 1 targets** (fast iteration, not reproducible):
- `nix run .#test-graph-manager` — pure logic, no PipeWire
- `nix run .#test-audio-common` — shared audio crate
- `nix run .#test-level-bridge` — Linux only
- `nix run .#test-pcm-bridge` — Linux only
- `nix run .#test-signal-gen` — Linux only

**Tier 2** runs automatically via `nix flake check` (the `checks` attribute).
Each Rust crate has exactly one QA target using `buildRustPackage`.

**Tier 3** (`nix run .#test-integration`) starts a headless PipeWire instance,
verifies audio flow through the convolver, and checks GM link topology.


## 3. Running the Web UI Locally

The web UI is a FastAPI application. In mock mode (`PI_AUDIO_MOCK=1`, the
default), it uses mock collectors and mock backends so you can develop and
test without audio hardware or PipeWire.

```sh
nix run .#local-demo
```

This starts the full local development stack on Linux: a headless PipeWire
instance, GraphManager, signal-gen, pcm-bridge, level-bridge, and the web UI
on `0.0.0.0:8080`. The UI will be available at `http://localhost:8080`.

For interactive development (e.g., custom host/port, debugging), use the
development shell:

```sh
nix develop
cd src/web-ui
python -m uvicorn app.main:app --host 127.0.0.1 --port 9000 --reload
```


## 4. Deploying to the Pi

Deployment to the Pi goes through the Change Manager (CM) using the deployment
target access protocol (see `.claude/team/protocol/deployment-target-access.md`).
Workers do not deploy directly; they commit code and the CM deploys.

### 4.1 Protocol Summary

1. The CM must hold a DEPLOY session (exclusive lock) before deploying.
2. Only committed code is deployed (D-023). The git working tree must be clean.
3. The owner must be notified before any action that restarts PipeWire or
   reboots the Pi, because the USBStreamer produces transients through the
   amplifier chain that can damage speakers. See `docs/operations/safety.md`.

### 4.2 The Deploy Script

`scripts/deploy/deploy.sh` deploys version-controlled configs and scripts to
the Pi via SSH/SCP/rsync.

```sh
scripts/deploy/deploy.sh --dry-run              # preview what would be deployed
scripts/deploy/deploy.sh                         # deploy configs and code
scripts/deploy/deploy.sh --mode dj               # deploy and set DJ/PA mode
scripts/deploy/deploy.sh --mode live             # deploy and set Live mode
scripts/deploy/deploy.sh --pi ela@10.0.0.5       # deploy to a different host
scripts/deploy/deploy.sh --reboot                # deploy and reboot
```

The script runs 10 sections:

1. Validate prerequisites (clean git, Pi reachable, source files exist)
2. Deploy user-level configs (PipeWire, WirePlumber, labwc, systemd user units)
3. Deploy system-level configs via sudo (udev rules, systemd overrides)
4. Deploy FIR coefficient files to `/etc/pi4audio/coeffs/`
5. Reload systemd (system + user)
6. Deploy scripts to `~/bin/` (test, stability, launch scripts)
6b. Deploy Rust binaries to `~/bin/` (with `.bak` rollback + version check)
7. Deploy web UI, measurement, and room correction code via rsync
8. Verify (PipeWire config syntax, script syntax, libjack resolution)
9. Optionally reboot

### 4.3 Manual Deploy (git pull on Pi)

For quick code-only updates during development sessions, the CM may run
`git pull` on the Pi instead of the full deploy script. This is only
appropriate for changes to scripts and application code (not system configs).

### 4.4 Rust Binary Deployment

The project has 4 Rust crates that produce binaries deployed to `~/bin/`
on the Pi:

| Crate | Binary name | Build directory | Systemd service |
|-------|------------|-----------------|-----------------|
| `src/graph-manager/` | `pi4audio-graph-manager` | `src/graph-manager/target/release/` | `pi4audio-graph-manager.service` |
| `src/pcm-bridge/` | `pcm-bridge` | `src/target/release/` | `pcm-bridge@monitor.service` |
| `src/signal-gen/` | `pi4audio-signal-gen` | `src/target/release/` | `pi4audio-signal-gen.service` |
| `src/level-bridge/` | `level-bridge` | `src/target/release/` | `level-bridge@monitor.service` |

Note: `graph-manager` has its own `Cargo.toml` and builds independently.
The other three are in a Cargo workspace (`src/Cargo.toml`), which is why
their build output lands in `src/target/release/`.

#### Building on the Pi (native ARM)

The Pi has Rust installed via rustup (`~/.cargo/env`). Non-login SSH
sessions do not source this automatically, so prefix build commands:

```sh
# Build graph-manager (separate crate, own Cargo.lock)
ssh ela@192.168.178.185 "source ~/.cargo/env && cd ~/pi4-audio-workstation/src/graph-manager && cargo build --release"

# Build workspace binaries (pcm-bridge, signal-gen, level-bridge)
ssh ela@192.168.178.185 "source ~/.cargo/env && cd ~/pi4-audio-workstation/src && cargo build --release"
```

#### Deploying binaries

**Option A: deploy.sh** — Section 6b of `deploy.sh` handles Rust binary
deployment automatically. It looks for local release binaries, backs up
existing binaries as `.bak`, copies the new ones, and runs `--version`
verification. If no local release binaries exist, section 6b is skipped.

**Option B: Manual deployment** — After building on the Pi:

```sh
# Stop services first (binaries may be read-only while running)
ssh ela@192.168.178.185 "systemctl --user stop pi4audio-graph-manager.service pcm-bridge@monitor.service pi4audio-signal-gen.service level-bridge@monitor.service"

# Back up + copy binaries
ssh ela@192.168.178.185 "cd ~/pi4-audio-workstation && \
  for bin in pi4audio-graph-manager; do \
    test -f ~/bin/\$bin && cp ~/bin/\$bin ~/bin/\$bin.bak; \
    chmod u+w ~/bin/\$bin 2>/dev/null; \
    cp src/graph-manager/target/release/\$bin ~/bin/\$bin && chmod +x ~/bin/\$bin; \
  done && \
  for bin in pcm-bridge pi4audio-signal-gen level-bridge; do \
    test -f ~/bin/\$bin && cp ~/bin/\$bin ~/bin/\$bin.bak; \
    chmod u+w ~/bin/\$bin 2>/dev/null; \
    cp src/target/release/\$bin ~/bin/\$bin && chmod +x ~/bin/\$bin; \
  done"

# Restart services
ssh ela@192.168.178.185 "systemctl --user start pi4audio-graph-manager.service pcm-bridge@monitor.service pi4audio-signal-gen.service level-bridge@monitor.service"
```

**SAFETY:** Stopping PipeWire-connected services does NOT restart PipeWire
itself (no USBStreamer transient risk). However, if restarting the graph
manager, audio routing will be interrupted until it comes back up.

#### Rollback

If a newly deployed binary causes issues, restore from the `.bak` file:

```sh
ssh ela@192.168.178.185 "systemctl --user stop pi4audio-graph-manager.service && \
  cp ~/bin/pi4audio-graph-manager.bak ~/bin/pi4audio-graph-manager && \
  systemctl --user start pi4audio-graph-manager.service"
```

#### Version verification

Three of the four binaries support `--version` (pcm-bridge, signal-gen,
level-bridge). Graph-manager does not have a version flag yet.

```sh
ssh ela@192.168.178.185 "~/bin/pcm-bridge --version && ~/bin/pi4audio-signal-gen --version && ~/bin/level-bridge --version"
```


## 5. Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PI_AUDIO_MOCK` | `1` | Enable mock mode (mock collectors, mock GraphManager/signal-gen). Set to `0` for real hardware. |
| `PI_AUDIO_URL` | (unset) | Pi web UI URL for e2e tests against real hardware. Tests skip if unset. |
| `PI4AUDIO_LEVELS_HOST` | `127.0.0.1` | pcm-bridge levels server host for LevelsCollector (peak/RMS metering). |
| `PI4AUDIO_LEVELS_PORT` | `9100` | pcm-bridge levels server TCP port for LevelsCollector. |
| `PI4AUDIO_PCM_JACK` | (unset) | Enable legacy JACK PCM collector (`1` = enable). Default off — pcm-bridge (Rust) is the replacement. The JACK client joins the RT graph and can cause xruns. |
| ~~`PI4AUDIO_PW_TOP`~~ | **removed** | Removed (US-063). PipeWireCollector now uses GraphManager RPC — no pw-top subprocess, no env gate needed. PipeWire data is always available. |
| `PI4AUDIO_MEAS_DIR` | (unset) | Override measurement directory path. Set in webui systemd service file on Pi. |
| `PLAYWRIGHT_BROWSERS_PATH` | (set by flake) | Path to Playwright's Chromium. Set automatically in `nix develop` and `nix run`. |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | `1` (set by flake) | Prevents Playwright from downloading browsers (Nix provides them). |


## 6. Project Layout

```
mugge/
  flake.nix                       Nix flake — all deps, packages, test targets
  flake.lock                      Pinned Nix inputs
  configs/                        Version-controlled Pi configs
    pipewire/                     PipeWire config fragments (quantum, filter-chain convolver)
    wireplumber/                  WirePlumber config fragments (D-043: linking disabled)
    labwc/                        Wayland compositor config
    systemd/                      Systemd unit files and overrides
    udev/                         udev rules (USBStreamer ALSA lockout, US-044)
    room-correction/              Room correction pipeline configs
    speakers/                     Speaker identity profiles
    camilladsp/                   Historical CamillaDSP configs (service stopped, D-040)
  src/
    graph-manager/                Rust GraphManager — sole PipeWire link manager (D-039)
    signal-gen/                   Rust RT signal generator — measurement audio source
    pcm-bridge/                   Rust PipeWire monitor tap (lock-free level metering)
    web-ui/                       FastAPI web UI + monitoring dashboard
      app/                        FastAPI application
        collectors/               Backend data collectors (FilterChain, Levels, System, PW)
        measurement/              Measurement daemon (session, routes)
        mock/                     Mock backends for development
      static/                     Frontend assets (HTML, JS, CSS)
      tests/                      Unit + integration tests
        e2e/                      Playwright e2e tests
          screenshots/            Visual regression reference images
    room-correction/              DSP pipeline (sweep, deconvolution, filters)
      tests/                      Unit tests (15+ test files)
    measurement/                  Measurement client libraries (GraphManager, signal-gen)
    midi/                         MIDI daemon
      tests/                      MIDI daemon tests
  scripts/
    deploy/deploy.sh              Deployment script (9 sections)
    test/                         Hardware test scripts
    stability/                    Stability test scripts
    launch/                       Application launch scripts
    drivers/                      Driver validation
      tests/                      Driver validation tests
  docs/
    architecture/                 Architecture documents (rt-audio-stack, web-ui, etc.)
    operations/safety.md          Safety manual — read before audio-producing operations
    lab-notes/                    Session lab notes (CHANGE, DEPLOY, OBSERVE)
    project/                      Status, decisions, assumptions, user stories
    guide/howto/                  This file and future HOWTOs
    theory/                       Design rationale, signal processing theory
```


## 7. Continuous Integration (US-070)

The project uses GitHub Actions for CI. The workflow is defined in
`.github/workflows/ci.yml`.

### 7.1 What Triggers CI

| Event | Scope | Behavior |
|-------|-------|----------|
| `push` | Any branch (`**`) | Runs on every push to any branch |
| `pull_request` | `main` branch | Runs on PR creation and each subsequent push |

A concurrency group (`ci-<ref>`) cancels in-progress runs when a newer commit
is pushed to the same branch, so you do not waste CI minutes on superseded
commits.

### 7.2 CI Jobs

CI runs two parallel jobs on `ubuntu-latest` (GitHub-hosted) runners:

| Job | What it runs | Typical duration |
|-----|-------------|-----------------|
| **`test-all`** | `nix run .#test-all` (web-ui unit, room-correction, midi, drivers, graph-manager via cargo), then individual Rust targets: `test-graph-manager`, `test-pcm-bridge`, `test-signal-gen` | 5-15 min |
| **`test-integration-browser`** | `nix run .#test-integration-browser` (Playwright browser tests against mock server) | 7-20 min |

Both jobs install Nix via `cachix/install-nix-action` and cache the Nix store
via `nix-community/cache-nix-action` (keyed on `flake.lock` hash). The first
run after a cache miss is slow (full Nix build); subsequent runs use cached
store paths.

### 7.3 Reading CI Results

- **GitHub PR page:** Check the "Checks" tab for per-job status.
- **GitHub Actions tab:** See full logs for each step.
- **Failed step:** Expand the failed step to see pytest or cargo test output.
  The test name and assertion message are usually sufficient to identify the
  failure.

### 7.4 Branch Protection

Branch protection on `main` requires both `test-all` and `test-integration-browser` to pass
before a PR can be merged. Force-push to `main` is disabled. Squash merge is
the default merge strategy (clean main history).

Workers create feature branches for their work (naming convention:
`<story-id>/<short-description>`, e.g., `us-064/graph-rework`), open PRs
against `main`, and merge only after CI passes.

### 7.5 Flaky Test Policy

A flaky test is a bug, not an inconvenience:

- **Do not** add retry logic or "re-run until green" workflows.
- **Do** file a defect and quarantine the test (`@pytest.mark.skip` with the
  defect ID) until fixed.
- CI failure on a flaky test blocks the PR until the test is fixed or properly
  quarantined.


## 8. Releases (US-132)

The project uses a tag-triggered release workflow to build SD card images and
publish them as GitHub Releases. The workflow is defined in
`.github/workflows/release.yml`.

### 8.1 Creating a Release

To create a release, push a `v*` tag to a commit on `main` that has passing CI:

```sh
git tag v2026.04.05
git push origin v2026.04.05
```

This triggers the release workflow, which:
1. Verifies the tagged commit has passing CI status (via GitHub API)
2. Builds the aarch64 SD card image (`nix build .#images.sd-card`)
3. Computes the SHA-256 checksum of the compressed image
4. Creates a GitHub Release with the image attached as a downloadable artifact

The release body includes the image filename, compressed size, SHA-256 checksum,
tag name, and commit SHA.

### 8.2 Tag Naming Convention

Tags must match the `v*` pattern. Two conventions are acceptable:

| Style | Example | When to use |
|-------|---------|-------------|
| Date-based | `v2026.04.05` | Regular releases tied to a session or date |
| Semantic | `v0.1.0`, `v1.0.0` | Milestone releases with clear versioning |

Tags must only be pushed to commits that have passed CI (T0+T1+T2+T3 green).
The release workflow checks CI status as a safety net, but the primary gate is
the PR merge process (Rule 13 + CI green).

### 8.3 Release vs CI

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| **CI** (`ci.yml`) | PR to `main`, manual dispatch | Runs tests (T0+T1+T2) and builds SD image (T3) to verify correctness |
| **Release** (`release.yml`) | `v*` tag push, manual dispatch | Builds SD image and publishes it as a GitHub Release artifact |

The release workflow does **not** re-run tests. It trusts that CI already
validated the tagged commit during the PR process.

### 8.4 Manual Dispatch (Testing)

The release workflow supports `workflow_dispatch` for manual triggering on any
branch. This is useful for testing the build without creating a tag or release.

Manual dispatch builds the SD image and uploads it as a **workflow artifact**
(available for 7 days from the Actions tab) instead of creating a GitHub Release.

To trigger manually: Actions tab > Release > Run workflow > select branch.

### 8.5 Where Artifacts Appear

| Trigger | Where to find the image |
|---------|------------------------|
| Tag push (`v*`) | GitHub Releases page — download from the release assets |
| Manual dispatch | GitHub Actions > workflow run > Artifacts section (7-day retention) |
