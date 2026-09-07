[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$wrapperPath = Join-Path $PSScriptRoot "neodb-owner-test.ps1"
$script:MockDockerCalls = [System.Collections.Generic.List[string]]::new()
$script:MockTypesenseRequests = [System.Collections.Generic.List[string]]::new()
$script:DeletedRemoteCollections = [System.Collections.Generic.List[string]]::new()

function Assert-Contract {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not $Condition) {
        throw "CONTRACT FAILURE: $Message"
    }
}

function git {
    $arguments = $args -join " "
    $global:LASTEXITCODE = 0
    if ($arguments -match "rev-parse HEAD\^\{tree\}") {
        return "f2d4fa8e1c9a0e2bde818da5d81d1e70a12f6f80"
    }
    if ($arguments -match "rev-parse HEAD") {
        return "102bb2edfb4277e1611a8c01ba8bb8b457577660"
    }
    return
}

function docker {
    $arguments = @($args | ForEach-Object { [string]$_ })
    $command = $arguments -join " "
    $script:MockDockerCalls.Add($command)
    $global:LASTEXITCODE = 0

    if ($command -match "image inspect") {
        $global:LASTEXITCODE = 1
    }

    if ($command -match "compose" -and $env:NEODB_SEARCH_URL -match "neodb_owner_\d+_[0-9a-f]{12}") {
        $script:MockDockerCalls.Add("RUN_UNIQUE_SEARCH_NAMESPACE=PASS")
    }
    if ($command -match "compose" -and $env:NEODB_SEARCH_URL -match "remote-contract-secret") {
        $script:MockDockerCalls.Add("REMOTE_SECRET_LEAK=FAIL")
    }
}

function Invoke-RestMethod {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [int]$TimeoutSec,
        [string]$Method = "Get"
    )

    $script:MockTypesenseRequests.Add("$Method $Uri")
    $global:LASTEXITCODE = 0
    if ($Uri -match "/health$") {
        return [pscustomobject]@{ ok = $true }
    }
    if ($Uri -match "/debug$") {
        return [pscustomobject]@{ version = "30.1" }
    }
    if ($Uri -match "/collections$") {
        if ($env:NEODB_SEARCH_URL -match "typesense://.*@[^/]+/(?<prefix>neodb_owner_\d+_[0-9a-f]{12})") {
            $prefix = $Matches.prefix
            $names = @(
                "$prefix-catalog",
                "$prefix-people-gw1",
                "vinylhub-dev-catalog",
                "other-run-catalog"
            ) | Where-Object { $script:DeletedRemoteCollections -notcontains $_ }
            return @($names | ForEach-Object { [pscustomobject]@{ name = $_ } })
        }
        return @()
    }
    if ($Method -eq "Delete") {
        $script:DeletedRemoteCollections.Add(($Uri -split "/")[-1])
        return [pscustomobject]@{}
    }
    throw "Unexpected mocked Typesense request: $Method $Uri"
}

function Get-EnvironmentSnapshot {
    $snapshot = @{}
    foreach ($name in @(
            "NEODB_SEARCH_URL",
            "NEODB_SECRET_KEY",
            "NEODB_SITE_DOMAIN",
            "NEODB_DATA",
            "COMPOSE_DISABLE_ENV_FILE",
            "NEODB_OWNER_TEST_PROFILE",
            "NEODB_OWNER_TEST_SOURCE_SHA",
            "NEODB_OWNER_TEST_SOURCE_TREE",
            "NEODB_OWNER_TEST_IMAGE",
            "NEODB_TYPESENSE_ENDPOINT",
            "NEODB_TYPESENSE_API_KEY",
            "OS",
            "RUNNER_OS"
        )) {
        $snapshot[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    return $snapshot
}

function Assert-EnvironmentSnapshot {
    param(
        [hashtable]$Expected,
        [string]$Context = "wrapper invocation"
    )

    $actual = Get-EnvironmentSnapshot
    foreach ($name in $Expected.Keys) {
        Assert-Contract ($actual[$name] -eq $Expected[$name]) "process environment was not restored for $name ($Context)"
    }
}

function Assert-OwnerTestEnvelope {
    param([pscustomobject]$Result)

    foreach ($name in @(
            "status",
            "evidenceClass",
            "admission",
            "testResult",
            "sourceSha",
            "sourceTree",
            "ownerTestsProfile",
            "typesenseVersion",
            "project",
            "cleanup",
            "failureStep",
            "failureExitCode",
            "failureReason"
        )) {
        Assert-Contract ($null -ne $Result.PSObject.Properties[$name]) "OWNER TESTS envelope is missing $name"
    }
    Assert-Contract ($Result.evidenceClass -eq "OWNER TESTS") "OWNER TESTS envelope evidence class changed"
    Assert-Contract ($Result.typesenseVersion -eq "30.1") "Typesense version changed"
}

function Set-EnvironmentValue {
    param([string]$Name, [AllowNull()][string]$Value)
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Restore-EnvironmentSnapshot {
    param([hashtable]$Snapshot)

    foreach ($name in $Snapshot.Keys) {
        $value = $Snapshot[$name]
        if ($null -eq $value) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        } else {
            Set-EnvironmentValue -Name $name -Value $value
        }
    }
}

function Invoke-WrapperContract {
    param([ValidateSet("LOCAL_DOCKER_TYPESENSE", "REMOTE_TYPESENSE")][string]$Profile)
    @(. $wrapperPath -Profile $Profile -ComposeProject "contract-test")
}

Assert-Contract ((Get-Command docker).CommandType -eq "Function") "Docker boundary was not replaced by the test double"
Assert-Contract ((Get-Command git).CommandType -eq "Function") "Git boundary was not replaced by the test double"
$wrapperSource = Get-Content -Raw $wrapperPath
foreach ($forbiddenToken in @('$IsWindows', 'OSVersion', 'RuntimeInformation', 'RUNNER_OS', 'GITHUB_ACTIONS', 'CI')) {
    Assert-Contract (-not $wrapperSource.Contains($forbiddenToken)) "wrapper contains profile-selection token $forbiddenToken"
}

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
    Set-EnvironmentValue $name "sentinel-$name"
}
Set-EnvironmentValue "NEODB_TYPESENSE_ENDPOINT" "remote-contract.example:8108"
Set-EnvironmentValue "NEODB_TYPESENSE_API_KEY" "remote-contract-secret"
$localEnvironment = Get-EnvironmentSnapshot
$script:MockDockerCalls.Clear()
$script:MockTypesenseRequests.Clear()
Set-EnvironmentValue "OS" "Windows_NT"
Set-EnvironmentValue "RUNNER_OS" "Windows"
try {
    $localResult = (Invoke-WrapperContract "LOCAL_DOCKER_TYPESENSE" | ConvertFrom-Json)
} finally {
    Restore-EnvironmentSnapshot $localEnvironment
}

Assert-OwnerTestEnvelope $localResult
Assert-Contract ($localResult.status -eq "PASS") "LOCAL profile did not reach the mocked Docker boundary"
Assert-Contract ($localResult.ownerTestsProfile -eq "LOCAL_DOCKER_TYPESENSE") "LOCAL profile was rewritten"
Assert-Contract ($localResult.cleanup -eq "PASS") "LOCAL profile did not report cleanup PASS"
Assert-Contract ($script:MockDockerCalls -contains "RUN_UNIQUE_SEARCH_NAMESPACE=PASS") "LOCAL profile did not use a run-unique namespace"
Assert-Contract (-not ($script:MockDockerCalls -contains "REMOTE_SECRET_LEAK=FAIL")) "LOCAL profile consumed remote credentials"
Assert-Contract ($script:MockTypesenseRequests.Count -eq 0) "LOCAL profile performed remote Typesense I/O"
Assert-EnvironmentSnapshot $localEnvironment "LOCAL Windows-like invocation"

$remoteEnvironment = Get-EnvironmentSnapshot
Set-EnvironmentValue "NEODB_TYPESENSE_ENDPOINT" $null
Set-EnvironmentValue "NEODB_TYPESENSE_API_KEY" $null
$missingEnvironment = Get-EnvironmentSnapshot
$script:MockDockerCalls.Clear()
$script:MockTypesenseRequests.Clear()
$missingResult = (Invoke-WrapperContract "REMOTE_TYPESENSE" | ConvertFrom-Json)

Assert-OwnerTestEnvelope $missingResult
Assert-Contract ($missingResult.status -eq "BLOCKED") "REMOTE missing input was not blocked"
Assert-Contract ($missingResult.testResult -eq "NOT_RUN") "REMOTE missing input unexpectedly ran tests"
Assert-Contract (-not ($script:MockDockerCalls | Where-Object { $_ -match "compose.*(config|build|up)" })) "REMOTE missing input fell back to LOCAL/startup"
Assert-EnvironmentSnapshot $missingEnvironment "REMOTE missing-input invocation"

Set-EnvironmentValue "NEODB_TYPESENSE_ENDPOINT" "remote-contract.example:8108"
Set-EnvironmentValue "NEODB_TYPESENSE_API_KEY" "remote-contract-secret"
$remoteEnvironment = Get-EnvironmentSnapshot
$script:MockDockerCalls.Clear()
$script:MockTypesenseRequests.Clear()
$script:DeletedRemoteCollections.Clear()
$remoteResult = (Invoke-WrapperContract "REMOTE_TYPESENSE" | ConvertFrom-Json)

Assert-OwnerTestEnvelope $remoteResult
Assert-Contract ($remoteResult.status -eq "PASS") "REMOTE caller process environment was not accepted"
Assert-Contract ($remoteResult.ownerTestsProfile -eq "REMOTE_TYPESENSE") "REMOTE profile was rewritten"
Assert-Contract ($remoteResult.cleanup -eq "PASS") "REMOTE profile did not report cleanup PASS"
Assert-Contract ($script:DeletedRemoteCollections.Count -eq 2) "REMOTE cleanup did not target exactly the run-owned collections"
Assert-Contract (@($script:DeletedRemoteCollections | Where-Object { $_ -match "^neodb_owner_\d+_[0-9a-f]{12}-(catalog|people-gw1)$" }).Count -eq 2) "REMOTE cleanup used a non-run-owned collection name"
Assert-Contract (@($script:DeletedRemoteCollections | Where-Object { $_ -match "vinylhub-dev|other-run" }).Count -eq 0) "REMOTE cleanup broadened its deletion authority"
Assert-EnvironmentSnapshot $remoteEnvironment "REMOTE caller-input invocation"

Write-Output "neodb-owner-test contract tests: PASS"
