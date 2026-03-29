# Change Management & Git Workflow Learnings

## Topic: git reset HEAD unsafe with parallel workers (2026-03-29)

**Context:** CM commit protocol step 2 runs `git reset HEAD` to clear staging after committing. With multiple workers modifying files in the same working tree, one worker's commit flow wiped another's unstaged changes. Specifically, worker-3's pipewire.nix changes were lost during CM's commit of worker-2's files.

**Learning:** `git reset HEAD` is safe for a single worker but dangerous with parallel workers sharing a working tree. Before running `git reset HEAD`, the CM must:
1. Run `git status` to check for modifications outside the requested commit files
2. If other modifications exist: stash them or warn the affected worker before proceeding
3. Never blindly clear staging when parallel work is in progress

**Root cause:** The commit protocol assumed sequential, single-worker operation. Parallel workers sharing one working tree create interleaving hazards at the git staging level.

**Source:** Team lead report — worker-3's pipewire.nix changes lost during worker-2's commit flow
**Tags:** change-manager, git, parallel-workers, data-loss, commit-protocol, git-reset, working-tree
