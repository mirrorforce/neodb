---
name: delivery-lifecycle
description: Deliver authorized NeoDB repository work through one task branch, coherent review evidence, and the integration gate.
---

# Delivery lifecycle

Use for authorized repository delivery.

- Start from fresh authority and a clean, owned checkout. Use one task branch and
  one writer; subagents are prohibited unless authority changes that rule.
- Keep changes within the owner Issue and authorized write set. Preserve upstream
  history and record the exact admitted baseline and candidate identity.
- Validate proportionally with T0 checks and, only after environment admission,
  T1/T2 runtime checks. Carry blocked checks forward honestly.
- Make coherent commits suitable for owner review. Do not amend, rebase, force-push,
  merge, or change the default branch unless explicitly authorized for that task.
- Push or open review only when the current authority requests it. Report the exact
  branch, commit/tree, parent, clean-tree state, validation outcomes, non-scope,
  and remaining integration-gate conditions.
