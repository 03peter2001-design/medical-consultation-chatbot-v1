[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$StagingRoot,
    [string]$DeployRoot = 'C:\Deploy\eHIS',
    [string]$AppPoolName = 'eHIS-Pool'
)

$ErrorActionPreference = 'Stop'
$staging = (Resolve-Path -LiteralPath $StagingRoot).Path
$deploy = (Resolve-Path -LiteralPath $DeployRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $deploy 'eHIS.dll') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $deploy 'web.config') -PathType Leaf)) {
    throw "DeployRoot is not an existing eHIS deployment: $deploy"
}

$relativeFiles = @(
    'eHIS.dll',
    'wwwroot\page\js\OP01.js',
    'wwwroot\ai-consult-registration\registration-invitation.js'
)
foreach ($relative in $relativeFiles) {
    $sourceFile = Join-Path $staging $relative
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
        throw "Missing staging file: $relative"
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $deploy ".deployment-backups\b01-registration-qr-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
foreach ($relative in $relativeFiles) {
    $targetFile = Join-Path $deploy $relative
    if (Test-Path -LiteralPath $targetFile -PathType Leaf) {
        $backupFile = Join-Path $backup $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupFile) | Out-Null
        Copy-Item -LiteralPath $targetFile -Destination $backupFile -Force
    }
}

$appcmd = Join-Path $env:windir 'System32\inetsrv\appcmd.exe'
$poolStopped = $false
$deployedFiles = New-Object System.Collections.Generic.List[string]
try {
    & $appcmd stop apppool "/apppool.name:$AppPoolName"
    if ($LASTEXITCODE -ne 0) { throw "Could not stop application pool $AppPoolName." }
    $poolStopped = $true

    foreach ($relative in $relativeFiles) {
        $sourceFile = Join-Path $staging $relative
        $targetFile = Join-Path $deploy $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetFile) | Out-Null
        Copy-Item -LiteralPath $sourceFile -Destination $targetFile -Force
        $deployedFiles.Add($relative)
        if ((Get-FileHash -LiteralPath $sourceFile).Hash -ne (Get-FileHash -LiteralPath $targetFile).Hash) {
            throw "Hash mismatch after copying $relative"
        }
    }
}
catch {
    foreach ($relative in $deployedFiles) {
        $targetFile = Join-Path $deploy $relative
        $backupFile = Join-Path $backup $relative
        if (Test-Path -LiteralPath $backupFile -PathType Leaf) {
            Copy-Item -LiteralPath $backupFile -Destination $targetFile -Force
        }
        elseif (Test-Path -LiteralPath $targetFile -PathType Leaf) {
            Remove-Item -LiteralPath $targetFile -Force
        }
    }
    throw
}
finally {
    if ($poolStopped) {
        & $appcmd start apppool "/apppool.name:$AppPoolName"
        if ($LASTEXITCODE -ne 0) { Write-Error "Could not restart application pool $AppPoolName." }
    }
}

Write-Output "eHIS registration QR deployment completed. Backup: $backup"
