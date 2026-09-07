[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("LOCAL_DOCKER_TYPESENSE", "REMOTE_TYPESENSE")]
    [string]$Profile,
    [string]$ComposeProject = "neodb-owner-tests"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runId = [Guid]::NewGuid().ToString("N")
$runSuffix = $runId.Substring(0, 12)
$composeProjectName = "$ComposeProject-$PID-$runSuffix"
$collectionPrefix = "neodb_owner_${PID}_$runSuffix"
$dataRoot = Join-Path ([IO.Path]::GetTempPath()) "neodb-owner-tests-$PID-$runId"
$remoteEndpoint = $null
$remoteApiKey = $null
$searchUrl = $null
$exitCode = 1
$cleanupFailed = $false

$originalEnvironment = @{}
foreach ($name in @(
        "NEODB_SEARCH_URL",
        "NEODB_DATA",
        "COMPOSE_DISABLE_ENV_FILE",
        "NEODB_OWNER_TEST_PROFILE",
        "NEODB_OWNER_TEST_SOURCE_SHA",
        "NEODB_OWNER_TEST_SOURCE_TREE"
    )) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
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
    $env:NEODB_OWNER_TEST_PROFILE = $Profile
    $env:NEODB_DATA = $dataRoot
    $env:COMPOSE_DISABLE_ENV_FILE = "1"
    $env:NEODB_OWNER_TEST_SOURCE_SHA = (& git -C $repoRoot rev-parse HEAD).Trim()
    $env:NEODB_OWNER_TEST_SOURCE_TREE = (& git -C $repoRoot rev-parse "HEAD^{tree}").Trim()

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

        $escapedApiKey = [Uri]::EscapeDataString($remoteApiKey)
        $searchUrl = "typesense://user:$escapedApiKey@$($remoteEndpoint.Authority)/$collectionPrefix"
        $safeEndpoint = "CONFIGURED"
        $secretSource = "PROCESS_ENVIRONMENT"
    }

    $env:NEODB_SEARCH_URL = $searchUrl
    "OWNER_TESTS_PROFILE = $Profile"
    "TYPESENSE_VERSION = 30.1"
    "TYPESENSE_ENDPOINT = $safeEndpoint"
    "TYPESENSE_COLLECTION_NAMESPACE = RUN_UNIQUE"
    "OWNER_TEST_PROJECT = RUN_UNIQUE"
    "APP_PERSISTENT_STATE = NOT_ATTACHED"
    "TYPESENSE_SECRET_SOURCE = $secretSource"
    "SECRET_VALUE_RETAINED_IN_REPORT = NO"

    Push-Location $repoRoot
    try {
        $composeArguments = @(
            "compose",
            "-p", $composeProjectName,
            "--profile", $composeProfile,
            "up",
            "--build",
            "--abort-on-container-exit",
            "--exit-code-from", $ownerTestService,
            $ownerTestService,
            "neodb-db",
            "takahe-db",
            "redis"
        )
        & docker @composeArguments
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($exitCode -ne 0) {
        exit $exitCode
    }
} finally {
    Remove-RemoteOwnerTestCollections
    Push-Location $repoRoot
    try {
        & docker compose -p $composeProjectName down --volumes --remove-orphans | Out-Host
        if ($LASTEXITCODE -ne 0) {
            $script:cleanupFailed = $true
            Write-Error "OWNER_TEST_DOCKER_CLEANUP = BLOCKED" -ErrorAction Continue
        }
    } finally {
        Pop-Location
    }
    if (Test-Path -LiteralPath $dataRoot) {
        Remove-Item -LiteralPath $dataRoot -Recurse -Force
    }
    Restore-ProcessEnvironment
    $remoteEndpoint = $null
    $remoteApiKey = $null
    $searchUrl = $null
}

if ($cleanupFailed -and $exitCode -eq 0) {
    exit 1
}
