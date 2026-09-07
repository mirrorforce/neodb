---
name: test-environment
description: Admit the exact NeoDB runner, source, dependencies, and required services before any runtime-dependent owner-test or owner-runtime command.
---

# Test environment admission

Use this Skill whenever a command would make a NeoDB `OWNER TESTS` or
`OWNER RUNTIME` claim, or would exercise the application, its test runner, its
database/cache/search dependencies, or an owner runtime. Dispatch this Skill
after task-preflight and before the first such command. STATIC CHECKS and
repository text checks may run without runtime admission.

This is a hard admission gate. An owner-test or owner-runtime claim is
legitimate only when the record says `ENVIRONMENT_ADMISSION = PASS`. Missing,
contradictory, substituted, or unproven prerequisites produce `BLOCKED`; do
not run the dependent command merely to rediscover a known mismatch.

## Current VinylHub machine-local canonical OWNER TESTS profile

The current machine-local OWNER TESTS runner is a Linux Docker container built
from the exact repository source. Search is capability-selected between the
two accepted profiles below. Selection is explicit and there is no automatic
fallback.

```text
SOURCE
  exact current NeoDB task SHA/tree
  exact current uv dependency lock

HOST
  Windows orchestration only: editor, Git, Docker, process-environment input,
  and evidence collection
  NeoDB tests do not run against a Windows source checkout

TEST RUNNER
  Linux Docker container built from the repository Dockerfile
  exact current source baked into the image; no source bind mount
  Python 3.14.x in the image
  exact uv.lock and locked dev/test dependencies
  cwd = /neodb
  entrypoint = /bin/neodb-owner-test

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

OWNER TESTS / LOCAL_DOCKER_TYPESENSE
  Typesense image = typesense/typesense:30.1
  RepoDigest = sha256:91604dc128e2023e7cba34ae8bd36f68351bcb74ea33a84960bfdc5649cf43b3
  task-owned disposable data under the temporary NEODB_DATA root
  no remote credential

OWNER TESTS / REMOTE_TYPESENSE
  remote test/development Typesense service, exact version 30.1
  explicit endpoint and scoped test credential from process environment
  test-only/disposable data and credential isolation must be proven
```

## Host runtime precision

Project Python compatibility is `pyproject.toml requires-python = >=3.14,<3.15`.
`.python-version = 3.14` is a minor-line selector, not an exact patch pin. For
a Windows, macOS, or Linux host used for repository tooling, compatible CPython
3.14.x is admissible. Record the actual host Python patch and build as
`RUNNER_IDENTITY`; it is not a hard requirement by default. The canonical
machine-local OWNER TESTS runner is the Linux Docker container above, so a
Windows host Python import failure is a platform mismatch, not a reason to
change NeoDB source for Windows compatibility.

The Docker Python patch does not govern the host Python patch. The Python patch
resolved by GitHub CI does not govern the host Python patch. An exact host
Python patch pin is allowed only when current owner authority proves a
patch-specific compatibility, security, or toolchain need.

Docker uv 0.8.8 belongs to the Docker build identity. The Docker owner-test
runner requires the exact task source, exact `uv.lock`, a successful locked
sync, and the actual image uv version recorded in evidence. A host uv version
may be recorded as orchestration evidence, but need not equal Docker uv 0.8.8.

## Profile selection and machine-local inputs

The repository-owned host entrypoint is `misc/bin/neodb-owner-test.ps1`. It requires
one explicit profile:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\misc\bin\neodb-owner-test.ps1 -Profile LOCAL_DOCKER_TYPESENSE
```

For the remote profile, provide endpoint and credential directly in the
process environment, then select the profile explicitly:

```powershell
$env:NEODB_TYPESENSE_ENDPOINT = '<machine-local endpoint>'
$env:NEODB_TYPESENSE_API_KEY = '<machine-local scoped owner-test key>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\misc\bin\neodb-owner-test.ps1 -Profile REMOTE_TYPESENSE
```

The endpoint must be a remote host or host:port only; do not include `http://`,
`https://`, credentials, or a path. An omitted port uses 8108. NeoDB's current
Typesense client uses HTTP for the resulting node connection. The remote key
is read only from the current process environment and must contain only
URL-userinfo unreserved characters (`A-Z`, `a-z`, `0-9`, `-`, `.`, `_`, `~`).
Unsafe values fail closed before external preflight. The NeoDB owner-test
wrapper consumes explicit arguments and process-environment values only; it
does not load any `.env` file. Normal VinylHub machine configuration is
App-owned. When the App controller dispatches this primitive, it may supply
the required process inputs from its own machine configuration; NeoDB does not
create a second configuration-init or `.env` load path.

The wrapper validates remote health, authenticated collection access, and
version 30.1 before starting Docker. It allocates a run-unique collection
namespace and fails closed if that namespace is already present. The owner
test settings derive the namespace from the wrapper's process-local search URL
and map `catalog`, `people`, and `journal` to it (plus the existing xdist worker
suffix), so the remote run never uses the persistent `vinylhub-dev` collections.
Cleanup lists collections and deletes only names
matching the exact run-owned namespace; cleanup residue is reported as a
failure rather than broadening deletion authority. It then constructs
`NEODB_SEARCH_URL` only in process memory. The test container independently
validates Typesense health, authentication, version 30.1, and the run-unique
namespace before running tests. The wrapper never prints the key, hostname, or
full credential-bearing URL, disables Compose automatic `.env` loading, and
restores its process environment during cleanup. Local profile execution uses
only the pinned local Typesense service, a run-unique Compose project, and
task-owned disposable data; it does not read remote credentials.

The profile-specific Compose services are `neodb-owner-tests-local` and
`neodb-owner-tests` under `owner-tests-local` and `owner-tests-remote`
profiles. The PowerShell wrapper is the only supported host-side entrypoint.
It cleans the Compose project with disposable volumes and removes its
task-owned temporary data path even after failure.

## Canonical OWNER TESTS commands

The supported host command is the explicit profile command above. Inside the
Linux test container, `/bin/neodb-owner-test` runs these commands in order:

```text
uv run --project .. python manage.py compilemessages -l zh_Hans
uv run --project .. python -m pytest -n auto --cov=. --cov-report=term-missing --cov-report=xml
```

Do not skip search tests, substitute another Typesense version, lower
coverage, change the canonical command, use a Windows source bind mount, or
create a local/remote workaround to manufacture PASS. A focused subset may be
diagnostic evidence but cannot replace canonical OWNER TESTS.

This is OWNER TESTS. App-owned VINYLHUB DEVELOPMENT is a separate ownership
boundary and may use a different exact service topology; its evidence must not
silently replace OWNER TESTS evidence. OWNER TESTS evidence does not prove
OWNER RUNTIME behavior.

## Required admission record

Before the first runtime-dependent command, record every material field using
current authority and bounded evidence. Do not retain secrets, full
credential-bearing URLs, or private key material.

```text
ENVIRONMENT_ADMISSION = PASS / BLOCKED
VALIDATION_CONTEXT = OWNER TESTS / OWNER RUNTIME / VINYLHUB DEVELOPMENT
OWNER_TESTS_PROFILE = LOCAL_DOCKER_TYPESENSE / REMOTE_TYPESENSE
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
PRODUCT_POSTGRES_ADMISSION
TAKAHE_POSTGRES_ADMISSION
REDIS_ADMISSION
TYPESENSE_MODE = LOCAL_DOCKER / REMOTE
TYPESENSE_VERSION = 30.1
TYPESENSE_ENDPOINT_REACHABILITY
TYPESENSE_HEALTH
TYPESENSE_AUTH
TYPESENSE_DATA_ISOLATION = PASS / BLOCKED
TYPESENSE_SECRET_SOURCE = NONE / PROCESS_ENVIRONMENT
SECRET_VALUE_RETAINED_IN_REPORT = NO
```

For OWNER TESTS, service identities must match the selected profile above
unless later current Human-approved environment qualification explicitly
supersedes it. OWNER TESTS evidence does not prove OWNER RUNTIME or LOCAL
INTEGRATION.

## Admission procedure

1. Fresh-read the current owner Issue, linked app authority, repository
   guidance, current default source, current CI/test workflow, dependency lock,
   and this Skill. Current authority may supersede this profile only explicitly.
2. Select `LOCAL_DOCKER_TYPESENSE` or `REMOTE_TYPESENSE` before runner/service
   selection. Missing or invalid selection is `BLOCKED`; never fall back to the
   other profile.
3. Prove the exact task source SHA/tree and exact lock used by the runner. A
   stale image, moving tag, old branch, or prior-lane checkout is not current
   evidence.
4. Build the Linux test image from exact source with exact lock and dev/test
   dependencies. Prove the image ID, Python/uv identity, `/etc/neodb_version`
   source SHA, and `/etc/neodb_tree` source tree before canonical commands.
5. Start/admit only the required local Docker PostgreSQL and Redis services with
   the accepted identities above. Prove reachability and readiness; process
   start alone is insufficient.
6. For LOCAL_DOCKER_TYPESENSE, prove the pinned 30.1 image, task-owned
   disposable data, health, authenticated access, and version from inside the
   test network.
7. For REMOTE_TYPESENSE, prove endpoint reachability, exact version 30.1,
   `/health`, authenticated collection access, and test-only/disposable data
   isolation. Prove the run-unique collection namespace is absent before the
   run and that cleanup targets only that namespace. Obtain the scoped key only
   from process-local machine input; keep
   it in process scope, expose it to NeoDB through `NEODB_SEARCH_URL`, redact
   the URL from output, and clear process state after the run.
8. Record `CWD` and both canonical commands before execution. The full pytest
   command is the OWNER TESTS claim; a focused subset cannot replace it.
9. Set `ENVIRONMENT_ADMISSION = PASS` only when every material field is proven
   and mutually consistent. If admission is blocked, stop dependent owner-test
   or owner-runtime commands and continue only separately authorized static
   work.

Re-admit after changing source, dependency identity, runner, PostgreSQL/Redis
identity, selected Typesense profile, Typesense identity/readiness, credential
preconditions, or any other claim-relevant prerequisite. Ordinary test
failures after valid admission are source/baseline evidence, not admission
failures.

## Hard vetoes

```text
local Windows Typesense startup used for OWNER TESTS
implicit profile selection or automatic profile fallback
LOCAL_DOCKER_TYPESENSE using a remote credential
REMOTE_TYPESENSE silently starting or substituting local Typesense
Typesense version changed from 30.1 without current Human-approved requalification
bootstrap/admin Typesense key used as routine owner-test credential
dummy or intentionally unreachable required endpoint
native Compose defaults treated as OWNER TESTS authority merely because they exist
focused subset represented as canonical full OWNER TESTS
OWNER TESTS evidence promoted to OWNER RUNTIME or VINYLHUB DEVELOPMENT
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
source/tree identity for every OWNER TESTS or OWNER RUNTIME claim. A selected
profile's evidence cannot be promoted to the other profile or to App LOCAL
INTEGRATION evidence.

`ENVIRONMENT_ADMISSION = BLOCKED`, a missing field, or an unproven required
service means the dependent semantic environment is `BLOCKED`/`NOT_RUN`, not
PASS. Static checks cannot be promoted to runtime evidence.
