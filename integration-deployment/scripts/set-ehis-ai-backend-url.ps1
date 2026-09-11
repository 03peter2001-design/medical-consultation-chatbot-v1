[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [string]$BackendBaseUrl
)

$ErrorActionPreference = 'Stop'
$config = (Resolve-Path -LiteralPath $ConfigPath).Path
$uri = $null
if (-not [Uri]::TryCreate($BackendBaseUrl, [UriKind]::Absolute, [ref]$uri) -or
    $uri.Scheme -ne [Uri]::UriSchemeHttps -or
    -not [string]::IsNullOrEmpty($uri.UserInfo) -or
    -not [string]::IsNullOrEmpty($uri.Query) -or
    -not [string]::IsNullOrEmpty($uri.Fragment)) {
    throw 'BackendBaseUrl must be an absolute HTTPS URL without credentials, query, or fragment.'
}

$source = [IO.File]::ReadAllText($config)
$pattern = '("BackendBaseUrl"\s*:\s*)"[^"]*"'
$matches = [regex]::Matches($source, $pattern)
if ($matches.Count -ne 1) {
    throw "Expected exactly one AiConsult BackendBaseUrl setting, found $($matches.Count)."
}

$normalizedUrl = $uri.AbsoluteUri
$updated = [regex]::Replace(
    $source,
    $pattern,
    [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $match.Groups[1].Value + '"' + $normalizedUrl + '"' },
    1)
if ($updated -eq $source) {
    Write-Output "AiConsult backend URL is already $normalizedUrl"
    exit 0
}

$backup = "$config.$(Get-Date -Format 'yyyyMMdd-HHmmss').bak"
Copy-Item -LiteralPath $config -Destination $backup -Force
[IO.File]::WriteAllText($config, $updated, (New-Object Text.UTF8Encoding($false)))
Write-Output "Updated AiConsult backend URL to $normalizedUrl"
Write-Output "Previous configuration backup: $backup"
