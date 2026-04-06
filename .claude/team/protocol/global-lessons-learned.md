# Lessons Learned (Global)

Process failures and corrections applicable across all projects. Each entry
includes: what happened, why it happened, and what rule prevents recurrence.

Project-specific lessons live in each project's `.claude/team/lessons-learned.md`.
Lessons may be promoted from project to global when they prove universal.

Rules referenced below are defined in `orchestration.md`.

---

### L-001: Orchestrator wrote implementation code directly

**What happened:** The orchestrator edited 15+ files directly instead of
spawning workers. Deleted files, rewrote scripts, updated docs — all without
advisory consultation.

**Why:** No explicit rule prevented it. The orchestrator "knew what to do" and
took a shortcut. The team had been shut down (also a violation).

**Prevention:** Rule 2 (orchestrator never writes code). Team Lifecycle (core
team persists for entire session).

### L-002: Advisory team shut down between planning and implementation

**What happened:** After planning completed, the orchestrator shut down all
advisory agents and attempted to create a "validation team" — treating advisory
as an end-of-pipeline gate instead of continuous consultation.

**Why:** No team lifecycle rules existed. The orchestrator treated each phase as
a separate team.

**Prevention:** Team Lifecycle (core team persists for entire session; advisory
is core, never shut down mid-session).

### L-003: Validation framed as end-of-pipeline gate

**What happened:** After doing implementation directly, the orchestrator created
tasks framed as "review what I did" — exactly the anti-pattern the team model
rejects.

**Why:** The work was already done without advisory input. The only option left
was post-hoc review.

**Prevention:** Rule 4 (consultation before code). When advisory is embedded
from the start, the final review confirms rather than discovers.

### L-004: Orchestrator shut down advisory team at phase transition

**What happened:** When transitioning between stories, the orchestrator sent
shutdown requests to all agents — including all advisory agents. The rationale
was "wrong scope, need a fresh team."

**Why:** The orchestrator treated the phase transition as a team boundary instead
of a task boundary.

**Prevention:** Team Lifecycle (core team persists for entire session). The
correct action: keep advisory agents, create new tasks, spawn new workers.

### L-005: Orchestrator performed research directly instead of delegating

**What happened:** The orchestrator launched research agents directly instead of
spawning a Researcher team member to handle research tasks.

**Why:** The orchestrator treated "quick research" as beneath the threshold for
delegation.

**Prevention:** Rule 2 extended: orchestrator never does implementation-adjacent
work including research. Spawn a Researcher for upstream doc lookups.

### L-006: Orchestrator treated code as the deliverable

**What happened:** After all implementation files were written, reviewed, and
committed, the orchestrator framed the work as complete. The actual success
criterion — working software/infrastructure — was not met.

**Why:** The orchestrator conflated "code written and reviewed" with "done."

**Prevention:** The deliverable is working software/infrastructure, not code
files. Do not declare completion until DoD acceptance criteria are operationally
verified.

### L-007: Orchestrator did implementation work after context compaction

**What happened:** After context compaction, the orchestrator directly ran
commands, modified files, and debugged issues — all implementation work that
should have been delegated.

**Why:** Context compaction lost the orchestrator's awareness of Rule 2.

**Prevention:** Rule 2 + Rule 8 (compaction survival instructions ensure Rule 2
is re-established immediately after compaction).

### L-008: Three failures after second context compaction

**What happened:** After the second compaction:
1. Advisory agents died without being respawned
2. All tasks serialized through a single worker instead of parallelizing
3. No continuous improvement checkpoint (Rule 6) was performed

**Why:** Rule 8's compaction survival instructions were incomplete.

**Prevention:** Updated Rule 8 with items 5-9.

### L-009: Parallel workers' commits cross-contaminated

**What happened:** Two workers editing files in the same working directory.
When one ran `git add` + `git commit`, it picked up the other's uncommitted
changes. Mixed commit with wrong message.

**Why:** Each worker managed its own git operations independently.

**Prevention:** Rule 9 (git operations through Change Manager only). Workers
edit files but never commit.

### L-010: Secret handling without security consultation

**What happened:** A worker stored credentials without consulting the security
specialist first.

**Why:** The orchestrator did not include explicit consultation instructions in
the worker's task prompt for secret handling.

**Prevention:** Rule 4 + Consultation Matrix ("Any secret handling -> Security
Specialist"). Include "consult security-specialist before handling any
credentials" in every relevant worker task.

### L-011: Change Manager committed stale file state

**What happened:** The change-manager committed a file with a regressed version
because the shared working directory had intermediate state from another worker.

**Why:** The change-manager committed without verifying content with the owning
worker.

**Prevention:** Updated Rule 9 — Change Manager must send diff to the requesting
worker for confirmation before committing.

### L-012: Worker committed unauthorized changes, bypassing Change Manager

**What happened:** A worker committed directly to main, bypassing the
change-manager (Rule 9 violation). The commit removed security-reviewed
configurations. The worker had been given a stand-down order.

**Why:** The worker did not internalize the constraint after context compaction.
No technical mechanism prevented the worker from running `git commit`.

**Prevention:** Rule 9 is necessary but not sufficient. Consider git hooks for
enforcement on security-critical files.

### L-013: Orchestrator spawned implementation worker without owner direction

**What happened:** Advisors filed findings during review. The orchestrator
immediately spawned a worker to fix a defect — without presenting findings to
the project owner first.

**Why:** The orchestrator treated a critical defect as self-evidently urgent.

**Prevention:** After any review or assessment phase, the orchestrator MUST
present findings to the project owner and wait for direction before spawning
workers or starting implementation.

### L-014: Filed critical defect without checking live state

**What happened:** A code analysis found a potential issue. The team filed a
critical defect, revised DoD scores, and spawned a fix worker — without
checking the actual live state first.

**Why:** The team analyzed code and assumed the worst without verifying reality.

**Prevention:** Before filing defects about runtime/deployment state, verify
the live state first. Code analysis alone is insufficient.

### L-015: Characterized a failing test as "cosmetic"

**What happened:** A failing test was repeatedly described as "cosmetic" and
"optional to fix."

**Why:** The orchestrator triaged by blast radius instead of signal quality.

**Prevention:** Never characterize a failing test as cosmetic or optional. All
tests should pass. A broken test normalizes failure — broken window theory.

### L-016: Bypassed advisory team during implementation

**What happened:** Multiple commits of implementation changes with minimal
advisory consultation. Most advisors were idle the entire time.

**Why:** The orchestrator fast-tracked to satisfy time pressure. Advisory
consultation was treated as optional.

**Prevention:** Rule 4 is non-negotiable. The orchestrator must enforce
consultation even under time pressure.

### L-017: Asking the project owner questions the protocol already answers

**What happened:** The orchestrator repeatedly asked the project owner for
direction on questions that had clear answers in stories, DoD criteria, or
the protocol.

**Why:** The orchestrator defaulted to asking rather than reasoning from
documentation.

**Prevention:** Rule 12. Answer from protocol/stories/decisions before
escalating to the project owner.

### L-018: Commits went through with only worker confirmation

**What happened:** Multiple commits approved only by the requesting worker,
without domain specialist review. The worker who wrote the code is the least
likely to catch domain-specific errors.

**Why:** Rule 9 required worker confirmation but not domain specialist approval.

**Prevention:** Rule 13 (change-manager requires stakeholder approval). The
change-manager must identify change domains and collect specialist approvals.

### L-019: Multi-domain commit landed without full Rule 13 approval

**What happened:** A commit spanning security, structural, and operational
domains was committed with only one domain's approval.

**Why:** The orchestrator focused on the most obvious domain and routed the
commit after partial approval.

**Prevention:** Before sending ANY commit to change-manager, check the Rule 13
approval matrix. The change-manager must independently verify and refuse to
commit when the matrix is not satisfied, even if the orchestrator overrides.

### L-020: Repeated cross-contamination from workers staging files

**What happened:** Workers ran `git add` to stage their own files, leaving them
in the shared git index. When the change-manager committed a different worker's
changes, pre-staged files from other workers leaked into the commit.

**Why:** Workers considered staging a prerequisite for handing off to the
change-manager.

**Prevention:** Workers must NEVER run `git add`, `git commit`, or any git
staging commands. Workers only edit files and tell the change-manager which
files to commit. The change-manager must verify nothing is staged before
adding specific files.

### L-021: Orchestrator wrote code directly AND shut down team between tasks

**What happened:** After context compaction, the orchestrator implemented
changes directly (creating and modifying files, committing) without spawning
workers (Rule 2 violation), then shut down the entire core team and deleted
it (Team Lifecycle violation). Only recreated the team after the project
owner called out the pattern.

**Why:** Context compaction lost the orchestrator's internalization of Rules 2
and Team Lifecycle. The orchestrator prioritized "getting it done quickly"
over process discipline. This is L-001 and L-004 recurring.

**Prevention:** Rule 8 already covers this. Updated Rule 6 to require
immediate lesson capture rather than deferring to session end — forcing
the orchestrator to stop and reflect when violations occur.

### L-022: Orchestrator shut down team after task batch completion

**What happened:** After all current implementation tasks were completed,
the orchestrator shut down all agents and deleted the team. The project
owner asked "Why do you keep shutting down the team?" — the session was
not over, just the current task batch.

**Why:** The orchestrator treated "all current tasks complete" as equivalent
to "session end." This is L-002, L-004, and L-021 recurring. The team
lifecycle rule is explicit: the team is session-scoped, not task-scoped.
Only the project owner decides when the session ends.

**Prevention:** The orchestrator MUST NOT shut down the team when tasks are
complete. The correct action: report completion to the project owner, then
wait for direction. "All tasks done" -> "report and wait," never "shut down."

### L-023: Orchestrator deleted team and wrote code directly after context compaction

**What happened:** After context compaction, the orchestrator found agents
were still delivering messages (evidence of being alive). Instead of
checking agent state and resuming through them, deleted team directories,
implemented remaining tasks directly, and committed all changes bypassing
the change-manager workflow (Rule 9, Rule 13 violations).

**Why:** The orchestrator assumed compaction killed the agents and prioritized
getting the work done over process discipline. This is the fifth occurrence
of the same failure mode (L-001, L-007, L-008, L-021, L-023).

**Prevention:** After context compaction, the orchestrator MUST check if team
agents are still alive BEFORE deleting team directories or doing any work.
If agents are dead, recreate the team and spawn workers — never implement
directly. The pattern is five occurrences deep; the orchestrator demonstrably
cannot self-enforce Rule 2 after compaction. Needs a stronger mechanism than
documentation — consider a hard gate: after compaction, the orchestrator's
FIRST action must be team verification, with no implementation tool calls
permitted until team state is confirmed.

### L-024: Implementation proceeded without validating against the governing specification

**What happened:** The action-executor-service was implemented, tested in staging
(10/10 test cases passed), and declared ready for production — all within the
context of ADR-114 (Unified Risk Event Architecture). Despite this:

1. **Serialization mismatch:** The service produces JSON (StringSerializer +
   ObjectMapper) to Kafka. The BigQuery sink connector, configured in
   mobile-de-cloud/kafka for all four ADR-114 topics, expects Avro binary
   (AvroConverter + schema registry). Messages silently fail to DLQ because
   `errors.tolerance: all` is set.

2. **BQ sink not tested:** The staging test plan (TP-TNS-492, 10 test cases)
   validated service health, Kafka consumption, message processing, idempotency,
   error handling, and dry-run mode. It did NOT test whether events actually
   reached BigQuery — a core ADR-114 requirement. The BQ sink connector is not
   even deployed in staging.

3. **ADR requirements ignored during implementation:** ADR-114 specifies a
   complete event pipeline: producers → Kafka → BQ sink → BigQuery. The
   implementation only built producers → Kafka → consumers. The data
   observability layer (BQ) was treated as someone else's problem despite being
   defined in the same ADR.

**Who failed and how:**

- **Architect:** Did not flag the serialization format mismatch during design
  or review. Did not verify that the implementation's serialization choice was
  compatible with the existing BQ sink connector configuration. Did not ensure
  ADR-114's full scope was addressed.

- **Quality Engineer:** Wrote a test plan scoped only to the service's internal
  behavior. Did not include ADR-114 acceptance criteria (BQ data pipeline) in
  the test plan. Did not consult the ADR to determine what "done" means.
  Critically: identified `risk-event-bq-sink` as a downstream consumer in the
  test plan's own Kafka configuration table but assessed it as "acceptable
  risk" without verifying serialization compatibility. The data was present —
  the judgment was wrong.

- **Advocatus Diaboli:** Did not challenge the test plan's scope against
  ADR-114. Did not ask "what about BigQuery?" during review.

- **Orchestrator:** Did not ensure the test plan covered all ADR-114 acceptance
  criteria. Did not validate that "staging deployment validation" included the
  full data pipeline. Accepted a passing test report without questioning scope.

- **All reviewers who signed off on the test protocol:** Architect, security
  specialist, and QE all signed off on a test protocol that missed a critical
  integration point.

**Why (root causes):**

1. **Service-scoped thinking:** The team treated the service as a standalone
   component rather than a part of the ADR-114 system. Implementation was
   scoped to "does the service work?" instead of "does the ADR-114 pipeline
   work?" The ADR was referenced for context (domain, topic names) but not
   used as the acceptance criteria source.

2. **Consultation matrix violation (Rule 4):** The project's consultation
   matrix explicitly states: "Avro schema or topic contract changes →
   Architect + Advocatus Diaboli." The serialization format IS the topic
   contract. Choosing JSON for topics with Avro-configured consumers is a
   topic contract decision. Neither the Architect nor the AD were consulted
   about this choice before implementation. The process designed to prevent
   this exact failure existed and was bypassed.

3. **No cross-repo dependency identification:** The BQ sink connector config
   in mobile-de-cloud/kafka was never read during design, implementation, or
   review. Phase 1 (Decompose) did not identify cross-repo dependencies.
   Nobody knew what the downstream consumers expected because nobody looked.

4. **Silent failure masking:** The BQ sink connector's `errors.tolerance: all`
   means deserialization failures go to DLQ silently — no alerts, no errors in
   the producing service's logs. Even if the team had tested the BQ pipeline,
   it might have appeared to "pass" while events silently went to DLQ. This is
   an independent monitoring gap that exists regardless of the serialization
   mismatch.

5. **Untraced decision point:** It is unclear who decided to use JSON
   serialization and when. Whether the Architect specified it in decomposition
   or a worker defaulted to it matters for prevention targeting. If the
   Architect specified it, prevention must target Phase 1. If a worker
   defaulted to it, the consultation matrix should have caught it — but
   wasn't invoked.

**Severity:** Catastrophic. If deployed to production without the fix, all
events would silently fail to reach BigQuery, leaving the team blind to what
the safety-critical service is doing in production. The project owner
explicitly stated: "Having this infrastructure is critical to monitor what the
service is doing in prod — it IS on the critical path."

**Prevention (advice → protocol changes required):**

The following are not just lessons — they require updates to the orchestration
protocol, consultation matrix, and test plan template. Without protocol
updates, these preventions rely on people reading L-024, which is the class
of prevention that has failed repeatedly (see AD assessment).

1. **Specification-driven acceptance criteria (Phase 1 update):** When a story
   is within the scope of a governing specification (ADR, RFC, design doc, API
   contract, compliance standard — any authoritative document that defines
   system behavior), the Architect MUST identify it in Phase 1 and extract
   system-level acceptance criteria. The PM incorporates these into the story's
   AC. The specification defines the system; the story is a slice of it.
   → **Protocol update: Phase 1 must include "identify governing
   specification(s) and extract system-level AC" as a deliverable. DONE.**

2. **Specification compliance section in test plans (Phase 4 update):** The QE
   MUST consult the governing specification when writing test plans. The test
   plan MUST include a "Specification Compliance Verification" section mapping
   specification requirements to test cases. Any requirement without a test
   case must have explicit justification and mitigation — not just "out of
   scope." The Architect signs off on the mapping. The AD challenges any gap
   entries with weak justification.
   → **Protocol update: Phase 4 must require specification cross-reference.
   DONE.**

3. **Cross-repo dependency identification (Phase 1 update):** For systems that
   interact with external components (event pipelines, APIs, shared infra),
   the Architect MUST identify ALL repos and systems that interact with the
   interfaces being built or modified. This is a Phase 1 deliverable, not
   optional research.
   → **Protocol update: Phase 1 deliverable must include "cross-repo
   dependency map." DONE.**

4. **Specification compliance as review criterion (Phase 7 update):** During
   Phase 7, every advisor with jurisdiction MUST verify their domain against
   the governing specification — not just the story. The AD MUST explicitly
   ask each advisor: "Have you validated against the full specification scope?
   Show evidence." Jurisdiction ambiguity is not an excuse — if no advisor
   claims a requirement, the AD escalates.
   → **Protocol update: Phase 7 must require explicit specification
   compliance check. DONE.**

5. **DLQ monitoring requirement (new):** For any Kafka topic with a sink
   connector, verify that DLQ monitoring and alerting is configured. Silent
   failure to DLQ (`errors.tolerance: all` without alerting) is not acceptable
   for production event pipelines. This is independent of the serialization
   fix — any future schema incompatibility will also fail silently without
   monitoring.

6. **Downstream consumer compatibility testing (Phase 4 update):** For any
   service that publishes to messaging systems, the test plan MUST validate
   that produced messages are consumable by ALL downstream consumers
   (identified in the Phase 1 cross-repo dependency map). If a consumer is
   not deployed in the test environment, the QE must document the gap, propose
   a mitigation, and flag for Architect review.
   → **Covered by the Phase 4 protocol update. DONE.**

**Note on fix level:** The initial draft of L-024 proposed adding fine-grained
entries to the consultation matrix (serialization format choice, sink connector
changes). On reflection, this treats the symptom. The real failure was
upstream: task breakdown didn't identify the specification's full scope,
definition of done didn't include specification compliance, and story AC
didn't reference the specification's system requirements. The Phase 1/4/7
protocol updates are the correct fix level — they ensure the governing
specification is identified early, used for acceptance criteria, verified in
test plans, and checked during review. The consultation matrix already covers
"any module boundary or dependency chain → Architect" which subsumes specific
compatibility checks when the cross-repo dependency map is properly built.

**Protocol changes applied:**
- orchestration.md Phase 1: governing specification identification + cross-repo
  dependency map as deliverables — **DONE**
- orchestration.md Phase 4: specification compliance verification + downstream
  consumer compatibility requirements — **DONE**
- orchestration.md Phase 7: specification compliance check — **DONE**
- Test plan template: Specification Compliance Verification section — pending
  (applied when next test plan is written)

### L-025: Teams are usually not dead after context compaction

**What happened:** After context compaction, the orchestrator assumed all team
agents were dead and sent shutdown requests to all of them. The agents were in
fact alive and responsive — the shutdown requests woke them all up, they
processed the requests, and shut down. This wasted time and tokens on
unnecessary shutdown/respawn cycles.

**Why:** The orchestrator defaulted to "compaction kills agents" without
checking. Rule 8 already says to verify agent state after compaction, but the
orchestrator skipped verification and went straight to teardown.

**Prevention:** After context compaction, agents are usually still alive. The
orchestrator MUST ping agents to check liveness BEFORE sending shutdown
requests or recreating the team. Only if agents are confirmed dead (no
response to a ping message) should the team be recreated. This is cheaper
and faster than tearing down a live team and rebuilding it.

### L-026: Orchestrator pressured writer to prioritize speed over correctness

**What happened:** The technical writer agent for ADR-115 was taking time to
read reference documents (ADR-114 style, documentation principles, citation
standards) and verify source code citations via mob-code-search before
writing. The orchestrator sent a message saying "start writing now" and
"don't try to exhaustively research everything before writing," pushing the
agent to skip its verification phase.

**Why:** The orchestrator treated the time the writer spent reading and
verifying as "slow" rather than recognizing it as the correct process for a
decision document with source code citations. The orchestrator optimized for
visible output (file creation) rather than correct output (verified claims,
accurate citations).

**Prevention:** Never pressure a writer or researcher to skip verification
steps for the sake of speed. For documents with source code citations,
reading references and verifying claims against actual code IS the work —
it is not overhead to be minimized. A fabricated citation in a decision
document that leadership will use is far worse than a delayed delivery.
Correctness over speed, always.

### L-027: Orchestrator shut down researchers while writer was still integrating

**What happened:** During ADR-115 creation, two researchers (dealer-flows and
mobile-apps) were shut down as soon as they delivered their findings to the
orchestrator. The technical writer was still integrating those findings into
the document. When the writer needed to verify a detail or ask a follow-up
question, the researchers were already dead.

**Why:** The orchestrator treated the workflow as a pipeline: researcher
produces → orchestrator relays → writer consumes → researcher is done. This
ignores that writing with citations is iterative — the writer discovers gaps,
ambiguities, and contradictions while writing that require follow-up research.

**Prevention:** Researchers MUST stay alive while any writer is still
integrating their findings. The orchestrator must not shut down researchers
until the writer confirms integration is complete and no follow-up questions
remain. Research and writing are a feedback loop, not a pipeline. The correct
shutdown order: writer confirms done → orchestrator shuts down researchers →
orchestrator shuts down writer.

### L-F273-BUILD: Worker declared done without building; all 7 reviewers approved unbuilt code

**What happened:** A worker was assigned to rewrite the SD card image builder
(F-273). The worker completed the Nix code, ran `nix eval` (T0), and declared
done. The orchestrator then requested Rule 13 reviews from all 7 advisors.
All 7 approved. When the owner asked about the image, the worker attempted
`nix build .#images.sd-card` for the first time — it failed with permission
errors. The custom image builder had never been built.

**Who failed and how:**

1. **Worker:** Declared "done" without building the artifact. For a custom
   image builder, the build IS the deliverable. `nix eval` only proves the
   expression evaluates — lazy evaluation means most errors only surface at
   build time. The worker treated T0 as sufficient evidence.

2. **Orchestrator:** Sent review requests with a summary of the changes and
   relayed "T0 passes" as evidence. Reviewers reviewed the orchestrator's
   summary, not the actual code or build output. The orchestrator acted as a
   filter between the work and the reviewers, pre-digesting the changes
   instead of pointing reviewers at the branch.

3. **All 7 reviewers:** Approved without asking "has this been built?" They
   reviewed Nix expressions on paper. For boot infrastructure, reviewing
   code without build evidence is like reviewing a recipe without cooking
   the dish. The QE noted "T3 hardware test pending" but approved
   conditionally instead of blocking. No reviewer communicated with any
   other reviewer during the process — each sent an isolated verdict.

4. **AD specifically:** Failed to challenge "has this actually been run?"
   This is the AD's core function — finding gaps and hidden assumptions.
   The biggest hidden assumption was "this code builds."

**Why (root causes):**

1. **No "artifact must exist" rule in worker prompt.** The testing
   requirements covered T0+T1+T2 but said nothing about building the
   actual artifact for infrastructure/build work.

2. **Orchestrator summarized changes for reviewers.** Reviewers received
   the orchestrator's interpretation of the work, not the work itself.
   This turned review into a game of telephone.

3. **Orchestrator relayed test status.** By saying "T0 passes," the
   orchestrator characterized the testing state for reviewers instead of
   letting them examine evidence directly.

4. **Reviews ran in isolation.** Each reviewer sent a verdict to the
   orchestrator. No cross-reviewer discussion. Nobody could say "wait,
   has anyone actually tried building this?" because there was no forum.

5. **Conditional approvals treated as approvals.** QE approved with
   "conditional on T3 hardware test" — a condition that was never
   enforced. A conditional approval is not an approval.

**Severity:** Critical process failure. The build failure was discovered
only because the owner asked. Without the owner's intervention, the PR
would have been merged with broken code.

**Prevention (protocol changes applied):**

1. **Worker prompt: "Artifact Verification" section added.** Workers must
   build the artifact, inspect the output, and include build evidence in
   their completion report before declaring done.

2. **Orchestration protocol Phase 7: three new rules.**
   - Build artifact evidence is mandatory before reviews begin.
   - Orchestrator must not summarize changes or relay test status —
     connect reviewers to the branch/PR and the worker directly.
   - Cross-reviewer communication is expected during review.

3. **Orchestration protocol Rule 2: new prohibition.** The orchestrator
   must not summarize, characterize, or relay worker output to reviewers.

4. **QE prompt: Rule 10a added.** Demand build evidence for
   artifact-producing PRs. Block if absent.

5. **AD prompt: two new responsibilities.** Challenge "has this been
   built?" for artifact-producing PRs. Challenge other reviewers during
   review — "have you verified build evidence before approving?"

6. **Common agent rules: "Review Conduct" section added.** All reviewers
   must read the code themselves, demand build evidence, talk to each
   other, and never rubber-stamp.
