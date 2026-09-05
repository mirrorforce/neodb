---
name: acceptance-evidence
description: Produce compact, reproducible NeoDB evidence for owner review, default-branch delivery, and integration-gate decisions.
---

# Acceptance evidence

Use when validating or handing off a repository candidate.

Capture evidence in this order:

1. Authority: current program handoff, owner Issue, PR, change classification,
   authorized write set, and non-scope.
2. Identity: fork/default branch, admitted upstream, exact source commit/tree,
   task-branch/head identity, and any separate runtime/artifact identity relevant
   to the claim.
3. Diff: changed paths, clean/dirty state, and an explicit statement of Product,
   runtime, schema, migration, dependency, service, data, or private-content
   non-changes where applicable.
4. Validation: exact commands and outcomes, separated by evidence tier. Preserve
   baseline-versus-head results when they matter to the delivery claim.
5. Review notes: accepted seams, authority/source drift, bounded unknowns, branch
   cleanup state, and the next integration gate.

## T1/T2 admission gate

For every runtime-dependent T1 or T2 claim, require the admission method in
`.agents/skills/test-environment/SKILL.md` to run before the first
runtime-dependent command. Preserve this complete record:

```text
ENVIRONMENT_ADMISSION = PASS / BLOCKED
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

Refuse tier promotion when the record is missing, incomplete, contradictory, or
has `ENVIRONMENT_ADMISSION != PASS`. Such evidence is `BLOCKED` or `NOT_RUN`,
not `PASS`. T0 static evidence has no runtime claim; `T1 PASS != T2 PASS`.
Do not copy volatile runner/service/version matrices into this Skill or durable
guidance; identify them in the current per-run evidence.

Each evidence packet must identify, where applicable:

```text
VALIDATION_TIER
VALIDATION_SOURCE_SHA
VALIDATION_SOURCE_TREE
APPLICATION_RUNTIME_IDENTITY
DEPENDENCY_IDENTITY
SERVICE_PREREQUISITES
TEST_RUNNER_IDENTITY
RUNNER_PLATFORM
BASELINE_VALIDATION_SOURCE_SHA
BASELINE_VALIDATION_RESULT
HEAD_VALIDATION_SOURCE_SHA
HEAD_VALIDATION_RESULT
HEAD_DELTA_RESULT
COMMAND
CWD
EXIT
RESULT
```

`RESULT` must be one of `PASS`, `FAIL`, `NOT_RUN`, `BLOCKED`, or `UNKNOWN`.
Keep validation claims at their observed tier: never promote T0 to T1, T1 to T2,
mock to live, or stale source/runtime evidence to the current head.

For any baseline-versus-task-head comparison, report both source SHAs and
validation results. `HEAD_DELTA_RESULT` must be one of `NONE`,
`NEW_REGRESSION`, `IMPROVED`, or `UNKNOWN`; compare diagnostic semantics rather
than matching exit codes/counts. Baseline debt remains debt even when unchanged.

## Delivery and branch evidence

For a repository delivery, also preserve:

```text
DEFAULT_BRANCH
DEFAULT_BASE_SHA
TASK_BRANCH
REVIEWED_HEAD_SHA
REVIEWED_HEAD_TREE
PR_BASE
PR_HEAD
MERGE_OR_REF_ACTION
ACCEPTED_DEFAULT_SHA
BRANCH_CLEANUP
```

A task branch is not a current source authority merely because it is reviewed or
accepted as a candidate. After accepted delivery, fresh-read the default branch
and report deletion/retention of the task branch truthfully. A current
Human-approved recovery/cutover may use exceptional ancestry/ref mechanics, but
its evidence must show how the operation terminates in one authoritative default
branch without force rewriting shared history unless separately authorized.

Run commands with test-only values or isolated disposable services. Redact
credentials and exclude secrets, tokens, private user data, database dumps,
private media, personal logs, and uncontrolled environment output. Evidence must
support replay without becoming a second source of Product requirements.

Fail closed when a required acceptance fact cannot be tied to exact authority,
source identity, command/result, or authorized scope. Do not convert static
inspection into runtime approval or claim a clean result after an unrecorded
failure.
