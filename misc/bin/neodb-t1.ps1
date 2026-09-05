[CmdletBinding()]
param(
    [string]$ComposeProject = "neodb-owner-tests-local",
    [switch]$Configure
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

if ($Configure) {
    $configurationKey = $null
    $endpointInput = $null
    $protectedConfigurationValue = $null
    $createdConfigurationFiles = @()
    $createdConfigurationDirectories = @()
    try {
        foreach ($path in @($protectedKeyFile, $endpointFile)) {
            if (Test-Path -LiteralPath $path) {
                throw "Existing Typesense configuration detected; refusing overwrite"
            }
        }

        $configurationParents = @(
            (Split-Path -Path $protectedKeyFile -Parent),
            (Split-Path -Path $endpointFile -Parent)
        ) | Where-Object { $_ } | Sort-Object -Unique
        foreach ($parent in $configurationParents) {
            if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
                $createdConfigurationDirectories += $parent
            }
        }

        $endpointInput = (Read-Host "Remote Typesense endpoint").Trim()
        if ([string]::IsNullOrWhiteSpace($endpointInput)) {
            throw "Typesense endpoint must not be empty"
        }
        $configurationKey = Read-Host "Remote Typesense API key" -AsSecureString
        if ($null -eq $configurationKey -or $configurationKey.Length -eq 0) {
            throw "Typesense API key must not be empty"
        }

        $protectedConfigurationValue = ConvertFrom-SecureString -SecureString $configurationKey
        $utf8NoBom = [Text.UTF8Encoding]::new($false)
        [IO.File]::WriteAllText($protectedKeyFile, $protectedConfigurationValue, $utf8NoBom)
        $createdConfigurationFiles += $protectedKeyFile
        [IO.File]::WriteAllText($endpointFile, $endpointInput, $utf8NoBom)
        $createdConfigurationFiles += $endpointFile

        "CONFIGURATION_RESULT = PASS"
        "KEY_FILE_CREATED = YES"
        "ENDPOINT_FILE_CREATED = YES"
    } catch {
        foreach ($path in $createdConfigurationFiles) {
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                Remove-Item -LiteralPath $path -Force
            }
        }
        foreach ($parent in ($createdConfigurationDirectories | Sort-Object Length -Descending)) {
            $parentHasEntries = @(Get-ChildItem -LiteralPath $parent -Force).Count -gt 0
            if ((Test-Path -LiteralPath $parent -PathType Container) -and -not $parentHasEntries) {
                Remove-Item -LiteralPath $parent -Force
            }
        }
        throw "Typesense configuration failed; existing entries were not overwritten"
    } finally {
        if ($configurationKey) {
            $configurationKey.Dispose()
        }
        $endpointInput = $null
        $protectedConfigurationValue = $null
    }
    return
}

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
