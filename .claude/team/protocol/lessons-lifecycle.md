# Lessons-Learned Lifecycle

Process for capturing, triaging, implementing, and retiring lessons learned.

**CRITICAL RULE: Record and move on.** When you discover a problem worth
documenting, record the lesson and CONTINUE YOUR CURRENT TASK. You do NOT
stop to implement the fix. The fix goes through the lifecycle below. This
prevents the "sidetracked into solving" anti-pattern — the agent's primary
task always takes priority over process improvement.

## Lifecycle

```
RECORD -> TRIAGE -> MITIGATE -> VERIFY -> ARCHIVE
  |                    |           |
  agent files it      PM assigns   AD/QE confirms
  and moves on        corrective   mitigation
                      actions      landed
```

## Stage Definitions

### 1. RECORD

**Who:** Any agent who encounters an incident, failure, or insight.
**When:** Immediately upon discovery.
**What:**
- File the lesson in the appropriate lessons-learned file:
  - Project-specific: `.claude/team/lessons-learned.md`
  - Global (cross-project): `.claude/team/protocol/global-lessons-learned.md`
- Required fields: date, context, what happened, root cause, corrective
  actions needed (specific: which document, what change).
- **Then return to your current task.** Do not implement the corrective
  actions. Do not research the fix. Do not refactor code. Record and move on.

**Output:** New L-NNN entry with status `RECORDED`.

### 2. TRIAGE

**Who:** Project Manager.
**When:** Session start (review new lessons) and session end (review lessons
filed this session).
**What:**
- Review each `RECORDED` lesson.
- For each corrective action, create a tracked item:
  - Assign to the responsible role (e.g., "Add PA-off gate to CM prompt"
    -> Architect or TW to draft, CM to review).
  - Link the tracked item back to the lesson ID.
- Update lesson status to `TRIAGED`.

**Output:** Corrective actions assigned with responsible agent and target
document identified.

### 3. MITIGATE

**Who:** Assigned agent (typically Architect, TW, or worker).
**When:** Scheduled by PM based on priority.
**What:**
- Implement the corrective action: edit the prompt, update the protocol,
  add the consultation matrix entry, fix the code.
- Link the implementation (commit hash or file + line) back to the lesson.
- Update lesson status to `MITIGATED`.

**Output:** Corrective action implemented and linked to lesson.

### 4. VERIFY

**Who:** AD or QE.
**When:** After mitigation is committed.
**What:**
- Confirm the mitigation actually landed in the specified document.
- Confirm the change matches what the lesson's corrective action required.
- If the mitigation is insufficient or misses the point, send back to
  MITIGATE with feedback.
- Update lesson status to `VERIFIED`.

**Output:** Sign-off that the mitigation matches the lesson's intent.

### 5. ARCHIVE

**Who:** TW or PM.
**When:** After verification.
**What:**
- Compress the lesson to a summary line in `active-mitigations.md`:
  `| L-NNN | one-line summary | governing rule/document reference |`
- Move the full narrative to `lessons-learned-archive.md`.
- Remove the full entry from the active lessons-learned file.
- Update lesson status to `ARCHIVED`.

**Output:** Summary in mitigations table, full text in archive.

## Lesson Status Values

| Status | Meaning |
|--------|---------|
| RECORDED | Filed by discovering agent. Corrective actions identified but not assigned. |
| TRIAGED | PM has reviewed and assigned corrective actions. |
| MITIGATED | Corrective action implemented and committed. |
| VERIFIED | AD/QE confirmed mitigation matches lesson intent. |
| ARCHIVED | Compressed to summary line. Full text in archive. |

## Responsibilities Summary

| Role | Responsibilities |
|------|-----------------|
| Any agent | RECORD lessons immediately. Then return to current task. |
| PM | TRIAGE new lessons. Assign corrective actions. Track completion. |
| Architect / TW / Worker | MITIGATE — implement assigned corrective actions. |
| AD / QE | VERIFY — confirm mitigations landed correctly. |
| TW / PM | ARCHIVE — compress to summary, move narrative to archive. |
