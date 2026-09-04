---
name: acceptance-evidence
description: Produce compact, reproducible NeoDB evidence for owner review and integration-gate decisions.
---

# Acceptance evidence

Use when validating or handing off a repository candidate.

- Record exact source commit/tree, admitted upstream identity, branch, worktree
  state, dependency identity, runner, services, canonical commands, and outcomes.
- Separate T0 static results from T1/T2 runtime results. Preserve the complete
  test-environment admission record and refuse to promote a tier without it.
- List changed paths, scope and non-scope, migration/model-state findings, focused
  test coverage, security/privacy checks, and bounded unknowns.
- Mark unavailable checks as `BLOCKED` or `NOT-RUN`; never convert missing services,
  missing credentials, or skipped tests into a pass.
- Keep evidence minimal and reproducible. Do not include secrets, private data,
  uncontrolled logs, or speculative conclusions.
- Hand off the exact candidate identity and evidence to the owner review and
  integration gate. Do not merge or alter the default branch as part of evidence
  production.
