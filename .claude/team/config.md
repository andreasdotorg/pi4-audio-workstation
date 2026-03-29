# mugge — Team Configuration

## Work Management

- **Backend:** repo-local
- **State directory:** docs/project/

## Phases

- DECOMPOSE, PLAN, IMPLEMENT, TEST, REVIEW
- deploy-verify: **enabled** (Pi deployment via SSH through change-manager)

## Git Workflow

- **Branch model:** direct-to-main (single developer, personal project)
- **Commit conventions:** conventional commits, no Jira ticket references
  - Format: `type(scope): description`
  - Types: feat, fix, docs, refactor, test, chore
  - Scopes: dsp, pipewire, filter-chain, graph-manager, signal-gen, level-bridge, mixxx, reaper, midi, measurement, web-ui, nix, docs, team
  - **Co-author line:** `Co-Authored-By: Claude <noreply@anthropic.com>` — no model version

## Roles

### Core Team (session-scoped — never shut down mid-session)

| Role | Agent Name | Category | Notes |
|------|-----------|----------|-------|
| Product Owner | product-owner | Coordination | **Custom role.** Translates owner inputs into structured stories with AC. |
| Project Manager | project-manager | Coordination | Standard role |
| Change Manager | change-manager | Coordination | Standard role |
| Architect | architect | Advisory | Focuses on signal flow, module boundaries, DSP pipeline coherence, **real-time performance on constrained hardware** |
| Live Audio Engineer | audio-engineer | Advisory | **Custom role.** Domain specialist for live sound, signal processing, event requirements. Part of approval process. |
| Security Specialist | security-specialist | Advisory | Standard role, **scoped to availability/integrity for live performance.** Threat model: casual attackers, venue networks, service exposure. Not nation-state. |
| UI/UX Specialist | ux-specialist | Advisory | **Custom role.** Interaction design across MIDI controllers, headless ops, displays, web UIs, remote access. |
| Technical Writer | technical-writer | Advisory | **Promoted to core.** Maintains comprehensive technical documentation suite. Part of approval process for documentation accuracy. |
| Quality Engineer | quality-engineer | Quality | Standard role. For this project: test plans focus on hardware validation, latency measurements, CPU benchmarks |
| Advocatus Diaboli | advocatus-diaboli | Challenge | Standard role |

### Workers (task-scoped — spawn and retire as needed)

| Role | Agent Name | Notes |
|------|-----------|-------|
| Worker | worker-N | Implementation workers, spawned per task |
| Researcher | researcher | On-demand for upstream docs, hardware specs, library APIs |

## Validation Rules

This project targets a Raspberry Pi 4B running Raspberry Pi OS Trixie. Most
validation is hardware-dependent and cannot be run in CI. Validation categories:

| Category | Method | When |
|----------|--------|------|
| Script syntax | `bash -n` / `python -m py_compile` | Before commit |
| YAML validity | `python -c "import yaml; yaml.safe_load(open(...))"` | Before commit |
| Config consistency | Manual review — PipeWire filter-chain config matches documented channel assignments | Before commit |
| DSP correctness | Audio engineer reviews filter parameters, crossover design, latency budget | Before commit |
| Hardware validation | Test plan T1-T5 on actual Pi 4B hardware | Before deployment to hardware |
| Documentation accuracy | Technical writer verifies docs match implementation | Before commit |

## Test Suite Mapping (Gate 1)

Workers must run the relevant `nix run .#test-*` suite(s) before reporting
a task complete. `nix run` is THE QA gate for workers. `nix develop` is
acceptable only for ad-hoc exploratory testing during development.

| Change category | Required suites |
|----------------|----------------|
| Web UI backend (`src/web-ui/app/`) | `nix run .#test-unit` |
| Web UI frontend (`src/web-ui/static/`) | `nix run .#test-unit` + `nix run .#test-e2e` |
| Web UI backend + frontend | `nix run .#test-unit` + `nix run .#test-e2e` |
| Room correction (`src/room-correction/`) | `nix run .#test-room-correction` |
| GraphManager Rust (`src/graph-manager/`) | `nix run .#test-graph-manager` |
| pcm-bridge Rust (`src/pcm-bridge/`) | `nix run .#test-pcm-bridge` |
| signal-gen Rust (`src/signal-gen/`) | `nix run .#test-signal-gen` |
| MIDI daemon (`src/midi/`) | `nix run .#test-all` |
| Driver YAMLs (`configs/drivers/`) | `nix run .#test-all` (includes driver validation) |
| PW/WP configs, systemd, udev | No local test — note "requires Pi validation" |
| Multiple categories | All relevant suites from above |

**Key rules:**
- Changes to BOTH frontend and backend require BOTH `test-unit` AND `test-e2e`
- Config-only changes (PipeWire, WirePlumber, systemd, udev) have no local
  test — mark "requires Pi validation" for Gate 2.
- When in doubt whether E2E is needed, run E2E.

### Gate 2: Pi Hardware Validation (QE owns)

**Trigger:** Story-closing commits and batched fix commits (3+ related
defects). Single-defect fixes and doc-only commits need only Gate 1.

Hardware-specific validation per story test plan. Requires CM DEPLOY session.
QE defines criteria (standard + per-story checklist), worker executes on Pi,
QE reviews evidence and signs off.

### Gate 3: Owner Acceptance (PM tracks)

Sub-step of REVIEW phase. Owner performs hands-on Pi verification. PM records
outcome in DoD tracking table. Max 3 stories in acceptance queue at a time.

See `docs/project/testing-process.md` Section 8 for full gate definitions.

## Deployment Target

| Property | Value |
|----------|-------|
| Name | Pi audio workstation |
| Type | Embedded device (Raspberry Pi 4B) |
| Access mechanism | SSH (`ela@192.168.178.185`, hostname: mugge) |
| Auth | Key-based, passwordless sudo |
| Access controller | Change Manager |
| OBSERVE timeout | 10 minutes |
| CHANGE/DEPLOY unresponsive timeout | 5 minutes |

See `protocol/deployment-target-access.md` for the three-tier access protocol
(OBSERVE/CHANGE/DEPLOY).

## Deploy-Verify Protocol

All deployments go through the Change Manager's deployment target session
protocol (DEPLOY tier). Workers execute deployment under a CM-granted session
(the CM grants/revokes sessions and commits results, workers execute on Pi).

### What gets deployed

| Artifact | Repo source | Pi destination |
|----------|-------------|----------------|
| PW filter-chain config | `nix/pipewire/` | `/etc/pipewire/pipewire.conf.d/` or `~/.config/pipewire/pipewire.conf.d/` |
| FIR coefficient WAVs | `coeffs/` | `/etc/pi4audio/coeffs/` |
| GraphManager service | `services/graph-manager/` | systemd user service |
| Signal-gen service | `services/signal-gen/` | systemd user service |
| Level-bridge service | `services/level-bridge/` | systemd user service |
| Web UI | `web-ui/` | `/opt/mugge/web-ui/` |
| PipeWire quantum config | `nix/pipewire/` | `~/.config/pipewire/pipewire.conf.d/10-audio-settings.conf` |
| Deploy/test scripts | `scripts/` | `/home/ela/bin/` or `/tmp/` |

### Deploy procedure

1. **Commit first.** All changes must be committed to the repo before deployment.
   The deployed commit hash is recorded in the lab note.

2. **Worker executes under CM session.** The worker holding a DEPLOY session
   transfers files to the Pi via scp/rsync and sets permissions.

3. **Set permissions.** Scripts get `chmod +x`. System configs owned by root
   where required (`/etc/pipewire/`, `/etc/pi4audio/`).

4. **Record.** Worker notes in lab notes: what was deployed, from which commit,
   to which path.

### Verify checklist

After deployment, the worker runs these checks (proportionate to what changed):

**PipeWire filter-chain config deployed:**
- [ ] PipeWire running at correct priority: `chrt -p $(pidof pipewire)` → SCHED_FIFO 88
- [ ] Convolver node loaded: `pw-cli ls Node | grep convolver`
- [ ] FIR files loaded: check convolver node properties for correct WAV paths
- [ ] No PipeWire crash loop: `systemctl --user status pipewire` = active

**Audio flow verification:**
- [ ] Audio flows: app → PipeWire filter-chain convolver → USBStreamer (no Loopback, no CamillaDSP)
- [ ] No xruns after 60s: `pw-top` or journal
- [ ] Quantum correct for mode: `pw-metadata -n settings 0 clock.force-quantum`

**Service deployed (GraphManager, signal-gen, level-bridge):**
- [ ] Service running: `systemctl --user status <service>`
- [ ] GraphManager responsive: `curl localhost:4002/health`
- [ ] Level-bridge responsive: `curl localhost:9100/levels` (if level-bridge)

**Script deployed:**
- [ ] `bash -n <script>` or `python -m py_compile <script>` — syntax valid
- [ ] Script runs without error in dry-run or short test

**Full system (after major changes):**
- [ ] PipeWire + filter-chain convolver + application (Mixxx or Reaper) all running
- [ ] Audio flows end-to-end: application → PipeWire filter-chain → USBStreamer
- [ ] GraphManager managing link topology
- [ ] No xruns for 60 seconds
- [ ] Temperature stable (not climbing toward 75C)

### Rollback

Rollback is manual: re-deploy the previous version of the affected file(s) from
the repo's git history. For PipeWire filter-chain config, restart PipeWire after
restoring the file. For services, redeploy and restart the systemd unit.

There is no automated rollback — the blast radius is one Pi running a personal
project. The change-manager maintains a record of what was deployed in case
rollback is needed.

### What does NOT need deploy-verify

- **Documentation-only changes** (lab notes, CLAUDE.md, user-stories.md) — no Pi deployment
- **FIR filter WAVs** — generated by the room calibration pipeline, verified by the pipeline's own verification measurement (design principle #7)
- **Reaper project files** — created interactively on the Pi, not version-controlled

## Documentation Suite

The technical writer maintains these deliverables:

| Document | Purpose | Location |
|----------|---------|----------|
| Introduction & Getting Started | Project overview, quick start for new readers | docs/guide/introduction.md |
| How-To Guides | Step-by-step procedures for setup and operations | docs/guide/howto/ |
| Complete Handbook | Comprehensive reference for all components | docs/handbook/ |
| Theory & Design | Requirements, signal processing theory, design rationale | docs/theory/ |
| Lab Notes | Experiment logs, measurement results, observations | docs/lab-notes/ |
