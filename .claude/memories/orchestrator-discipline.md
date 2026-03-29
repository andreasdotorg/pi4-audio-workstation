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
