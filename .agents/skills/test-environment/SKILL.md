---
name: test-environment
description: Admit the exact NeoDB runner, source, dependencies, and required services before any runtime-dependent T1 or T2 command.
---

# Test environment admission

Use this Skill whenever a command would make a NeoDB `T1 NEOdb TEST` or
`T2 OWNER INTEGRATION` claim, or would exercise the application, its test
runner, its database/cache/search dependencies, or an owner runtime. Dispatch
this Skill after task-preflight and before the first such command. T0 static
inspection and repository text checks may run without runtime admission.

This is a hard admission gate, not a best-effort diagnostic. A T1 or T2
claim is legitimate only when the admission record says
`ENVIRONMENT_ADMISSION = PASS`. If any required fact is unknown, missing,
contradictory, or cannot be proven for the current source, record
`ENVIRONMENT_ADMISSION = BLOCKED` and do not run a command as T1 or T2.

## Required admission record

Before the first runtime-dependent command, record every field below using
current authority and safe, bounded evidence. Do not include credentials,
tokens, private endpoints, private user data, uncontrolled environment dumps,
or service response bodies when a result category is sufficient.

```text
ENVIRONMENT_ADMISSION = PASS / BLOCKED
VALIDATION_TIER = T1 NEOdb TEST / T2 OWNER INTEGRATION
RUNNER_PLATFORM = <platform and architecture>
RUNNER_IDENTITY = <exact runner, image, checkout or host identity>
SOURCE_SHA = <full 40-character source commit>
SOURCE_TREE = <full source tree identity>
DEPENDENCY_IDENTITY = <lockfile/environment identity and provenance>
TEST_SOURCE_AVAILABLE = YES / NO / UNKNOWN
DEV_TEST_DEPS_AVAILABLE = YES / NO / UNKNOWN
CWD = <repository-native working directory>
CANONICAL_COMMAND = <exact command to be run>
REQUIRED_SERVICES = <services required by this claim>
SERVICE_IDENTITIES = <exact admitted identity for each required service>
SERVICE_HEALTH = <bounded readiness and reachability result for each service>
```

`SERVICE_IDENTITIES` must distinguish the identity required by the current
claim from a merely similar CI, Compose, or runtime service. `SERVICE_HEALTH`
must prove that every required service is real, reachable from the runner, and
ready for the operation; process-started or HTTP-only evidence is insufficient
when the current operation also needs migrations, queues, storage, or another
readiness condition.

## Admission procedure

1. Fresh-read the current owner Issue, linked app authority, repository
   guidance, and the current source/runtime authority relevant to the claim.
   For T1, read the current CI workflow, dependency lock, test layout, and
   runner instructions. For T2, read the exact owner runtime/provider
   authority. Do not copy volatile Python, database, cache, search, image, or
   service-version values into this Skill or durable guidance.
2. Select the tier before selecting a runner. T1 follows current repository
   CI-native test conventions. T2 requires exact task-admitted owner runtime
   and provider identities. `T1 PASS != T2 PASS`; a passing lower tier never
   promotes a higher tier.
3. Prove `RUNNER_PLATFORM` and `RUNNER_IDENTITY` against that tier. If the
   current source requires Linux-only APIs, native Windows is
   `PLATFORM_MISMATCH` and cannot be admitted as T1. An incompatible host is
   `BLOCKED`, not a reason to patch Product source or weaken the claim.
4. Prove that `SOURCE_SHA` and `SOURCE_TREE` are the source actually mounted,
   checked out, or built into the runner. A stale prior-lane image, moving
   tag, or default artifact is not current-source evidence. Prove
   `DEPENDENCY_IDENTITY` from the current lock and environment provenance.
5. Prove `TEST_SOURCE_AVAILABLE` and `DEV_TEST_DEPS_AVAILABLE` before running
   tests. A production/runtime image is not automatically a test runner. If
   it omits current tests or development/test dependencies, it is not admitted
   for T1; use an exact current-source, test-compatible runner only when the
   current authority permits it.
6. Record the repository-native `CWD` and exact `CANONICAL_COMMAND` before
   execution. Do not replace the command with an easier probe and call the
   result T1 or T2.
7. Enumerate `REQUIRED_SERVICES` from the current authority and prove each
   `SERVICE_IDENTITY` and `SERVICE_HEALTH`. A CI service identity does not
   automatically become a Compose or owner-runtime identity. Required
   endpoints must be real, reachable, and ready; dummy, intentionally
   unreachable, or unspecified endpoints are forbidden.
8. If a required service cannot run with the exact admitted identity on the
   selected host, classify the result as `SERVICE_HOST_INCOMPATIBLE` or
   `SERVICE_NOT_READY` and set admission to `BLOCKED`. Do not perform an
   ad-hoc service-version substitution, point the endpoint nowhere, or remove
   a prerequisite to manufacture PASS unless current authority explicitly
   admits that identity.
9. Set `ENVIRONMENT_ADMISSION = PASS` only when all required fields are
   proven and mutually consistent. Preserve the record with the command
   result. If admission is `BLOCKED`, stop only the T1/T2 claim: continue
   authorized T0/static validation and report the blocked tier accurately.

Re-admit after changing source, dependency identity, runner, service
identity, or any prerequisite that could affect readiness. Ordinary
application failures after a valid admission remain execution evidence; do
not turn this Skill into a generic diagnostics or orchestration framework.

## Bounded failure labels

Use only the label that the evidence supports:

```text
PLATFORM_MISMATCH
RUNNER_NOT_ADMITTED
ARTIFACT_IDENTITY_MISMATCH
SERVICE_NOT_READY
SERVICE_HOST_INCOMPATIBLE
MIGRATION_NOT_READY
SOURCE_TEST_FAILURE
OWNER_RUNTIME_FAILURE
UNKNOWN
```

The #35/#36 delivery is the motivating example: the local host could not run
CI-aligned Typesense, so `LOCAL_T1` remained `BLOCKED`. The focused run was
diagnostic evidence only; an unreachable or substituted search endpoint was
not promoted to T1 evidence.

## Evidence rule

Acceptance evidence must include the admission record and exact source/tree
identity for every T1/T2 claim. An evidence packet with
`ENVIRONMENT_ADMISSION = BLOCKED`, a missing admission record, or an
unproven required field must report that tier as `BLOCKED` or `NOT_RUN`; it
must not report `PASS`. Static checks remain T0 evidence and must not be
promoted to T1 or T2.
