# Orchestrator Discipline Learnings

## Topic: Orchestrator must not do technical analysis or prescribe HOW (2026-03-29)

**Context:** The orchestrator analyzed a Nix build failure (x86_64 vs aarch64 mismatch) in detail, then told the worker what to do — including specific diagnosis and three numbered implementation steps. Separately, the orchestrator told worker-1 exact test implementation details (specific function calls, assert values) for an F-195 regression test instead of just saying "QE requires a regression test, coordinate with QE."

**Learning:** This is a Rule 2 violation. The orchestrator assigns WHAT, not HOW. When a build or tool failure occurs, the orchestrator should relay the failure notification to the responsible worker without analysis. The worker diagnoses and fixes it themselves, consulting the architect if needed. When relaying QE requirements, state WHAT is needed ("regression test required per QE") and let the worker coordinate with QE on specifics.

**Correct pattern:**
- Build failure: relay raw error to worker, worker diagnoses (consults architect if needed)
- QE requirement: "QE requires a regression test for F-195" — worker coordinates with QE on specifics
- Never: numbered implementation steps, specific function calls, diagnosis of root cause

**Source:** Orchestrator self-report / team lead relay
**Tags:** orchestrator-discipline, rule-2, token-efficiency, WHAT-not-HOW, delegation

## Topic: L-ORCH-003 — NEVER SKIP RULE 13. Shipping code without gate checks. (2026-04-04)

**Context:** During US-112 implementation, the orchestrator pushed 9 commits in a
single session without a single Rule 13 gate pass. The sequence: worker writes
code → architect approves design → CM commits and pushes → next task. QE was
brought in only AFTER everything was committed. PM's full accounting revealed:
**0 out of 5 active stories passed Rule 13 this session.** US-112, US-123,
US-125, US-126 all have committed code with no formal QE verification, no
formal architect sign-off, and no owner acceptance.

The version mismatch (PW 1.7.0 patch vs 1.4.9 build) was a downstream symptom:
if the gate process had been followed, QE would have caught the build failure
BEFORE the commit, not after. Instead, the broken patch was committed (`87a1eca`),
then fixed (`d09cba9`), burning two commits and a failed SD card build.

**Learning:** The orchestrator's primary job is PROCESS ENFORCEMENT, not velocity.
Rule 13 exists to prevent exactly this: shipping untested, unreviewed code.

**HARD RULES for commit flow:**
1. **No commit without FULL advisory review.** Every story needs sign-off from
   ALL FOUR advisory roles: Architect, UX, AE, AD. Plus QE verification.
   Not just architect + QE — the full panel. Every story, every time.
2. **No commit without QE sign-off.** QE must verify tests pass independently.
   "Worker says tests pass" is insufficient — QE must confirm.
3. **Build verification BEFORE commit, not after.** If the code changes a build
   (Nix overlay, patch, derivation), verify the build succeeds before committing.
   If it adds a flake output, verify `nix run` works before committing.
4. **The sequence is: implement → test → QE verify → all advisors approve →
   THEN commit.** Not: implement → commit → test → discover it's broken → fix →
   commit again.
5. **Velocity without gates is waste.** Every commit that needs a follow-up fix
   (like `87a1eca` → `d09cba9`) doubles the work and pollutes the git history.

**What went wrong specifically:**
- Orchestrator treated "architect reviewed the design" as "architect approved for commit"
- Orchestrator treated "worker says tests pass" as "QE verified"
- Orchestrator pushed commits the moment code was ready, without waiting for gates
- QE was consulted AFTER commits, not before — making QE review retroactive, not preventive

**Source:** Owner review of PM's Rule 13 accounting, session 9.
**Tags:** orchestrator-discipline, rule-13, gate-process, commit-flow, CRITICAL

## Topic: Verify target version before developing patches (2026-04-04)

**Context:** US-112 patch developed against PW 1.7.0 but NixOS build uses 1.4.9.
Different filename, directory, API, port layout. Required full regeneration.

**Learning:** Include target version in worker brief. Check `nix eval
nixpkgs#<pkg>.version` before assigning patch work. This was a downstream
consequence of skipping gates (L-ORCH-003) — build verification before commit
would have caught it.

**Source:** SD card build failure.
**Tags:** version-mismatch, patch-development, nixpkgs

## Topic: Story/status updates are PM/TW work, not worker work (2026-04-04)

**Context:** Assigned worker-3 to update `docs/project/stories/US-112.md` with
status changes. Owner corrected: "Why is a worker writing a status update, not
PM or TW?"

**Learning:** Documentation and status tracking have designated roles:
- Story status updates → PM
- Story content / prose → TW
- Workers do implementation work only
Assigning documentation tasks to workers bypasses the roles that exist specifically
for this purpose and wastes worker capacity.

**Source:** Owner correction, session 9.
**Tags:** orchestrator-discipline, role-assignment, pm, tw, workers
