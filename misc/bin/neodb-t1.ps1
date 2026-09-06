[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("LOCAL_DOCKER_TYPESENSE", "REMOTE_TYPESENSE")]
    [string]$Profile,
    [string]$ComposeProject = "neodb-owner-tests"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$dataRoot = Join-Path ([IO.Path]::GetTempPath()) "neodb-owner-tests-$PID"
$remoteEndpoint = $null
$remoteApiKey = $null
$searchUrl = $null
$exitCode = 1

$originalEnvironment = @{}
foreach ($name in @(
        "NEODB_SEARCH_URL",
        "NEODB_DATA",
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

    $endpointUri = if ($Endpoint -match "^https?://") {
        [Uri]$Endpoint
    } else {
        [Uri]("http://$Endpoint")
    }
    if ($endpointUri.Scheme -notin @("http", "https") -or
        [string]::IsNullOrWhiteSpace($endpointUri.Host) -or
        $endpointUri.UserInfo -or
        ($endpointUri.AbsolutePath -notin @("", "/")) -or
        $endpointUri.Query -or
        $endpointUri.Fragment) {
        throw "NEODB_TYPESENSE_ENDPOINT must be a host, host:port, or an HTTP(S) endpoint without credentials or a path"
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

try {
    $env:NEODB_OWNER_TEST_PROFILE = $Profile
    $env:NEODB_DATA = $dataRoot
    $env:NEODB_OWNER_TEST_SOURCE_SHA = (& git -C $repoRoot rev-parse HEAD).Trim()
    $env:NEODB_OWNER_TEST_SOURCE_TREE = (& git -C $repoRoot rev-parse "HEAD^{tree}").Trim()

    if ($Profile -eq "LOCAL_DOCKER_TYPESENSE") {
        $composeProfile = "owner-tests-local"
        $ownerTestService = "neodb-owner-tests-local"
        $searchUrl = "typesense://user:eggplant@typesense:8108/catalog"
        $safeEndpoint = "typesense:8108"
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
            $null = Invoke-RestMethod -Uri "$($remoteEndpoint.AbsoluteUri.TrimEnd('/'))/collections" -Headers $typesenseHeaders -TimeoutSec 10
            if ($health.ok -ne $true -or [string]$debug.version -ne "30.1") {
                throw "unexpected remote Typesense response"
            }
        } catch {
            throw "Remote Typesense health/authentication/version check failed"
        }

        $escapedApiKey = [Uri]::EscapeDataString($remoteApiKey)
        $searchUrl = "typesense://user:$escapedApiKey@$($remoteEndpoint.Authority)/catalog"
        $safeEndpoint = $remoteEndpoint.Authority
        $secretSource = "PROCESS_ENVIRONMENT"
    }

    $env:NEODB_SEARCH_URL = $searchUrl
    "OWNER_TESTS_PROFILE = $Profile"
    "TYPESENSE_VERSION = 30.1"
    "TYPESENSE_ENDPOINT = $safeEndpoint"
    "TYPESENSE_SECRET_SOURCE = $secretSource"
    "SECRET_VALUE_RETAINED_IN_REPORT = NO"

    Push-Location $repoRoot
    try {
        $composeArguments = @(
            "compose",
            "-p", $ComposeProject,
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
    Push-Location $repoRoot
    try {
        & docker compose -p $ComposeProject down --volumes --remove-orphans | Out-Host
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
