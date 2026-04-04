#!/bin/bash
# Pre-compact hook: additive summarization instructions for team sessions.
#
# For agents coordinating a team (orchestrator): shifts the summarizer's
# focus to coordination state instead of technical detail.
# For agents doing implementation work (workers): these instructions are
# effectively no-ops — there's no team coordination state to summarize,
# so the summarizer naturally preserves full technical detail as normal.
#
# stdout is appended as custom compact instructions (exit 0).

cat <<'EOF'
If this conversation involves coordinating a team of agents via SendMessage:
- Prioritize: which team members are alive and their roles, pending approvals
  and review status, owner directives and decisions, what tasks are assigned
  to whom, protocol state (deployment sessions, Rule 13 gate status).
- De-prioritize: code snippets, patch contents, build logs, file diffs,
  technical diagnostics. These belong to the workers who hold that context.
  Mention them only by reference (e.g., "build failed for PipeWire patch"
  not the full error log).
- For "Current Work" and "Optional Next Step": describe the coordination
  state, not technical work. What is the orchestrator waiting for? Who
  needs to report? What does the owner need to decide?

If this conversation is doing direct implementation work (editing files,
running tests, debugging), ignore the above and preserve full technical
detail as normal.
EOF
