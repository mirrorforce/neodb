---
name: test-environment
description: Admit the exact NeoDB runner, dependencies, source, and required services before runtime-dependent validation.
---

# Test environment admission

Use before the first T1/T2 command.

- Read the current workflow, Dockerfile, dependency lock, runner requirements, and
  service authority at execution time. Do not copy volatile versions or service
  matrices into durable guidance.
- Record runner platform and identity, candidate source SHA/tree, dependency-lock
  identity, test source availability, development dependencies, working directory,
  canonical command, and required service identities.
- Start only isolated disposable services with test-only values. Verify each
  required service using its authoritative health check and retain exact image
  tags/digests and outcomes.
- Set `ENVIRONMENT_ADMISSION = PASS` only when the exact runner, source,
  dependencies, command, and every required service are available. Otherwise set
  `BLOCKED`, name the precise classification, and do not substitute a service or
  claim T1/T2 execution.
- Clean up only the disposable resources created for admission and retain the
  reproducible record. T0 static checks may continue independently after a block.
