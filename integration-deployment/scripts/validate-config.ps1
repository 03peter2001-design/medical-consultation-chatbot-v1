$ErrorActionPreference = 'Stop'
$deployRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $deployRoot '..')).Path

$required = @(
    '.env.example', 'docker-compose.yml', 'nginx\default.conf.template',
    'iis\ai-api-rewrite.rules.xml', 'iis\doctor-static.web.config',
    'scripts\deploy-ubuntu.sh', 'scripts\backup-sqlite.sh',
    'scripts\restore-sqlite.sh', 'scripts\deploy-doctor.ps1'
)
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $deployRoot $relative))) {
        throw "Missing deployment file: $relative"
    }
}

[xml](Get-Content -LiteralPath (Join-Path $deployRoot 'iis\ai-api-rewrite.rules.xml') -Raw) | Out-Null
[xml](Get-Content -LiteralPath (Join-Path $deployRoot 'iis\doctor-static.web.config') -Raw) | Out-Null

$compose = Get-Content -LiteralPath (Join-Path $deployRoot 'docker-compose.yml') -Raw
$nginx = Get-Content -LiteralPath (Join-Path $deployRoot 'nginx\default.conf.template') -Raw
$exampleEnv = Get-Content -LiteralPath (Join-Path $deployRoot '.env.example') -Raw
foreach ($needle in @('workers', '"1"', 'ENABLE_UNVERSIONED_ALIASES', 'CORS_ALLOWED_ORIGINS', 'internal: true', 'backend-egress', 'AVATAR_CSP_CONNECT_SRC_SUFFIX')) {
    if (-not $compose.Contains($needle)) { throw "Compose invariant missing: $needle" }
}
foreach ($needle in @('frame-ancestors ''none''', 'client_max_body_size 12m', 'proxy_read_timeout 180s', 'allow ${UCC_SOURCE_CIDR}', '$request_method $uri', 'connect-src ''self''${AVATAR_CSP_CONNECT_SRC_SUFFIX}', 'script-src ''self''')) {
    if (-not $nginx.Contains($needle)) { throw "Nginx invariant missing: $needle" }
}
if ($nginx.Contains('https://esm.sh')) {
    throw 'Patient CSP must not allow the obsolete remote D-ID SDK origin.'
}
foreach ($blockedPublicRoute in @('location ^~ /api/v1/doctor/', 'location = /api/v1/invitations')) {
    if (-not $nginx.Contains($blockedPublicRoute)) { throw "Public route block missing: $blockedPublicRoute" }
}
if (-not $exampleEnv.Contains('UCC_JWT_AUDIENCE=medical-consultation-api')) {
    throw 'Deployment JWT audience no longer matches the eHIS AiConsult default.'
}

$trackedFrontendChanges = git -C $repoRoot status --short -- frontend
if ($trackedFrontendChanges) {
    Write-Warning "Pre-existing changes exist under frontend/; deployment files did not modify them:`n$trackedFrontendChanges"
}

if (Get-Command docker -ErrorAction SilentlyContinue) {
    $envFile = Join-Path $deployRoot '.env'
    if (Test-Path -LiteralPath $envFile) {
        & docker compose --project-directory $deployRoot -f (Join-Path $deployRoot 'docker-compose.yml') config --quiet
        if ($LASTEXITCODE -ne 0) { throw 'docker compose config validation failed.' }
    } else {
        Write-Output 'Skipped docker compose config: integration-deployment/.env is intentionally absent.'
    }
}

Write-Output 'Deployment static validation passed.'
