---
name: test-environment
description: Admit the exact NeoDB runner, source, dependencies, and required services before any runtime-dependent owner-test or owner-runtime command.
---

# Test environment admission

Use this Skill whenever a command would make a NeoDB `OWNER TESTS` or
`OWNER RUNTIME` claim, or would exercise the application, its test
runner, its database/cache/search dependencies, or an owner runtime. Dispatch
this Skill after task-preflight and before the first such command. T0 static
inspection and repository text checks may run without runtime admission.

This is a hard admission gate. An owner-test or owner-runtime claim is legitimate only when the
record says `ENVIRONMENT_ADMISSION = PASS`. Missing, contradictory, substituted,
or unproven prerequisites produce `BLOCKED`; do not run the dependent command
merely to rediscover a known environment mismatch.

## Current VinylHub machine-local canonical OWNER TESTS profile

The current VinylHub machine-local OWNER TESTS profile is concrete because repeated
qualification already converged on this environment. Do not reconstruct it from
an older M0 note, the native production Compose defaults, or a remembered prior
failure.

```text
SOURCE
  exact current NeoDB task SHA/tree
  exact current uv dependency lock

HOST
  Windows orchestration only: editor, Git, secure-store retrieval, Docker, evidence
  NeoDB tests do not run against a Windows source checkout

TEST RUNNER
  Linux Docker container built from the repository Dockerfile
  exact current source baked into the image; no source bind mount
  Python 3.14.x in the image
  exact uv.lock and locked dev/test dependencies
  cwd = /neodb
  entrypoint = /bin/neodb-t1

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

## Host runtime precision

Project Python compatibility is `pyproject.toml requires-python = >=3.14,<3.15`.
`.python-version = 3.14` means a minor-line selector, not an exact patch pin.
For a Windows, macOS, or Linux host used for repository tooling, compatible
CPython 3.14.x is admissible. Record the actual host Python patch and build as
`RUNNER_IDENTITY` evidence; it is not a hard requirement by default. The
The canonical machine-local NeoDB OWNER TESTS runner is the Linux Docker container above,
so a Windows host Python import failure is a platform mismatch, not a reason to
change NeoDB source for Windows compatibility.

The Docker Python patch does not govern the host Python patch. The Python patch
resolved by GitHub CI does not govern the host Python patch. An exact host
Python patch pin is allowed only when current owner authority proves a
patch-specific compatibility, security, or toolchain need.

Docker uv 0.8.8 belongs to the Docker build identity. The Docker owner-test runner
requires the exact task source, exact `uv.lock`, a successful locked sync, and
the actual image uv version recorded in evidence. A host uv version may be
recorded as orchestration evidence, but it does not need to equal Docker uv
0.8.8 unless current claim-specific evidence requires it.

The remote Typesense endpoint and credential are machine-local/private runtime
inputs. They must not be committed, printed, copied into Issue/PR evidence, or
reconstructed from a public document. Use the configured local secure-store
mechanism and a separate scoped owner-test key. Do not use the bootstrap/admin key as the
routine test credential. Never print the plaintext key or full
`NEODB_SEARCH_URL`.

## Windows secure-store retrieval HOW

The repository-owned host orchestration entrypoint is
`misc/bin/neodb-t1.ps1`. It uses the established Windows machine-local secure
store contract:

From the repository root, invoke it with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\misc\bin\neodb-t1.ps1
```

The optional first argument is the disposable Compose project name. The
entrypoint is the only supported host-side orchestration path for the local
NeoDB OWNER TESTS environment.

```text
provider/mechanism = Windows DPAPI-protected SecureString for the key,
                     plus a private endpoint value stored outside the checkout
safe entry identifiers = %USERPROFILE%\.vinylhub-secrets\typesense-t1.dpapi
                         %USERPROFILE%\.vinylhub-secrets\typesense-t1.endpoint
optional path overrides = NEODB_TYPESENSE_KEY_FILE,
                           NEODB_TYPESENSE_ENDPOINT_FILE
```

The helper reads those entries, checks remote Typesense health/version and
authenticated collection-endpoint reachability without retaining response
content, constructs `NEODB_SEARCH_URL` only in its process memory, and passes it
through the process environment to the explicit Compose `owner-tests` service.
It never writes the URL/key to a file, Compose YAML, the image, Git, or
evidence. It records no plaintext value. The helper invokes only the
`neodb-owner-tests`, `neodb-db`, `takahe-db`, and `redis` services, then runs
Compose cleanup with disposable volumes and removes its task-owned temporary
data path.
It clears the process environment and zeroes the DPAPI plaintext buffer in a
`finally` block. A missing/inaccessible entry may be reported as
`CREDENTIAL_PRECONDITION_MISSING` only after this entrypoint has been invoked.

The absence of a local Typesense container is **not** an owner-test blocker for this
profile. Native `compose.yml` has its own pinned local Typesense 30.1 runtime
service, but the `owner-tests` service explicitly selects the Dockerfile
`owner-tests` target,
depends only on Product PostgreSQL, Takahē PostgreSQL, and Redis, and rejects
an absent or empty `NEODB_SEARCH_URL` before tests. The machine-local owner-test
search service is remote Typesense 30.1, injected into the owner-test container process
through the secure-store path.

The canonical commands, from `/neodb` inside the Linux test container, are:

```text
uv run --project .. python manage.py compilemessages -l zh_Hans
uv run --project .. python -m pytest -n auto --cov=. --cov-report=term-missing --cov-report=xml
```

Do not skip search tests, substitute another Typesense version, lower coverage,
change the canonical command, use a Windows source bind mount, or create a
local Typesense workaround to manufacture PASS. `/bin/neodb-t1` runs the two
commands above in order with `/neodb-venv/bin/python`.

This profile is OWNER TESTS. App-owned LOCAL INTEGRATION is a separate
ownership boundary and may use a different exact service topology; LOCAL
INTEGRATION evidence must not silently replace OWNER TESTS evidence. OWNER
TESTS evidence does not prove OWNER RUNTIME behavior.

## Required admission record

Before the first runtime-dependent command, record every material field using
current authority and bounded evidence. Do not retain secrets or private endpoint
values.

```text
ENVIRONMENT_ADMISSION = PASS / BLOCKED
VALIDATION_CONTEXT = OWNER TESTS / OWNER RUNTIME / LOCAL INTEGRATION
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

# required for the current machine-local OWNER TESTS profile
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

For OWNER TESTS, `SERVICE_IDENTITIES` must match the profile above unless a
later current Human-approved environment qualification explicitly supersedes
it. OWNER TESTS evidence does not prove OWNER RUNTIME or LOCAL INTEGRATION.

## Admission procedure

1. Fresh-read the current owner Issue, linked app authority, repository guidance,
   current default source, current CI/test workflow, dependency lock, and this
   Skill. Current authority may supersede this profile only explicitly.
2. Select the semantic environment context before runner/service selection. Do
   not infer OWNER TESTS from production Compose or LOCAL INTEGRATION from
   OWNER TESTS conventions.
3. Prove the exact task source SHA/tree and exact lock are the source/dependencies
   used by the runner. A stale image, moving tag, old branch, or prior-lane
   checkout is not current evidence.
4. For machine-local OWNER TESTS, build the Linux test image from the exact source with
   the exact lock and dev/test dependencies. Prove the image ID, Python/uv
   identity, `/etc/neodb_version` source SHA, and `/etc/neodb_tree` source tree
   before running the canonical commands.
5. Start/admit only the required local Docker PostgreSQL and Redis services using
   the accepted identities above. Prove database/cache reachability and readiness;
   process start alone is insufficient.
6. Admit remote Typesense 30.1 directly. Prove endpoint reachability, exact
   version, `/health`, authenticated access required by the test suite, and the
   test-only/disposable data designation before setting admission to PASS.
7. Obtain the scoped Typesense owner-test credential only from the configured local
   secure store. Keep it in process scope only, expose it to NeoDB through
   `NEODB_SEARCH_URL`, redact the URL from output, and clear plaintext process
   state after the run.
8. Record `CWD` and both canonical commands before execution. The full pytest
   command is the OWNER TESTS claim; a focused subset may be diagnostic evidence
   but cannot replace canonical OWNER TESTS.
9. Set `ENVIRONMENT_ADMISSION = PASS` only when all material fields are proven and
   mutually consistent. If admission is blocked, stop the dependent owner-test or
   owner-runtime command and continue only separately authorized static work.

Re-admit after changing source, dependency identity, runner, PostgreSQL/Redis
identity, remote Typesense identity/readiness, credential preconditions, or any
other claim-relevant prerequisite. Ordinary test failures after a valid admission
are source/baseline evidence, not environment-admission failures.

## Hard vetoes

```text
local Windows Typesense startup used for the current machine-local OWNER TESTS
local Docker Typesense substituted for the admitted remote 30.1 profile
Typesense version changed from 30.1 without current Human-approved requalification
bootstrap/admin Typesense key used as routine owner-test credential
dummy or intentionally unreachable required endpoint
native Compose defaults treated as OWNER TESTS authority merely because they exist
focused subset represented as canonical full OWNER TESTS
OWNER TESTS evidence promoted to OWNER RUNTIME or LOCAL INTEGRATION
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
source/tree identity for every OWNER TESTS or OWNER RUNTIME claim. The previously proven remote
Typesense path reached the full canonical suite; therefore an executor must not
reopen the superseded local-Typesense blocker unless current evidence proves a
new change in that admitted path.

`ENVIRONMENT_ADMISSION = BLOCKED`, a missing field, or an unproven required
service means the dependent semantic environment is `BLOCKED`/`NOT_RUN`, not
PASS. Static checks cannot be promoted to runtime evidence.
