[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EhisProjectRoot,
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$ehisRoot = (Resolve-Path -LiteralPath $EhisProjectRoot).Path
$project = Get-ChildItem -LiteralPath $ehisRoot -Filter '*.csproj' -File | Select-Object -First 1
if (-not $project) {
    throw "No ASP.NET project was found directly under $ehisRoot"
}

$frontendRoot = Join-Path $RepositoryRoot 'frontend-v2'
$dist = Join-Path $frontendRoot 'apps\doctor\dist'
if (-not $SkipBuild) {
    Push-Location $frontendRoot
    try {
        $oldApiBase = $env:VITE_BACKEND_BASE_URL
        $env:VITE_BACKEND_BASE_URL = '/ai-api'
        & npm.cmd run build:doctor
        if ($LASTEXITCODE -ne 0) { throw 'Doctor frontend build failed.' }
    }
    finally {
        if ($null -eq $oldApiBase) { Remove-Item Env:VITE_BACKEND_BASE_URL -ErrorAction SilentlyContinue }
        else { $env:VITE_BACKEND_BASE_URL = $oldApiBase }
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $dist 'index.html'))) {
    throw "Doctor build output is missing: $dist"
}

$distIndex = Get-Content -LiteralPath (Join-Path $dist 'index.html') -Raw
$bundleMatch = [regex]::Match($distIndex, 'assets/index-([A-Za-z0-9_-]+)\.js')
if (-not $bundleMatch.Success) {
    throw 'Doctor build output does not reference a hashed JavaScript entry.'
}

# eHIS embeds index.html in an iframe. Tie its query-string cache buster to the
# actual Vite entry hash so ordinary refreshes cannot retain an older SPA shell.
$ehisView = Join-Path $ehisRoot 'Views\AiConsult\Index.cshtml'
if (-not (Test-Path -LiteralPath $ehisView)) {
    throw "eHIS AiConsult view is missing: $ehisView"
}
$viewSource = Get-Content -LiteralPath $ehisView -Raw
$versionPattern = 'const string assetVersion = "[^"]+";'
if (-not [regex]::IsMatch($viewSource, $versionPattern)) {
    throw 'eHIS AiConsult view does not contain the expected assetVersion declaration.'
}
$nextVersion = 'const string assetVersion = "doctor-' + $bundleMatch.Groups[1].Value + '";'
$updatedView = [regex]::Replace($viewSource, $versionPattern, $nextVersion, 1)
$viewNeedsUpdate = $updatedView -ne $viewSource

$wwwroot = Join-Path $ehisRoot 'wwwroot'
$target = Join-Path $wwwroot 'ai-consult'
$resolvedWwwroot = [IO.Path]::GetFullPath($wwwroot).TrimEnd('\') + '\'
$resolvedTarget = [IO.Path]::GetFullPath($target)
if (-not $resolvedTarget.StartsWith($resolvedWwwroot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to deploy outside eHIS wwwroot: $resolvedTarget"
}

if ((Test-Path -LiteralPath $target) -or $viewNeedsUpdate) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $ehisRoot ".deployment-backups\ai-consult-$stamp"
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
}
if (Test-Path -LiteralPath $target) {
    Copy-Item -LiteralPath $target -Destination $backup -Recurse
    Remove-Item -LiteralPath $target -Recurse -Force
}
if ($viewNeedsUpdate) {
    Copy-Item -LiteralPath $ehisView -Destination (Join-Path $backup 'Index.cshtml')
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $dist '*') -Destination $target -Recurse -Force
Copy-Item -LiteralPath (Join-Path $RepositoryRoot 'integration-deployment\iis\doctor-static.web.config') `
    -Destination (Join-Path $target 'web.config') -Force
if ($viewNeedsUpdate) {
    [IO.File]::WriteAllText($ehisView, $updatedView, (New-Object Text.UTF8Encoding($false)))
    Write-Output "Updated eHIS iframe cache buster to doctor-$($bundleMatch.Groups[1].Value)"
}

$registrationInstaller = Join-Path $RepositoryRoot 'integration-deployment\scripts\install-registration-invitation.ps1'
if (-not (Test-Path -LiteralPath $registrationInstaller -PathType Leaf)) {
    throw "Registration invitation installer is missing: $registrationInstaller"
}
& $registrationInstaller -EhisProjectRoot $ehisRoot -RepositoryRoot $RepositoryRoot

Write-Output "Doctor frontend deployed to $target"
Write-Output 'Doctor assets and the B01 registration invitation integration are installed in the eHIS source tree.'
Write-Output 'This script does not publish or restart eHIS/IIS.'

