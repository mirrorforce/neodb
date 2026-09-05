# Repository governance

This file defines the durable repository method. The current program handoff and
owner Issue define the current work: scope, acceptance criteria, authorized write
set, and integration order. Do not infer current Product requirements from old
tasks, closed Issues, historical branches, or source archaeology.

## Authority and execution

- Fresh-read the current program handoff, owner Issue, repository guidance,
  default branch, and fork/upstream identity before non-trivial work.
- The repository default branch is the sole current downstream source authority.
  Ordinary non-trivial work starts from a fresh exact default-branch HEAD and is
  delivered through one task branch and one owner PR back to the default branch.
- A task, integration, candidate, recovery, or experiment branch must not become a
  second long-lived Product mainline. A non-default source base is permitted only
  for an explicit current Human-approved recovery/cutover, and that exception must
  terminate by restoring one authoritative default branch.
- Upstream identity is tracked separately. A fresh upstream commit/tree may be an
  admitted baseline or comparison input, but it does not replace the downstream
  default branch as repository source authority.
- Repository-owned repeatable methods live under `.agents/skills`. They describe
  HOW to work; Issues and PRs provide mutable WHAT, WHY, scope, and exact identity.
  `.codex/` is tool-private/local and has no repository authority unless a future
  explicit contract says otherwise.
- The machine-local Executor is the repository-file writer. Keep authority,
  review, and handoff decisions in the current owner workflow rather than in chat
  memory or a parallel governance system.

## Safety and ownership

- One repository has one writer by default. `SUBAGENTS = PROHIBITED` unless the
  current authority explicitly changes it.
- Preserve history. Do not write non-trivially to the default branch, rewrite
  shared history, force-push, or silently reset/rebase/amend shared work.
- Delete accepted task branches after delivery/terminalization once no current
  Issue or PR consumes them. Historical evidence remains in commits, PRs, and
  Issues rather than in permanent parallel source branches.
- Fail closed on a dirty or unknown checkout, source identity drift, another writer
  occupying the line, contradictory authority, or a request outside the current
  authorized write set.
- Keep public-fork content free of secrets, credentials, private user data,
  database dumps, private media, and uncontrolled runtime output. Use isolated
  disposable services and test-only values for validation.

## Source and architecture

- Record the exact default-branch source commit/tree and exact admitted upstream
  commit/tree before implementation. A downstream delivery has its own reviewed
  identity and must not reuse an upstream release identity.
- Preserve upstream-native Django, Takahē, persistence, session, queue, search,
  and runtime ownership and lifecycle boundaries. Introduce only the minimum
  accepted owner-lane delta.
- Never infer Product or architecture semantics from retired downstream code. Fail
  closed on generic frameworks, duplicate authority, parallel Product models, or
  unaccepted dependency, persistence, schema, API, migration, or runtime changes.

## Evidence and delivery

- T0 is static evidence: inspection, formatting, lint, type, compile, structural,
  documentation, and changed-path checks. It does not establish runtime behavior.
- T1/T2 claims require the current `test-environment` admission before the first
  runtime-dependent command. A blocked admission is recorded as
  `BLOCKED`/`NOT_RUN`; required services are not silently substituted.
- NeoDB's current VinylHub machine-local canonical T1 profile is defined inside
  `.agents/skills/test-environment/SKILL.md`. It is an explicit proven profile,
  not something to reconstruct from `compose.yml`, old M0 notes, or previous
  failure reports. In particular, native Compose search defaults are not
  automatically the VinylHub owner-T1 search authority.
- T3 app-composed development is owned and admitted by
  `mirrorforce/vinyl-catalog-app`; NeoDB supplies exact owner identities and
  requirements but does not admit T3. A different App T3 service topology must
  not silently overwrite the NeoDB T1 profile.
- Preserve exact commands, outcomes, changed paths, non-scope, and bounded unknowns
  in acceptance evidence. Keep Skills, operations, and implemented behavior in
  their respective owners.
- Follow owner Issue -> task branch -> review -> accepted default branch -> branch
  cleanup -> integration gate. Do not merge or change the default branch unless
  current authority explicitly authorizes that action.
