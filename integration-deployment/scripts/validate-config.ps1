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
foreach ($needle in @('workers', '"1"', 'ENABLE_UNVERSIONED_ALIASES', 'CORS_ALLOWED_ORIGINS', 'internal: true', 'edge:', 'backend-egress', 'AVATAR_CSP_CONNECT_SRC_SUFFIX', '127.0.0.1:${DEVELOPMENT_API_PORT:-18000}:8000', '${PATIENT_HTTPS_PORT:-443}:443', '${UCC_API_PORT:-8443}:8443', 'https://127.0.0.1/api/v1/health', '${RAG_CHROMA_DB_PATH:-../backend/chroma_db}:/app/chroma_db', 'amir20/dozzle:v10.6.14', 'ghcr.io/tecnativa/docker-socket-proxy:v0.5.0', '127.0.0.1:${CONTAINER_MONITOR_PORT:-18080}:8080', '/var/run/docker.sock:/var/run/docker.sock:ro', 'DOZZLE_REMOTE_HOST: tcp://docker-api-proxy:2375|${COMPOSE_PROJECT_NAME:-medical-consultation}', 'DOZZLE_ENABLE_ACTIONS: "false"', 'DOZZLE_ENABLE_SHELL: "false"', 'DOZZLE_ENABLE_MCP: "false"', 'DOZZLE_NO_ANALYTICS: "true"', 'POST: "0"')) {
    if (-not $compose.Contains($needle)) { throw "Compose invariant missing: $needle" }
}
$animationDefault = 'AVATAR_ANIMATION_ENABLED: ${AVATAR_ANIMATION_ENABLED:-true}'
if ([regex]::Matches($compose, [regex]::Escape($animationDefault)).Count -ne 2) {
    throw 'Backend and Avatar service must both receive the animation default explicitly.'
}
if ($compose.Contains('${RAG_CHROMA_DB_PATH:-../backend/chroma_db}:/app/chroma_db:ro')) {
    throw 'Chroma PersistentClient requires a writable SQLite working directory.'
}
foreach ($needle in @('frame-ancestors ''none''', 'client_max_body_size 12m', 'proxy_read_timeout 180s', 'allow ${UCC_SOURCE_CIDR}', '$request_method $uri', 'connect-src ''self''${AVATAR_CSP_CONNECT_SRC_SUFFIX}', 'script-src ''self''', 'listen 8000;', 'proxy_set_header X-Forwarded-For 127.0.0.1;', 'resolver 127.0.0.11', 'server backend:8000 resolve;')) {
    if (-not $nginx.Contains($needle)) { throw "Nginx invariant missing: $needle" }
}
if ($nginx.Contains('proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;')) {
    throw 'Public proxy routes must overwrite untrusted X-Forwarded-For input.'
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
if (-not $exampleEnv.Contains('ALLOW_LOCAL_AUTH_BYPASS=false')) {
    throw 'Deployment defaults must keep local authentication bypass disabled.'
}
if (-not $exampleEnv.Contains('CONTAINER_MONITOR_PORT=18080')) {
    throw 'Deployment monitor must retain its documented loopback port default.'
}
if (-not $exampleEnv.Contains('AVATAR_ANIMATION_ENABLED=true')) {
    throw 'Deployment defaults must keep Avatar animation enabled for compatibility.'
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

        $composeFile = Join-Path $deployRoot 'docker-compose.yml'
        $resolvedComposeJson = & docker compose --project-directory $deployRoot `
            -f $composeFile config --format json | Out-String
        $composeExitCode = $LASTEXITCODE
        if ($composeExitCode -ne 0) { throw 'docker compose JSON validation failed.' }
        $resolvedCompose = $resolvedComposeJson | ConvertFrom-Json
        $backendAnimationDefault = $resolvedCompose.services.backend.environment.AVATAR_ANIMATION_ENABLED
        $avatarAnimationDefault = $resolvedCompose.services.avatar.environment.AVATAR_ANIMATION_ENABLED
        if ($null -eq $backendAnimationDefault -or
            $backendAnimationDefault -ne $avatarAnimationDefault) {
            throw 'Resolved backend and Avatar animation defaults must remain explicit and equal.'
        }
        $ragMounts = @($resolvedCompose.services.backend.volumes | Where-Object {
            $_.target -eq '/app/chroma_db'
        })
        if ($ragMounts.Count -ne 1) {
            throw "Expected one backend /app/chroma_db mount, found $($ragMounts.Count)."
        }
        if ($ragMounts[0].read_only -eq $true) {
            throw 'Resolved backend /app/chroma_db mount must be writable.'
        }

        $monitor = $resolvedCompose.services.monitor
        if ($monitor.image -ne 'amir20/dozzle:v10.6.14') {
            throw 'Container monitor image must remain pinned to the reviewed Dozzle release.'
        }
        $monitorPorts = @($monitor.ports | Where-Object { $_.target -eq 8080 })
        if ($monitorPorts.Count -ne 1 -or $monitorPorts[0].host_ip -ne '127.0.0.1') {
            throw 'Dozzle port 8080 must have one host-loopback-only binding.'
        }
        $monitorDockerSockets = @($monitor.volumes | Where-Object {
            $_.target -eq '/var/run/docker.sock'
        })
        if ($monitorDockerSockets.Count -ne 0) {
            throw 'Dozzle must use the restricted API proxy, not mount docker.sock directly.'
        }
        foreach ($disabledCapability in @('DOZZLE_ENABLE_ACTIONS', 'DOZZLE_ENABLE_SHELL', 'DOZZLE_ENABLE_MCP')) {
            if ($monitor.environment.$disabledCapability -ne 'false') {
                throw "Dozzle capability must remain disabled: $disabledCapability"
            }
        }
        if ($monitor.environment.DOZZLE_NO_ANALYTICS -ne 'true') {
            throw 'Dozzle analytics must remain disabled.'
        }
        if ($monitor.environment.DOZZLE_REMOTE_HOST -ne "tcp://docker-api-proxy:2375|$($resolvedCompose.name)") {
            throw 'Dozzle must use the internal Docker API proxy.'
        }
        $monitorNetworks = @($monitor.networks.PSObject.Properties.Name)
        if ($monitorNetworks.Count -ne 2 -or
            -not $monitorNetworks.Contains('monitoring') -or
            -not $monitorNetworks.Contains('monitoring-api')) {
            throw 'Dozzle must remain on the monitoring UI and API networks only.'
        }

        $dockerApiProxy = $resolvedCompose.services.'docker-api-proxy'
        if ($dockerApiProxy.image -ne 'ghcr.io/tecnativa/docker-socket-proxy:v0.5.0') {
            throw 'Docker API proxy image must remain pinned to the reviewed release.'
        }
        $proxyPorts = @($dockerApiProxy.ports)
        if ($proxyPorts.Count -ne 0) {
            throw 'Docker API proxy must not publish a host port.'
        }
        $proxySocketMounts = @($dockerApiProxy.volumes | Where-Object {
            $_.target -eq '/var/run/docker.sock'
        })
        if ($proxySocketMounts.Count -ne 1 -or $proxySocketMounts[0].read_only -ne $true) {
            throw 'Docker API proxy must mount exactly one read-only Docker socket.'
        }
        foreach ($requiredProxySetting in @{
            CONTAINERS = '1'; EVENTS = '1'; INFO = '1'; PING = '1'; POST = '0'; VERSION = '1'
        }.GetEnumerator()) {
            if ($dockerApiProxy.environment.($requiredProxySetting.Key) -ne $requiredProxySetting.Value) {
                throw "Docker API proxy setting mismatch: $($requiredProxySetting.Key)"
            }
        }
        $proxyNetworks = @($dockerApiProxy.networks.PSObject.Properties.Name)
        if ($proxyNetworks.Count -ne 1 -or $proxyNetworks[0] -ne 'monitoring-api') {
            throw 'Docker API proxy must remain isolated on the internal monitoring API network.'
        }
        if ($dockerApiProxy.read_only -ne $true) {
            throw 'Docker API proxy root filesystem must remain read-only.'
        }
        if (-not @($dockerApiProxy.cap_drop).Contains('ALL')) {
            throw 'Docker API proxy must drop all Linux capabilities.'
        }
        $proxyTmpfs = @($dockerApiProxy.tmpfs)
        foreach ($requiredTmpfs in @('/tmp', '/run', '/var/lib/haproxy')) {
            if (-not $proxyTmpfs.Contains($requiredTmpfs)) {
                throw "Docker API proxy writable runtime path must use tmpfs: $requiredTmpfs"
            }
        }
        if (-not @($monitor.cap_drop).Contains('ALL')) {
            throw 'Dozzle must drop all Linux capabilities.'
        }
    } else {
        Write-Output 'Skipped docker compose config: integration-deployment/.env is intentionally absent.'
    }
}

Write-Output 'Deployment static validation passed.'
