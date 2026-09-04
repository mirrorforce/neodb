# Repository governance

This repository is a downstream candidate. Before non-trivial work, fresh-read the
current program handoff, owner Issue, repository guidance, default branch, and
fork/upstream identity. The current authority defines scope, source SHAs, runtime
requirements, and acceptance decisions; do not infer them from old tasks or this
file.

## Safety and ownership

- One repository has one writer. Subagents are prohibited unless current authority
  explicitly changes that rule.
- Work on one task branch and preserve existing history. Do not write non-trivial
  changes directly to the default branch, rewrite history, or force-push.
- Fail closed on a dirty worktree, unknown ownership, source identity drift, or a
  requested change outside the authorized write set.
- Keep public-fork content free of secrets, credentials, private user data, dumps,
  private media, and uncontrolled runtime output. Use isolated disposable services
  and test-only values for validation.

## Source and architecture

- Record the exact admitted upstream commit and tree before implementation. A
  downstream candidate has its own reviewed commit identity and must not reuse an
  upstream release identity.
- Conform to existing Django, Takahē, persistence, queue, search, and runtime seams.
  Do not introduce generic frameworks, orchestration, ownership changes, or product
  schema/API semantics without current authority.
- Keep R0 repository governance separate from product behavior. Keep R1 identity
  work at the narrow verified-identity -> stable binding -> Product User -> native
  session seam, leaving future R2 provisioning outside this candidate.

## Evidence and delivery

- T0 covers static inspection, formatting, lint, type, compile, and structural
  checks; it does not establish runtime behavior.
- T1/T2 runtime claims require the repository's test-environment admission before
  the first runtime-dependent command. Record runner, source, dependency, and
  required-service identities. If admission fails, report BLOCKED/NOT-RUN and do
  not substitute services or promote the tier.
- Preserve exact commands, outcomes, changed paths, non-changes, and bounded
  unknowns in the acceptance evidence.
- Follow the owner Issue -> task branch -> review -> integration gate lifecycle.
  Do not merge or change the default branch unless current authority explicitly
  authorizes it.
