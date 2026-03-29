# Common Agent Rules

These rules apply to ALL team members (advisory, coordination, quality,
challenge, implementation). Your role prompt may add role-specific details.

## Communication & Responsiveness (L-040)

**Mental model:** Agents are independent processes. They do NOT read messages
while executing a tool call. Messages queue in an inbox and are seen only
when the current tool call completes. Silence from another agent means they
are busy, not dead or ignoring you.

**Rules:**

1. **Check messages every ~5 minutes.** If starting a long operation (build,
   SSH deployment, large test suite), run it in the background first.
2. **Report status proactively.** When you complete a significant deliverable,
   message the requesting agent and the team lead immediately.
3. **Acknowledge received messages promptly.** Even "received, working on it"
   prevents unnecessary follow-ups.
4. **One message to other agents, then wait.** They are busy, not ignoring you.
5. **"Idle" does not mean available.** An idle agent may be waiting for human
   permission approval. Do not draw conclusions from idle status.
6. **Close the loop before going idle.** If someone asked you to do something,
   message them with the outcome (success, failure, blocked) before you stop
   working. An idle notification is NOT a status report.

## Context Compaction Recovery

When your context is compacted, you lose awareness of your role, rules,
current task, and protocol.

**Your compaction summary MUST include:**
1. Your role name and team name
2. Where to find your role prompt (path in `.claude/team/roles/`)
3. Role-specific state (see your role prompt for what to preserve)
4. "After compaction, re-read your role prompt before doing anything."

**After compaction recovery:**
1. Re-read your role prompt at the path noted in your summary
2. Re-read the project CLAUDE.md for current context
3. Resume your task from where compaction interrupted
4. Do NOT start new work without checking with the team lead first

## Memory Reporting

Whenever you discover knowledge that would help future sessions — trial and
error, non-obvious behavior, environment gotchas, repeated mistakes, or
hard-won insights — message the **technical-writer** immediately with the
details. Your role prompt lists domain-specific topics to watch for.

Do not wait until your task is done. Report as you go. The technical writer
maintains the team's institutional memory so knowledge is never lost.
