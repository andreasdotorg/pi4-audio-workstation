# Pi4 Audio Workstation — Team Configuration

## Work Management

- **Backend:** repo-local
- **State directory:** docs/project/

## Phases

- DECOMPOSE, PLAN, IMPLEMENT, TEST, REVIEW
- deploy-verify: **disabled** (no remote deployment — this is a local hardware project)

## Git Workflow

- **Branch model:** direct-to-main (single developer, personal project)
- **Commit conventions:** conventional commits, no Jira ticket references
  - Format: `type(scope): description`
  - Types: feat, fix, docs, refactor, test, chore
  - Scopes: dsp, pipewire, camilladsp, mixxx, reaper, midi, measurement, docs, team

## Roles

### Core Team (session-scoped — never shut down mid-session)

| Role | Agent Name | Category | Notes |
|------|-----------|----------|-------|
| Project Manager | project-manager | Coordination | Standard role |
| Change Manager | change-manager | Coordination | Standard role |
| Architect | architect | Advisory | Focuses on signal flow, module boundaries, DSP pipeline coherence |
| Live Audio Engineer | audio-engineer | Advisory | **Custom role.** Domain specialist for live sound, signal processing, event requirements. Part of approval process. |
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
| Config consistency | Manual review — CamillaDSP configs match documented channel assignments | Before commit |
| DSP correctness | Audio engineer reviews filter parameters, crossover design, latency budget | Before commit |
| Hardware validation | Test plan T1-T5 on actual Pi 4B hardware | Before deployment to hardware |
| Documentation accuracy | Technical writer verifies docs match implementation | Before commit |

## Documentation Suite

The technical writer maintains these deliverables:

| Document | Purpose | Location |
|----------|---------|----------|
| Introduction & Getting Started | Project overview, quick start for new readers | docs/guide/introduction.md |
| How-To Guides | Step-by-step procedures for setup and operations | docs/guide/howto/ |
| Complete Handbook | Comprehensive reference for all components | docs/handbook/ |
| Theory & Design | Requirements, signal processing theory, design rationale | docs/theory/ |
| Lab Notes | Experiment logs, measurement results, observations | docs/lab-notes/ |
