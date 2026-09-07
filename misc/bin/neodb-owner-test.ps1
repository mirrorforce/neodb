[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("LOCAL_DOCKER_TYPESENSE", "REMOTE_TYPESENSE")]
    [string]$Profile,
    [string]$ComposeProject = "neodb-owner-tests",
    [string]$CoveragePath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path (Join-Path $PSScriptRoot "..") "..")).Path
$composeFile = Join-Path $repoRoot "compose.yml"
$runId = [Guid]::NewGuid().ToString("N")
$runSuffix = $runId.Substring(0, 12)
$composeProjectName = "$ComposeProject-$PID-$runSuffix"
$ownerTestImage = "neodb-owner-tests:$composeProjectName"
$collectionPrefix = "neodb_owner_${PID}_$runSuffix"
$dataRoot = Join-Path ([IO.Path]::GetTempPath()) "neodb-owner-tests-$PID-$runId"
$logPath = Join-Path ([IO.Path]::GetTempPath()) "$composeProjectName.log"
$remoteEndpoint = $null
$remoteApiKey = $null
$searchUrl = $null
$sourceSha = $null
$sourceTree = $null
$exitCode = 1
$status = "BLOCKED"
$admission = "BLOCKED"
$testResult = "NOT_RUN"
$cleanup = "NOT_REQUIRED"
$failureStep = $null
$failureExitCode = $null
$failureReason = $null
$cleanupRequired = $false
$cleanupFailed = $false
$cleanupFailureReason = $null
$logLifecycle = "NOT_CREATED"
$reportedLogPath = $null
$composeProfile = $null
$ownerTestService = $null

$originalEnvironment = @{}
foreach ($name in @(
        "NEODB_SEARCH_URL",
        "NEODB_SECRET_KEY",
        "NEODB_SITE_DOMAIN",
        "NEODB_DATA",
        "COMPOSE_DISABLE_ENV_FILE",
        "NEODB_OWNER_TEST_PROFILE",
        "NEODB_OWNER_TEST_SOURCE_SHA",
        "NEODB_OWNER_TEST_SOURCE_TREE",
        "NEODB_OWNER_TEST_IMAGE"
    )) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

function Get-OutputText {
    param([object[]]$Value)

    if ($null -eq $Value) {
        return ""
    }

    return ([string]::Join([Environment]::NewLine, [string[]]$Value)).Trim()
}

function Get-GitValue {
    param([string[]]$Arguments)

    $value = & git @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "git identity lookup failed"
    }

    return Get-OutputText $value
}

function Invoke-Compose {
    param([string[]]$Arguments)

    & docker compose "--project-name" $composeProjectName "--file" $composeFile @Arguments *>> $logPath
    return [int]$LASTEXITCODE
}

function Test-RunImagePresent {
    & docker image inspect $ownerTestImage *> $null
    return [int]$LASTEXITCODE -eq 0
}

function Remove-RunImage {
    & docker image rm --force $ownerTestImage *>> $logPath
    return [int]$LASTEXITCODE
}

function Remove-RunDataRoot {
    if (-not (Test-Path -LiteralPath $dataRoot)) {
        return $true
    }

    try {
        Remove-Item -LiteralPath $dataRoot -Recurse -Force -ErrorAction Stop
    } catch {
        # Linux containers may leave root-owned files in the host bind mount.
    }

    if (Test-Path -LiteralPath $dataRoot) {
        $cleanupImage = "postgres:14-alpine@sha256:727876d274666da0b92a445390ba093c84b8e9f8343e1c53cd4e9a7ab2d85310"
        & docker run --rm `
            --mount "type=bind,source=$dataRoot,target=/neodb-owner-test-data" `
            --entrypoint /bin/sh `
            $cleanupImage `
            -c "rm -rf /neodb-owner-test-data/* /neodb-owner-test-data/.[!.]* /neodb-owner-test-data/..?*" *>> $logPath
        if ([int]$LASTEXITCODE -ne 0) {
            return $false
        }

        Remove-Item -LiteralPath $dataRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    return -not (Test-Path -LiteralPath $dataRoot)
}

function Test-RunResourcesAbsent {
    $containers = & docker container ls --all --filter "label=com.docker.compose.project=$composeProjectName" --format "{{.ID}}" 2>> $logPath
    $containersCode = [int]$LASTEXITCODE
    $networks = & docker network ls --filter "label=com.docker.compose.project=$composeProjectName" --format "{{.Name}}" 2>> $logPath
    $networksCode = [int]$LASTEXITCODE
    $volumes = & docker volume ls --filter "label=com.docker.compose.project=$composeProjectName" --format "{{.Name}}" 2>> $logPath
    $volumesCode = [int]$LASTEXITCODE

    return $containersCode -eq 0 -and $networksCode -eq 0 -and $volumesCode -eq 0 -and
        [string]::IsNullOrWhiteSpace((Get-OutputText $containers)) -and
        [string]::IsNullOrWhiteSpace((Get-OutputText $networks)) -and
        [string]::IsNullOrWhiteSpace((Get-OutputText $volumes))
}

function Copy-CoverageArtifact {
    if ([string]::IsNullOrWhiteSpace($CoveragePath)) {
        return $true
    }

    $coverageDirectory = Split-Path -Parent $CoveragePath
    if ($coverageDirectory) {
        New-Item -ItemType Directory -Path $coverageDirectory -Force | Out-Null
    }

    & docker compose "--project-name" $composeProjectName "--file" $composeFile cp `
        "$ownerTestService`:/neodb/coverage.xml" $CoveragePath *>> $logPath
    return [int]$LASTEXITCODE -eq 0
}

function Restore-ProcessEnvironment {
    foreach ($name in $originalEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], "Process")
    }
}

function Get-TypesenseEndpointUri {
    param([string]$Endpoint)

    if ([string]::IsNullOrWhiteSpace($Endpoint)) {
        throw "NEODB_TYPESENSE_ENDPOINT must be set for REMOTE_TYPESENSE"
    }

    if ($Endpoint -match "^[a-z][a-z0-9+.-]*://") {
        throw "NEODB_TYPESENSE_ENDPOINT must be a remote host or host:port without a URL scheme"
    }

    $endpointUri = [Uri]("http://$Endpoint")
    if ($endpointUri.Scheme -ne "http" -or
        [string]::IsNullOrWhiteSpace($endpointUri.Host) -or
        $endpointUri.UserInfo -or
        ($endpointUri.AbsolutePath -notin @("", "/")) -or
        $endpointUri.Query -or
        $endpointUri.Fragment) {
        throw "NEODB_TYPESENSE_ENDPOINT must be a remote host or host:port without credentials or a path"
    }
    if (-not $endpointUri.IsDefaultPort -and ($endpointUri.Port -lt 1 -or $endpointUri.Port -gt 65535)) {
        throw "NEODB_TYPESENSE_ENDPOINT has an invalid port"
    }
    if ($endpointUri.IsDefaultPort) {
        $builder = [UriBuilder]$endpointUri
        $builder.Port = 8108
        $endpointUri = $builder.Uri
    }
    return $endpointUri
}

function Get-RemoteCollectionNames {
    param(
        [Parameter(Mandatory = $true)]
        [Uri]$Endpoint,
        [Parameter(Mandatory = $true)]
        [hashtable]$Headers
    )

    $collections = Invoke-RestMethod `
        -Uri "$($Endpoint.AbsoluteUri.TrimEnd('/'))/collections" `
        -Headers $Headers `
        -TimeoutSec 10
    return @($collections | ForEach-Object { [string]$_.name })
}

function Remove-RemoteOwnerTestCollections {
    if (-not $remoteEndpoint -or -not $remoteApiKey) {
        return
    }

    $headers = @{ "X-TYPESENSE-API-KEY" = $remoteApiKey }
    $ownedPattern = "^$([Regex]::Escape($collectionPrefix))-(catalog|people|journal)(-gw\d+)?$"
    try {
        $ownedCollections = @(Get-RemoteCollectionNames -Endpoint $remoteEndpoint -Headers $headers |
            Where-Object { $_ -match $ownedPattern })
        foreach ($collection in $ownedCollections) {
            $collectionPath = [Uri]::EscapeDataString($collection)
            Invoke-RestMethod `
                -Method Delete `
                -Uri "$($remoteEndpoint.AbsoluteUri.TrimEnd('/'))/collections/$collectionPath" `
                -Headers $headers `
                -TimeoutSec 10 | Out-Null
        }

        $remaining = @(Get-RemoteCollectionNames -Endpoint $remoteEndpoint -Headers $headers |
            Where-Object { $_ -match $ownedPattern })
        if ($remaining.Count -gt 0) {
            throw "run-owned remote Typesense collection cleanup left residue"
        }
    } catch {
        $script:cleanupFailed = $true
        Write-Error "REMOTE_TYPESENSE_CLEANUP = BLOCKED" -ErrorAction Continue
    }
}

try {
    $dirty = Get-GitValue @("-C", $repoRoot, "status", "--porcelain", "--untracked-files=all")
    if (-not [string]::IsNullOrWhiteSpace($dirty)) {
        $failureStep = "source-preflight"
        $failureReason = "working-tree-not-clean"
        throw "working tree is not clean"
    }

    $sourceSha = Get-GitValue @("-C", $repoRoot, "rev-parse", "HEAD")
    $sourceTree = Get-GitValue @("-C", $repoRoot, "rev-parse", "HEAD^{tree}")

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        $failureStep = "docker-preflight"
        $failureReason = "docker-not-found"
        throw "docker command not found"
    }

    $env:NEODB_OWNER_TEST_PROFILE = $Profile
    $env:NEODB_SECRET_KEY = "test"
    $env:NEODB_SITE_DOMAIN = "example.org"
    $env:NEODB_DATA = $dataRoot
    $env:COMPOSE_DISABLE_ENV_FILE = "1"
    $env:NEODB_OWNER_TEST_SOURCE_SHA = $sourceSha
    $env:NEODB_OWNER_TEST_SOURCE_TREE = $sourceTree
    $env:NEODB_OWNER_TEST_IMAGE = $ownerTestImage
    $cleanupRequired = $true

    if ($Profile -eq "LOCAL_DOCKER_TYPESENSE") {
        $composeProfile = "owner-tests-local"
        $ownerTestService = "neodb-owner-tests-local"
        $searchUrl = "typesense://user:eggplant@typesense:8108/$collectionPrefix"
        $safeEndpoint = "LOCAL_DOCKER"
        $secretSource = "NONE"
    } else {
        $composeProfile = "owner-tests-remote"
        $ownerTestService = "neodb-owner-tests"
        $remoteEndpoint = Get-TypesenseEndpointUri $env:NEODB_TYPESENSE_ENDPOINT
        $remoteApiKey = $env:NEODB_TYPESENSE_API_KEY
        if ([string]::IsNullOrWhiteSpace($remoteApiKey)) {
            throw "NEODB_TYPESENSE_API_KEY must be set for REMOTE_TYPESENSE"
        }
        if ($remoteApiKey -notmatch '^[A-Za-z0-9._~-]+$') {
            throw "REMOTE_TYPESENSE_CREDENTIAL_FORMAT = BLOCKED"
        }

        $typesenseHeaders = @{ "X-TYPESENSE-API-KEY" = $remoteApiKey }
        try {
            $health = Invoke-RestMethod -Uri "$($remoteEndpoint.AbsoluteUri.TrimEnd('/'))/health" -Headers $typesenseHeaders -TimeoutSec 10
            $debug = Invoke-RestMethod -Uri "$($remoteEndpoint.AbsoluteUri.TrimEnd('/'))/debug" -Headers $typesenseHeaders -TimeoutSec 10
            $existingCollections = @(Get-RemoteCollectionNames -Endpoint $remoteEndpoint -Headers $typesenseHeaders)
            if ($health.ok -ne $true -or [string]$debug.version -ne "30.1") {
                throw "unexpected remote Typesense response"
            }
            $ownedPattern = "^$([Regex]::Escape($collectionPrefix))-(catalog|people|journal)(-gw\d+)?$"
            if (@($existingCollections | Where-Object { $_ -match $ownedPattern }).Count -gt 0) {
                throw "run-owned remote Typesense collection namespace is not empty"
            }
        } catch {
            throw "Remote Typesense health/authentication/version check failed"
        }

        $searchUrl = "typesense://user:$remoteApiKey@$($remoteEndpoint.Authority)/$collectionPrefix"
        $safeEndpoint = "CONFIGURED"
        $secretSource = "PROCESS_ENVIRONMENT"
    }

    $env:NEODB_SEARCH_URL = $searchUrl
    $failureStep = "compose-config"
    $exitCode = Invoke-Compose @("--profile", $composeProfile, "config", "--quiet")
    if ($exitCode -ne 0) {
        $failureExitCode = $exitCode
        $failureReason = "compose-config-failed"
        throw "docker compose config failed"
    }

    $failureStep = "owner-test-build"
    $exitCode = Invoke-Compose @("--profile", $composeProfile, "build", $ownerTestService)
    if ($exitCode -ne 0) {
        $failureExitCode = $exitCode
        $failureReason = "owner-test-image-build-failed"
        throw "owner-test image build failed"
    }

    $admission = "PASS"
    $failureStep = "owner-tests"
    $exitCode = Invoke-Compose @(
        "--profile", $composeProfile,
        "up",
        "--abort-on-container-exit",
        "--exit-code-from", $ownerTestService,
        $ownerTestService,
        "neodb-db",
        "takahe-db",
        "redis"
    )
    if ($exitCode -ne 0) {
        $failureExitCode = $exitCode
        $testResult = "FAIL"
        $failureReason = "owner-test-command-failed"
        throw "owner-test command failed"
    }

    if (-not (Copy-CoverageArtifact)) {
        $failureStep = "coverage-copy"
        $failureReason = "coverage-artifact-copy-failed"
        throw "coverage artifact copy failed"
    }

    $testResult = "PASS"
    $status = "PASS"
    $failureStep = $null
} catch {
    if (-not $failureReason) {
        $failureReason = "owner-test-entrypoint-failed"
    }
} finally {
    try {
        Remove-RemoteOwnerTestCollections
        if ($cleanupRequired) {
            $downCode = Invoke-Compose @("--profile", $composeProfile, "down", "--volumes", "--remove-orphans")
            $removeImageCode = Remove-RunImage
            $imageRemains = Test-RunImagePresent
            $resourcesRemain = -not (Test-RunResourcesAbsent)
            $dataRemains = -not (Remove-RunDataRoot)
            if ($downCode -eq 0 -and $removeImageCode -eq 0 -and -not $imageRemains -and -not $resourcesRemain -and -not $dataRemains -and -not $cleanupFailed) {
                $cleanup = "PASS"
            } else {
                $cleanup = "BLOCKED"
                $cleanupFailed = $true
                if ($downCode -ne 0) {
                    $cleanupFailureReason = "compose-down-failed"
                } elseif ($removeImageCode -ne 0) {
                    $cleanupFailureReason = "owner-test-image-remove-failed"
                } elseif ($imageRemains) {
                    $cleanupFailureReason = "owner-test-image-remains"
                } elseif ($resourcesRemain) {
                    $cleanupFailureReason = "compose-resources-remain"
                } elseif ($dataRemains) {
                    $cleanupFailureReason = "disposable-data-remains"
                } else {
                    $cleanupFailureReason = "remote-collection-cleanup-failed"
                }
            }
        }
    } catch {
        $cleanup = "BLOCKED"
        $cleanupFailed = $true
    } finally {
        Restore-ProcessEnvironment
    }
}

if ($cleanupFailed -and $status -eq "PASS") {
    $status = "BLOCKED"
    $failureStep = "cleanup"
    $failureExitCode = 1
    $failureReason = $cleanupFailureReason ?? "disposable-project-cleanup-failed"
}

if ($status -eq "PASS") {
    if (Test-Path -LiteralPath $logPath) {
        Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $logPath) {
        $status = "BLOCKED"
        $cleanup = "BLOCKED"
        $failureStep = "log-cleanup"
        $failureReason = "run-log-delete-failed"
        $logLifecycle = "BLOCKED_DELETE_FAILED"
        $reportedLogPath = $logPath
    } else {
        $logLifecycle = "DELETED_ON_PASS"
    }
} elseif (Test-Path -LiteralPath $logPath) {
    $logLifecycle = "RETAINED_FAILURE_DIAGNOSTIC"
    $reportedLogPath = $logPath
}

$result = [ordered]@{
    status = $status
    evidenceClass = "OWNER TESTS"
    admission = $admission
    testResult = $testResult
    sourceSha = $sourceSha
    sourceTree = $sourceTree
    ownerTestsProfile = $Profile
    typesenseVersion = "30.1"
    project = $composeProjectName
    ownerTestImage = $ownerTestImage
    cleanup = $cleanup
    logLifecycle = $logLifecycle
    logPath = $reportedLogPath
    failureStep = $failureStep
    failureExitCode = $failureExitCode
    failureReason = $failureReason
}

Write-Output ($result | ConvertTo-Json -Compress)

if ($status -eq "PASS") {
    exit 0
}

exit 1
