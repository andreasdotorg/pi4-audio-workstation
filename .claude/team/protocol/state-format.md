# Project State Formats

Canonical formats for stories, decisions, defects, and status. These apply
to the repo-local backend. Jira backend uses Jira's native formats but the
same concepts.

## User Story Format

```markdown
## US-NNN: Title

**As** [role],
**I want** [capability],
**so that** [benefit].

**Status:** draft | ready | selected | in-progress | in-review | done | deferred
**Depends on:** US-XXX (reason), US-YYY (reason)
**Blocks:** US-ZZZ (reason)
**Decisions:** D-NNN, D-MMM

**Acceptance criteria:**
- [ ] Criterion 1
- [ ] Criterion 2

**DoD:**
- [ ] Code written
- [ ] Statically validated (lint, types, syntax)
- [ ] Tested (unit, integration, E2E per project)
- [ ] Deployed and verified (if deploy-verify enabled)
```

### Status field definitions

| Status | Meaning | Actionable? | Who transitions |
|--------|---------|-------------|-----------------|
| draft | Story exists but AC not yet confirmed | No | PM creates |
| ready | AC confirmed, dependencies met | No — awaiting selection | PM updates |
| selected | Project owner approved for implementation | Yes | Project owner only |
| in-progress | Implementation started | Yes (continue) | PM updates |
| in-review | Delivered, awaiting sign-off + acceptance | No (changes frozen) | PM updates |
| done | All DoD pass, signed off, owner accepted | No | PM after owner acceptance |
| deferred | Explicitly postponed | No | Project owner only |

## Decision Format

```markdown
## D-NNN: Title (date)

**Context:** What prompted the decision.
**Decision:** What was decided.
**Rationale:** Why.
**Impact:** What changes as a result.
```

Append-only. Never edit a past decision — add a new one that supersedes it.

## Defect Format

```markdown
## BUG-NNN: Title (date opened)

**Severity:** critical | high | medium | low
**Status:** open | triaged | in-progress | fixed | verified | wont-fix | duplicate
**Found in:** component or file
**Affects:** US-NNN, DoD #N, or "standalone"
**Found by:** agent name, test, user report

**Description:** Observed vs. expected behavior.

**Root cause:** (when understood)

**Fix:** (when resolved) What was done. Commit hash or PR.

**Verified:** (when confirmed) How the fix was verified.
```

## Status File Format

```markdown
# Project Status

## Overall Status
[One-line summary: current work focus and health indicator]

## Component Status
| Component | Status | Version/Commit | Notes |
|-----------|--------|----------------|-------|
| [name] | [deployed/verified/failed/pending] | [hash] | [notes] |

## DoD Tracking
| Story | Score | Status |
|-------|-------|--------|
| US-NNN | X/Y | [in-progress/in-review/done] |

## In Progress
- [Item]: [brief description of current state]

## Blockers
| Blocker | Affects | Owner | Since |
|---------|---------|-------|-------|
| [description] | [story/task] | [who can resolve] | [date] |

## External Dependencies
| Dependency | Status | Contact | Notes |
|------------|--------|---------|-------|
| [what's needed] | [waiting/resolved] | [who] | [notes] |

## Key Decisions Since Last Update
- D-NNN: [title] (see decisions.md)
```
