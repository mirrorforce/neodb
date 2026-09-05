---
name: task-preflight
description: Establish current NeoDB authority, exact default/upstream identity, checkout safety, and one-writer scope before non-trivial work.
---

# Task preflight

Use before non-trivial repository work.

1. Fresh-read the current program handoff, owner Issue, repository-root
   `AGENTS.md`, default branch, fork identity, and upstream identity. Current
   Issues own WHAT/WHY/scope; do not infer them from historical branches or old
   commits.
2. Record the exact current default-branch commit/tree, admitted upstream
   commit/tree, candidate commit/tree when one exists, branch, worktrees,
   remotes, checkout state, and repository writer ownership.
3. The ordinary source base is the fresh exact default-branch HEAD. Do not use a
   task/integration/candidate branch as a persistent Product base. A non-default
   source base is valid only when the current Human-approved authority explicitly
   defines a bounded recovery/cutover and its termination condition.
4. Confirm the checkout is clean and owned, the intended task branch is not the
   default branch, and no extra worktree, stash, untracked file, unexplained local
   change, open conflicting PR, or other writer overlaps the task. Stop on unknown
   ownership or contradictory authority.
5. Confirm the current authority's `PROGRAM_ISSUE`, `OWNER_ISSUE`, `REPOSITORY`,
   `CURRENT_DEFAULT_SHA`, `UPSTREAM / ADMITTED_BASELINE`,
   `CHANGE_CLASSIFICATION`, `MODE`, `AUTHORIZED_RESULT`, `AUTHORIZED_WRITESET`,
   `NON_SCOPE`, `REQUIRED_SKILLS`, `VALIDATION`, `STOP_CONDITIONS`,
   `PR_EXPECTATION`, `INTEGRATION_GATE`, and `SUBAGENTS` decision.
6. Classify the change before editing. Product schema/API/runtime semantics,
   ownership changes, migrations, dependencies, external integrations, or other
   architecture-sensitive behavior require current owner authority; do not expand
   scope to repair unrelated debt.
7. Enforce one repository writer and `SUBAGENTS = PROHIBITED` unless current
   authority explicitly changes it. Keep secrets, credentials, private user data,
   generated runtime state, and production data out of the public fork/evidence.

## Validation tier and runtime identity

Select the validation tier before choosing a runner or service topology:

- `T0 STATIC / CHECK`: repository text, diff, formatting/lint/type/compile and
  structural checks. T0 makes no Product runtime claim.
- `T1 NEOdb TEST`: use the exact current task source and dependency lock with
  repository CI-native test conventions. Fresh-read `.github/workflows/tests.yml`,
  current dependency/test layout, and relevant runtime guidance before selecting
  runner or services.
- `T2 OWNER INTEGRATION`: use only the exact owner/task-admitted runtime and
  provider identities required by the current claim.

When T1 or T2 is requested, dispatch
`.agents/skills/test-environment/SKILL.md` after this preflight and before the
first runtime-dependent command. Do not run a test, Django/runtime, service,
Compose, migration, queue, search, storage, or owner-provider command as a tier
claim until the complete admission record exists and
`ENVIRONMENT_ADMISSION = PASS`. If admission is `BLOCKED`, continue only
currently authorized T0/static work and preserve the requested tier as
`BLOCKED` or `NOT_RUN`. `T1 PASS != T2 PASS`.

The admission record must establish before the first runtime-dependent T1/T2
command:

```text
ENVIRONMENT_ADMISSION
VALIDATION_TIER
RUNNER_PLATFORM
RUNNER_IDENTITY
SOURCE_SHA
SOURCE_TREE
DEPENDENCY_IDENTITY
TEST_SOURCE_AVAILABLE
DEV_TEST_DEPS_AVAILABLE
CWD
CANONICAL_COMMAND
REQUIRED_SERVICES
SERVICE_IDENTITIES
SERVICE_HEALTH
```

Do not assume the primary host OS, a production image, a Compose default, or a
previous lane's service identity is valid for the current tier. CI service
identity is not automatically Compose/owner-runtime identity. If current source
requires Linux-only APIs, native Windows is `PLATFORM_MISMATCH`, not a reason to
patch Product source. A stale image or moving tag is not current-source evidence.

## Baseline versus task-head validation

When a repository-native check fails on the task head, determine whether the exact
clean base already had the same behavior. When needed, reproduce the exact base
and record:

```text
BASELINE_VALIDATION_SOURCE_SHA
BASELINE_VALIDATION_RESULT
HEAD_VALIDATION_SOURCE_SHA
HEAD_VALIDATION_RESULT
HEAD_DELTA_RESULT = NONE / NEW_REGRESSION / IMPROVED / UNKNOWN
```

An identical baseline/head failure is not a new task regression, but remains
`FAIL` or bounded debt rather than becoming `PASS`. Compare diagnostic semantics,
not only exit codes/counts.

For Git/GitHub evidence, use full 40-character commit SHAs and exact tree
identities. After push, verify the remote task branch full SHA and re-read PR head
metadata. A single stale PR response immediately after push is
`REMOTE_METADATA_PROPAGATION_DELAY`, not automatic authority drift.

## Reproducible handoff

End preflight with the minimum applicable frame:

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

State the next permitted action and carry forward every blocked/not-run check
without tier promotion.
