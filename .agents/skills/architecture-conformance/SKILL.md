---
name: architecture-conformance
description: Qualify NeoDB changes against existing Django and Takahē seams without inventing product architecture.
---

# Architecture conformance

Use when reviewing or implementing repository changes.

- Identify the existing Django, Takahē, persistence, session, queue, search, and
  runtime seam that owns the behavior. Prefer the smallest conforming change.
- Preserve existing ownership and native lifecycle boundaries. Do not add generic
  orchestration, reconciliation, adapters, projections, publication systems, or
  new product schemas unless current authority explicitly authorizes them.
- For a narrow Managed Identity lane, keep the contract to verified identity,
  stable issuer/subject binding, native Product User, and native Product session.
  Keep provider verification free of application-side effects and leave future
  community provisioning as an explicit downstream seam.
- Check imports, migrations, settings, URLs, and tests for accidental dependency on
  excluded product areas. Treat architecture drift as a stop condition, not as a
  reason to expand scope.
- Report the qualifying seam, changed paths, non-scope preserved, and any unknown
  that prevents a stronger claim.
