[CmdletBinding()]
param(
    [string]$ComposeProject = "neodb-owner-tests-local"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$secretRoot = Join-Path $env:USERPROFILE ".vinylhub-secrets"
$endpointFile = if ($env:NEODB_TYPESENSE_ENDPOINT_FILE) {
    $env:NEODB_TYPESENSE_ENDPOINT_FILE
} else {
    Join-Path $secretRoot "typesense-t1.endpoint"
}
$protectedKeyFile = if ($env:NEODB_TYPESENSE_KEY_FILE) {
    $env:NEODB_TYPESENSE_KEY_FILE
} else {
    Join-Path $secretRoot "typesense-t1.dpapi"
}
$dataRoot = Join-Path ([IO.Path]::GetTempPath()) "neodb-owner-tests-$PID"
$secureKey = $null
$keyPointer = [IntPtr]::Zero
$plainKey = $null
$endpoint = $null
$searchUrl = $null

try {
    if (-not (Test-Path -LiteralPath $endpointFile -PathType Leaf)) {
        throw "Typesense endpoint secure-store entry is unavailable: $endpointFile"
    }
    if (-not (Test-Path -LiteralPath $protectedKeyFile -PathType Leaf)) {
        throw "Typesense DPAPI secure-store entry is unavailable: $protectedKeyFile"
    }

    $endpoint = [IO.File]::ReadAllText($endpointFile).Trim()
    $protectedValue = [IO.File]::ReadAllText($protectedKeyFile).Trim()
    if ([string]::IsNullOrWhiteSpace($endpoint) -or [string]::IsNullOrWhiteSpace($protectedValue)) {
        throw "Typesense secure-store entry is empty or unusable"
    }

    $secureKey = ConvertTo-SecureString -String $protectedValue
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        throw "Typesense DPAPI secure-store entry is unusable"
    }

    $endpointUri = if ($endpoint -match "^https?://") {
        [Uri]$endpoint
    } else {
        [Uri]("http://$endpoint")
    }
    if ($endpoint -notmatch "^(?:https?://)?(?:\[[^\]]+\]|[^/:]+):\d+(?:/|$)") {
        $endpointBuilder = [UriBuilder]$endpointUri
        $endpointBuilder.Port = 8108
        $endpointUri = $endpointBuilder.Uri
    }
    $baseUri = $endpointUri.AbsoluteUri.TrimEnd('/')
    $typesenseHeaders = @{ "X-TYPESENSE-API-KEY" = $plainKey }
    try {
        $health = Invoke-RestMethod -Uri "$baseUri/health" -Headers $typesenseHeaders -TimeoutSec 10
        $debug = Invoke-RestMethod -Uri "$baseUri/debug" -Headers $typesenseHeaders -TimeoutSec 10
        $null = Invoke-RestMethod -Uri "$baseUri/collections" -Headers $typesenseHeaders -TimeoutSec 10
        if ($health.ok -ne $true -or [string]$debug.version -ne "30.1") {
            throw "unexpected remote Typesense response"
        }
    } catch {
        throw "Remote Typesense health/authentication check failed"
    }

    # The URL is process-scoped and is never written to a file or emitted.
    $searchUrl = "typesense://user:$plainKey@$($endpointUri.Authority)/catalog"
    $env:NEODB_SEARCH_URL = $searchUrl
    $env:NEODB_DATA = $dataRoot
    $env:NEODB_OWNER_TEST_SOURCE_SHA = (& git -C $repoRoot rev-parse HEAD).Trim()
    $env:NEODB_OWNER_TEST_SOURCE_TREE = (& git -C $repoRoot rev-parse 'HEAD^{tree}').Trim()

    Push-Location $repoRoot
    try {
        & docker compose -p $ComposeProject --profile owner-tests up --build --abort-on-container-exit --exit-code-from neodb-owner-tests neodb-owner-tests neodb-db takahe-db redis
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
        & docker compose -p $ComposeProject --profile owner-tests down --volumes --remove-orphans | Out-Host
    } finally {
        Pop-Location
    }
    if (Test-Path -LiteralPath $dataRoot) {
        Remove-Item -LiteralPath $dataRoot -Recurse -Force
    }
    $env:NEODB_SEARCH_URL = $null
    $env:NEODB_DATA = $null
    $env:NEODB_OWNER_TEST_SOURCE_SHA = $null
    $env:NEODB_OWNER_TEST_SOURCE_TREE = $null
    $plainKey = $null
    $endpoint = $null
    $searchUrl = $null
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
        $keyPointer = [IntPtr]::Zero
    }
    if ($secureKey) {
        $secureKey.Dispose()
    }
}
