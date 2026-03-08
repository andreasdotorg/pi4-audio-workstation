# Project Status

## Overall Status

Implementation underway. US-000 worker running (core software installation, ~2hr). US-000a partial complete (5/10 security findings resolved, 2 accepted risk, 2 deferred to CamillaDSP install). Validation-first approach: Tier 0/1 before UI work.

## Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| SETUP-MANUAL.md | draft | ~2200 lines, comprehensive but not yet validated on hardware |
| CLAUDE.md | current | Compaction survival rules, team listing, Pi state, owner preferences added |
| Team configuration | current | 10 core members, consultation matrix with 14 project-specific rules |
| Orchestration protocol | current | Self-contained copy in `.claude/team/protocol/` |
| Role prompts | current | All role files in `.claude/team/roles/` |
| User stories | active | 25 stories (US-000 through US-023 incl. US-000a) in `docs/project/user-stories.md` |
| CamillaDSP configs | draft | In SETUP-MANUAL.md, not yet tested on hardware |
| Room correction pipeline | not started | Stories US-008 through US-013 defined |
| Documentation suite | not started | Stories US-014 through US-016 defined |
| Web UI platform | not started | Stories US-022, US-023, US-018 defined (deferred per owner: validation first) |
| Core software (CamillaDSP, Mixxx, Reaper) | installing | US-000 worker running (~2hr estimated) |
| Platform security | partial | US-000a: firewall active, SSH hardened, rpcbind/ModemManager/CUPS disabled. CamillaDSP localhost binding deferred to US-000 completion. |

## DoD Tracking

| Story | Score | Status |
|-------|-------|--------|
| US-000 | 0/3 | in-progress (worker running, ~2hr) |
| US-000a | 2/4 | in-progress (partial: firewall+SSH+services done; CamillaDSP binding deferred) |
| US-004 | 0/3 | ready (independent, can run in parallel) |

## In Progress

- US-000: Core Audio Software Installation — worker running in background (~2hr estimated)
- US-000a: Platform Security Hardening — partial complete (5/10 findings resolved, 2 accepted risk, 2 deferred to CamillaDSP install: F-002 websocket, F-003 GUI localhost binding)
- Work sequence: US-000 completion -> US-000a remainder -> US-001/US-002 (parallel) -> US-003

## Blockers

None.

## External Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| Pi 4B hardware available for testing | available | SSH access verified, PipeWire running, all USB devices connected |
| Core software installation | in progress | US-000 selected, CamillaDSP/Mixxx/Reaper/RustDesk to be installed |
| Hercules DJControl Mix Ultra USB-MIDI verification | waiting | USB enumeration confirmed, functional MIDI test pending (US-005) |
| APCmini mk2 Mixxx mapping | waiting | Needs research / community check (US-007) |

## Key Decisions Since Last Update

- D-001: Combined minimum-phase FIR filters (2026-03-08)
- D-002: Dual chunksize — 2048 (DJ) vs 512 (Live) (2026-03-08)
- D-003: 16,384-tap FIR filters at 48kHz (2026-03-08)
- D-004: Two independent subwoofers with per-sub correction (2026-03-08)
- D-005: Team composition — Audio Engineer and Technical Writer on core team (2026-03-08)
- D-006: Expanded team — Security Specialist, UX Specialist, Product Owner; Architect gets real-time performance scope (2026-03-08)
