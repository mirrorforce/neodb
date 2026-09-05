---
name: architecture-conformance
description: Qualify NeoDB changes against existing Django and Takahē seams without inventing product architecture.
---

# Architecture conformance

Use when reviewing or implementing an architecture-sensitive repository change.

- Fresh-read the current owner Issue and identify the native NeoDB seam that
  actually owns the authorized behavior: Django/session/API, Community access
  mediation, Catalog/import/media, or another explicitly named owner seam.
  Current Issues supply the lane; this Skill must not make a lane permanent.
- Prefer the smallest upstream-conformant delta. Preserve existing Django,
  Takahē, persistence, session, queue, search, and runtime ownership and native
  lifecycle boundaries.
- Fail closed on a generic framework, parallel Product model, duplicate
  authority, invented adapter/orchestration layer, or unaccepted dependency,
  persistence, schema, API, migration, or runtime change. Do not use old
  downstream code to infer Product semantics.
- Check imports, migrations, settings, URLs, tests, and relevant documentation
  for accidental dependency on excluded Product areas or cross-owner behavior.
  Treat architecture drift as a stop condition, not a reason to expand scope.
- For governance or documentation-only work, qualify the repository method and
  verify that no Product or runtime behavior change is introduced.

Report the qualifying native seam, changed paths, preserved non-scope, and any
bounded unknown that prevents a stronger conformance claim.
