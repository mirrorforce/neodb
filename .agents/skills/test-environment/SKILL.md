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

This is a hard admission gate. A T1 or T2 claim is legitimate only when the
record says `ENVIRONMENT_ADMISSION = PASS`. Missing, contradictory, substituted,
or unproven prerequisites produce `BLOCKED`; do not run the dependent command
merely to rediscover a known environment mismatch.

## Current VinylHub machine-local canonical T1 profile

The current VinylHub machine-local T1 profile is concrete because repeated
qualification already converged on this environment. Do not reconstruct it from
an older M0 note, the native production Compose defaults, or a remembered prior
failure.

```text
SOURCE
  exact current NeoDB task SHA/tree
  exact current uv dependency lock

TEST RUNNER
  Python 3.14
  repository test source + dev/test dependencies present
  cwd = neodb

LOCAL DOCKER SERVICES
  Product PostgreSQL
    image = postgres:14-alpine
    RepoDigest = sha256:727876d274666da0b92a445390ba093c84b8e9f8343e1c53cd4e9a7ab2d85310
    accepted server = PostgreSQL 14.24

  Takahe PostgreSQL
    same admitted PostgreSQL image/version family

  Redis
    image = redis:alpine
    RepoDigest = sha256:becdda6c7f4b3fb42e42fd7f120bbf5c54c4caaaf16f26da24e4563d2c1f0576
    accepted server = Redis 8.10.1

SEARCH
  Typesense = REMOTE
  exact version = 30.1
  purpose = test-only
  data = disposable
  local Windows Typesense = PROHIBITED / NOT REQUIRED
  local Docker Typesense for this profile = NOT REQUIRED
```

The remote Typesense endpoint and credential are machine-local/private runtime
inputs. They must not be committed, printed, copied into Issue/PR evidence, or
reconstructed from a public document. Use the configured local secure-store
mechanism and a separate scoped T1 key. Do not use the bootstrap/admin key as the
routine test credential. Never print the plaintext key or full
`NEODB_SEARCH_URL`.

The absence of a local Typesense container is **not** a T1 blocker for this
profile. Native `compose.yml` has its own pinned local Typesense 30.1 runtime
service; that service is not the machine-local VinylHub T1 authority.

The canonical commands, from `neodb`, are:

```text
uv run --project .. python manage.py compilemessages -l zh_Hans
uv run --project .. python -m pytest -n auto --cov=. --cov-report=term-missing --cov-report=xml
```

Do not skip search tests, substitute another Typesense version, lower coverage,
change the canonical command, or create a local Typesense workaround to
manufacture PASS.

This profile is owner T1. App-owned T3 composition is a separate evidence tier
and may use a different exact service topology; T3 evidence must not silently
replace this T1 profile.

## Required admission record

Before the first runtime-dependent command, record every material field using
current authority and bounded evidence. Do not retain secrets or private endpoint
values.

```text
ENVIRONMENT_ADMISSION = PASS / BLOCKED
VALIDATION_TIER = T1 NEOdb TEST / T2 OWNER INTEGRATION
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

# required for the current machine-local T1 profile
PRODUCT_POSTGRES_ADMISSION
TAKAHE_POSTGRES_ADMISSION
REDIS_ADMISSION
TYPESENSE_MODE = REMOTE
TYPESENSE_VERSION = 30.1
TYPESENSE_ENDPOINT_REACHABILITY
TYPESENSE_HEALTH
TYPESENSE_AUTH
TYPESENSE_DATA_ISOLATION = PASS / BLOCKED
TYPESENSE_SECRET_SOURCE = LOCAL_SECURE_STORE
SECRET_VALUE_RETAINED_IN_REPORT = NO
```

For T1, `SERVICE_IDENTITIES` must match the profile above unless a later current
Human-approved environment qualification explicitly supersedes it. For T2, use
the exact owner runtime/provider identities required by the current owner Issue;
`T1 PASS != T2 PASS`.

## Admission procedure

1. Fresh-read the current owner Issue, linked app authority, repository guidance,
   current default source, current CI/test workflow, dependency lock, and this
   Skill. Current authority may supersede this profile only explicitly.
2. Select the evidence tier before runner/service selection. Do not infer T1 from
   production Compose or T2 from T1 CI conventions.
3. Prove the exact task source SHA/tree and exact lock are the source/dependencies
   used by the runner. A stale image, moving tag, old branch, or prior-lane
   checkout is not current evidence.
4. For machine-local T1, prove Python 3.14, test source and dev/test dependencies
   before running the canonical commands.
5. Start/admit only the required local Docker PostgreSQL and Redis services using
   the accepted identities above. Prove database/cache reachability and readiness;
   process start alone is insufficient.
6. Admit remote Typesense 30.1 directly. Prove endpoint reachability, exact
   version, `/health`, authenticated access required by the test suite, and the
   test-only/disposable data designation before setting admission to PASS.
7. Obtain the scoped Typesense T1 credential only from the configured local
   secure store. Keep it in process scope only, expose it to NeoDB through
   `NEODB_SEARCH_URL`, redact the URL from output, and clear plaintext process
   state after the run.
8. Record `CWD` and both canonical commands before execution. The full pytest
   command is the T1 claim; a focused subset may be diagnostic evidence but cannot
   replace canonical T1.
9. Set `ENVIRONMENT_ADMISSION = PASS` only when all material fields are proven and
   mutually consistent. If admission is blocked, stop the dependent T1/T2 command
   and continue only separately authorized T0/static work.

Re-admit after changing source, dependency identity, runner, PostgreSQL/Redis
identity, remote Typesense identity/readiness, credential preconditions, or any
other claim-relevant prerequisite. Ordinary test failures after a valid admission
are source/baseline evidence, not environment-admission failures.

## Hard vetoes

```text
local Windows Typesense startup used for the current machine-local T1
local Docker Typesense substituted for the admitted remote 30.1 profile
Typesense version changed from 30.1 without current Human-approved requalification
bootstrap/admin Typesense key used as routine T1 credential
dummy or intentionally unreachable required endpoint
native Compose defaults treated as T1 authority merely because they exist
focused subset represented as canonical full T1
T1 evidence promoted to T2 or T3
secret value or full NEODB_SEARCH_URL retained in evidence
```

## Bounded failure labels

```text
PLATFORM_MISMATCH
RUNNER_NOT_ADMITTED
ARTIFACT_IDENTITY_MISMATCH
SERVICE_NOT_READY
SERVICE_HOST_INCOMPATIBLE
CREDENTIAL_PRECONDITION_MISSING
MIGRATION_NOT_READY
SOURCE_TEST_FAILURE
OWNER_RUNTIME_FAILURE
UNKNOWN
```

## Evidence rule

Acceptance evidence must preserve the complete admission record and exact
source/tree identity for every T1/T2 claim. The previously proven remote
Typesense path reached the full canonical suite; therefore an executor must not
reopen the superseded local-Typesense blocker unless current evidence proves a
new change in that admitted path.

`ENVIRONMENT_ADMISSION = BLOCKED`, a missing field, or an unproven required
service means the dependent tier is `BLOCKED`/`NOT_RUN`, not PASS. Static checks
remain T0 and cannot be promoted.
