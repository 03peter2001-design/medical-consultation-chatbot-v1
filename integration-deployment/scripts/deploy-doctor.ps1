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

$wwwroot = Join-Path $ehisRoot 'wwwroot'
$target = Join-Path $wwwroot 'ai-consult'
$resolvedWwwroot = [IO.Path]::GetFullPath($wwwroot).TrimEnd('\') + '\'
$resolvedTarget = [IO.Path]::GetFullPath($target)
if (-not $resolvedTarget.StartsWith($resolvedWwwroot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to deploy outside eHIS wwwroot: $resolvedTarget"
}

if (Test-Path -LiteralPath $target) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $ehisRoot ".deployment-backups\ai-consult-$stamp"
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    Copy-Item -LiteralPath $target -Destination $backup -Recurse
    Remove-Item -LiteralPath $target -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $dist '*') -Destination $target -Recurse -Force
Copy-Item -LiteralPath (Join-Path $RepositoryRoot 'integration-deployment\iis\doctor-static.web.config') `
    -Destination (Join-Path $target 'web.config') -Force

Write-Output "Doctor frontend deployed to $target"
Write-Output 'This script does not publish or restart eHIS/IIS.'

