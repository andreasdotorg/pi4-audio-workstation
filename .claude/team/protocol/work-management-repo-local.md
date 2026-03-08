# Work Management: Repo-Local Backend

Uses in-repo markdown files for all tracking. Best for: smaller projects,
experimental work, single-repo scope, rapid iteration.

## State Directory

Declared in project config.md as `State directory`. Typically `docs/project/`.

## Standardized Files

| File | Contents | Primary owner | Backstop |
|------|----------|---------------|----------|
| `status.md` | Current status, DoD scores, blockers, external deps | Project Manager | Orchestrator (session-end) |
| `decisions.md` | Binding decisions (D-001+) | Orchestrator | Project Manager |
| `user-stories.md` | Stories with AC, DoD, dependencies | Project Manager | — |
| `defects.md` | Defect log with severity, status, linked story | Project Manager | Orchestrator (session-end) |

Formats follow `~/mobile/gabriela-bogk/team-protocol/project-state/format.md`.

## Story Selection

The project owner moves stories from `ready` -> `selected` by editing the
file (or telling the orchestrator, who asks the PM to update).

## Status Tracking

`status.md` has these sections:
- **Overall Status** — one-line summary with current work and health
- **Component Status** — table of components and their state
- **DoD Tracking** — per-story DoD score (done/total)
- **In Progress** — items currently being worked on
- **Blockers** — items that cannot proceed (with reason and owner)
- **External Dependencies** — items requiring action outside the team
- **Key Decisions Since Last Update** — recent decisions (pointer to decisions.md)

## CLAUDE.md Integration

The project's CLAUDE.md should have a **Current Mission** section that points
to status.md for details. The Current Mission is a brief directive — details
live in status.md. This avoids duplication.

## Commit Workflow

Status file updates are committed through the Change Manager like any other
change. The PM is responsible for keeping files current. At session end, the
orchestrator verifies and backstops.
