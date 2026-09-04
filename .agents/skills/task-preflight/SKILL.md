---
name: task-preflight
description: Establish current authority, exact source identity, checkout safety, and one-writer scope before NeoDB repository work.
---

# Task preflight

Use before non-trivial repository work.

- Fresh-read the current program handoff, owner Issue, repository guidance, default
  branch, and fork/upstream identity.
- Record the exact admitted upstream commit and tree, current candidate state,
  branch, worktrees, remotes, and ownership. Stop on dirty or ambiguous state.
- Confirm the authorized write set, non-scope, and whether the task is R0, R1, or
  another explicitly authorized lane. Do not infer scope from historical commits.
- Enforce one repository writer and `SUBAGENTS = PROHIBITED` unless current
  authority changes it.
- Before any runtime-dependent T1/T2 command, dispatch `test-environment` and
  require `ENVIRONMENT_ADMISSION = PASS`. A blocked admission remains blocked;
  do not substitute services.
- End with a reproducible preflight record and the next permitted action. Do not
  silently reset, rebase, amend, force-push, or write the default branch.
