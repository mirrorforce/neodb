# Repository governance

This file defines the durable repository method. The current program handoff and
owner Issue define the current work: scope, source identity, acceptance criteria,
and integration order. Do not infer them from old tasks, closed Issues, or this
file.

## Authority and execution

- Fresh-read the current program handoff, owner Issue, repository guidance,
  default branch, and fork/upstream identity before non-trivial work.
- The exact admitted baseline and current owner Issue control the source and
  authorized write set. The default branch may be historical product-source
  reference material rather than the admitted base; state that explicitly.
- Repository-owned repeatable methods live under `.agents/skills`. They describe
  HOW to work; Issues and PRs provide the mutable WHAT, WHY, scope, and identity.
  `.codex/` is tool-private/local and has no repository authority unless a future
  explicit contract says otherwise.
- The machine-local Executor is the repository-file writer. Keep authority,
  review, and handoff decisions in the current owner workflow rather than in
  chat memory or a parallel governance system.

## Safety and ownership

- One repository has one writer by default. `SUBAGENTS = PROHIBITED` unless the
  current authority explicitly changes it.
- Work on one task branch descended from the admitted baseline. Preserve history;
  do not write non-trivially to the default branch, rewrite history, or
  force-push.
- Fail closed on a dirty or unknown checkout, source identity drift, another
  writer occupying the line, or a request outside the current authorized write
  set.
- Keep public-fork content free of secrets, credentials, private user data,
  private media, and uncontrolled runtime output. Use isolated disposable
  services and test-only values for validation.

## Source and architecture

- Record the exact admitted source commit and tree before implementation. A
  downstream candidate has its own reviewed identity and must not reuse an
  upstream release identity.
- Preserve upstream-native Django, Takahē, persistence, session, queue, search,
  and runtime ownership and lifecycle boundaries. Introduce only the minimum
  accepted owner-lane delta.
- Never infer Product or architecture semantics from old downstream code. Fail
  closed on generic frameworks, duplicate authority, parallel Product models,
  or unaccepted dependency, persistence, schema, API, migration, or runtime
  changes.

## Evidence and delivery

- T0 is static evidence: inspection, formatting, lint, type, compile, structural,
  documentation, and changed-path checks. It does not establish runtime
  behavior.
- T1/T2 claims require the owning repository's current `test-environment`
  admission before the first runtime-dependent command. A blocked admission is
  recorded as `BLOCKED`/`NOT-RUN`; services are not substituted.
- T3 app-composed development is owned and admitted by
  `mirrorforce/vinyl-catalog-app`; NeoDB supplies exact owner identities and
  requirements but does not admit T3.
- Preserve exact commands, outcomes, changed paths, non-scope, and bounded
  unknowns in acceptance evidence. Keep Skills, operations, and implemented
  behavior in their respective owners.
- Follow the current owner Issue -> task branch -> review -> integration gate
  lifecycle. Do not merge or change the default branch unless current authority
  explicitly authorizes it.
