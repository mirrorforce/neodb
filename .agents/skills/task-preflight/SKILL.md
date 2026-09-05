---
name: task-preflight
description: Establish current authority, exact source identity, checkout safety, and one-writer scope before NeoDB repository work.
---

# Task preflight

Use before non-trivial repository work.

- Fresh-read the current program handoff, owner Issue, repository guidance,
  default branch, and fork/upstream identity.
- Record the exact admitted baseline commit and tree, current default SHA,
  candidate commit and tree, branch, worktrees, remotes, checkout state, and
  repository writer ownership. Stop on dirty, unknown, or contradictory state.
- Confirm the current authority's `PROGRAM_ISSUE`, `OWNER_ISSUE`,
  `REPOSITORY`, `CURRENT_DEFAULT_SHA`, `UPSTREAM / ADMITTED_BASELINE`,
  `CHANGE_CLASSIFICATION`, `MODE`, `AUTHORIZED_RESULT`, `AUTHORIZED_WRITESET`,
  `NON_SCOPE`, `REQUIRED_SKILLS`, `VALIDATION`, `STOP_CONDITIONS`,
  `PR_EXPECTATION`, `INTEGRATION_GATE`, and `SUBAGENTS` decision. Do not infer
  current scope from historical tasks.
- Make explicit when the default branch is not the admitted Product source base.
  Use the accepted clean lineage named by current authority and preserve its
  identity; do not silently reset, rebase, amend, force-push, or write the
  default branch.
- Enforce one repository writer and `SUBAGENTS = PROHIBITED` unless current
  authority explicitly changes it. The machine-local Executor performs
  repository-file writes within the authorized write set.
- Dispatch only the required repository methods. Before any runtime-dependent
  T1/T2 command, dispatch `test-environment` and require
  `ENVIRONMENT_ADMISSION = PASS`; T0-only work does not claim runtime evidence.

## Reproducible handoff

End with the minimum applicable execution frame:

```text
PROGRAM_ISSUE
OWNER_ISSUE
REPOSITORY
CURRENT_DEFAULT_SHA
UPSTREAM / ADMITTED_BASELINE
CHANGE_CLASSIFICATION
MODE
AUTHORIZED_RESULT
AUTHORIZED_WRITESET
NON_SCOPE
REQUIRED_SKILLS
VALIDATION
STOP_CONDITIONS
PR_EXPECTATION
INTEGRATION_GATE
SUBAGENTS = PROHIBITED
```

State the next permitted action and carry forward any blocked or not-run check
without promoting its evidence tier.
