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
7. **Escalate infrastructure failures BEFORE applying workarounds.** When you
   encounter an infrastructure failure that changes how work is performed —
   build strategy, tool version, network path — you MUST report to the
   orchestrator BEFORE applying any workaround. The orchestrator escalates
   to the owner, who decides whether the workaround is acceptable or whether
   to fix the infrastructure first.

   **What to report:** (a) what failed and the exact error, (b) what you
   believe is wrong (root cause diagnosis), (c) what you already tried to
   fix it, (d) suggested repair steps the owner can take, (e) what
   workaround you propose if repair is not immediate, (f) the impact of
   the workaround (e.g., "local builds use dev machine CPU and are
   slower"). The agent has the technical context; the owner needs it to act.

   **If the owner is unavailable:** The affected work is put on hold — not
   silently worked around, not blocked indefinitely. The orchestrator asks
   the PM to track the blocked work item with the infrastructure issue as
   the blocker, then redirects the worker to other available tasks. The
   infrastructure issue stays reported and unresolved until the owner
   addresses it.

   **What counts as infrastructure failure:**
   - Remote builder unreachable or returning errors
   - Nix store corruption (missing paths, hash mismatches)
   - SSH failures to build infrastructure (NOT the deployment target — Pi
     SSH failures are covered by `deployment-target-access.md`)
   - Network timeouts, DNS failures, disk space exhaustion
   - Service unavailability (CI runners, package caches, registries)

   **Boundary with deployment-target-access.md:** Infrastructure is the
   build toolchain — remote builders, Nix store, flake inputs, CI runners,
   network connectivity to nixpkgs/GitHub. The deployment target (Pi at
   192.168.178.185) is covered by the deployment-target-access protocol.
   SSH failure to the builder → this rule. SSH failure to the Pi → CM protocol.

   **What does NOT require escalation:**
   - Transient errors that resolve on a single retry (e.g., a dropped
     connection that reconnects immediately)
   - Expected build failures from code errors (patch doesn't apply, compile
     error) — these are normal development, not infrastructure failures

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

## Git Worktrees for Parallel Development

Workers performing file edits that may conflict with other workers SHOULD use
git worktrees for isolation. Each worktree is a separate working tree with its
own branch, sharing the same `.git` object store as the main repo.

### Creating a worktree

**Preferred: use the `EnterWorktree` tool.** It creates the worktree in
`.claude/worktrees/` and switches your session into it automatically.

```
EnterWorktree { name: "us-128-pw-upgrade" }
```

**Manual alternative** (if the tool is unavailable or you need control):

```bash
cd /home/ela/mugge
git worktree add .claude/worktrees/<name> -b <branch-name> HEAD
```

**Naming conventions:**
- Worktree name: story ID or short description, e.g., `us-128-pw-upgrade`
- Branch name: same as worktree name, e.g., `us-128-pw-upgrade`
- All worktrees live under `.claude/worktrees/` (gitignored)

### Verify the flake works

After creating the worktree, verify the flake evaluates:

```bash
cd /home/ela/mugge/.claude/worktrees/<name>
nix eval .#packages.x86_64-linux.graph-manager.name --raw
```

If this returns the package name (e.g., `pi4audio-graph-manager-0.1.0`), the
worktree is fully functional.

### Rules

1. **Use absolute paths.** Agent cwd resets between bash calls. Always use
   `/home/ela/mugge/.claude/worktrees/<name>/...` in commands.
2. **Do NOT modify main repo files from a worktree.** Each worktree has its
   own copy of all tracked files. Edit only within your worktree path.
3. **Do NOT run `git` commands against the main repo while in a worktree.**
   The worktree has its own HEAD and index. Use `git` normally inside the
   worktree -- it operates on the worktree's branch.
4. **Commit your work in the worktree.** When done, commit on your branch.
   The CM merges it into main via the normal process.
5. **One worker per worktree.** Do not share worktrees between agents.
6. **Do not create worktrees on existing branch names.** If branch `foo`
   exists, `git worktree add ... -b foo` will fail. Use unique names.

### `.venv` and build artifacts

The main repo's `.venv` contains hardcoded paths and will NOT work in a
worktree. If your task needs Python:
- Use `nix develop` inside the worktree (provides the full Python env)
- Or create a fresh `.venv` in the worktree if absolutely needed

The `result` symlink (from `nix build`) is per-directory and harmless.

### Cleaning up

**Preferred: use the `ExitWorktree` tool** if you used `EnterWorktree`:

```
ExitWorktree { action: "remove" }
```

**Manual cleanup:**

```bash
cd /home/ela/mugge
git worktree remove .claude/worktrees/<name>      # fails if untracked files
git worktree remove --force .claude/worktrees/<name>  # force if needed
git branch -d <branch-name>                        # delete the branch
```

Always delete the branch after removing the worktree. Verify cleanup:

```bash
git worktree list   # should show only /home/ela/mugge
```

### Gotchas

- **L-015/L-052: Do NOT use `isolation: "worktree"` when spawning agents.**
  The Agent tool's worktree parameter is broken and silently fails. Workers
  must call `EnterWorktree` or run `git worktree add` themselves.
- **Worktree removal fails with untracked files.** Use `--force` or clean
  up first. Always confirm the worktree has no uncommitted work before
  force-removing.
- **Flakes work inside worktrees.** The `flake.nix` and `flake.lock` are
  copied into the worktree. Nix evaluates them normally.
- **`.claude/worktrees/` is gitignored.** Worktrees do not pollute the
  main repo's `git status` (only the directory itself shows as untracked
  if the gitignore entry is missing).
