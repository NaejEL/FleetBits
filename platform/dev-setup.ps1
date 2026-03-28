#!/usr/bin/env pwsh
<#
.SYNOPSIS
    One-command local dev setup for FleetBits.

.DESCRIPTION
    Generates secrets, writes config files, builds images, and starts the
    full stack. Safe to re-run — existing secrets are preserved unless
    -Force is passed.

.PARAMETER Force
    Regenerate secrets.env and sibling .env files even if they already exist.

.PARAMETER NoBuild
    Write config files only — skip docker compose up.

.EXAMPLE
    .\dev-setup.ps1
    .\dev-setup.ps1 -Force
    .\dev-setup.ps1 -NoBuild
#>

param([switch]$Force, [switch]$NoBuild)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Helpers ───────────────────────────────────────────────────────────────────

function Write-Step { Write-Host "`n==> $args" -ForegroundColor Cyan }
function Write-OK   { Write-Host "    OK  $args" -ForegroundColor Green }
function Write-Warn { Write-Host "    --  $args" -ForegroundColor Yellow }

function New-Secret([int]$bytes = 32) {
    $b = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] $bytes
    $b.GetBytes($buf)
    return [Convert]::ToBase64String($buf)
}

function New-Hex([int]$bytes = 32) {
    $b = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] $bytes
    $b.GetBytes($buf)
    return [BitConverter]::ToString($buf).Replace('-', '').ToLower()
}

# Read KEY=VALUE lines from an env file into a hashtable.
# Handles values containing '=' (e.g. base64 padding, bcrypt hashes).
function Read-EnvFile([string]$file) {
    $h = @{}
    Get-Content $file -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_ -match '^([A-Z_][A-Z0-9_]*)=(.*)$') {
            $h[$Matches[1]] = $Matches[2]
        }
    }
    return $h
}

# ── Locations ─────────────────────────────────────────────────────────────────

$PlatformRoot = $PSScriptRoot
$DockerDir    = Join-Path $PlatformRoot "docker"
$ApiRepo      = Join-Path $PlatformRoot ".." "FleetBits-api"
$UiRepo       = Join-Path $PlatformRoot ".." "FleetBits-ui"
$SecretsEnv   = Join-Path $PlatformRoot "secrets.env"
$OverrideExmp = Join-Path $DockerDir "docker-compose.override.yml.example"
$Override     = Join-Path $DockerDir "docker-compose.override.yml"

Write-Host ""
Write-Host "FleetBits — Local Dev Setup" -ForegroundColor White
Write-Host "Platform : $PlatformRoot"

# ── Prerequisites ─────────────────────────────────────────────────────────────

Write-Step "Checking prerequisites"

if (-not (docker info 2>$null)) {
    Write-Host "ERROR: Docker is not running or not installed." -ForegroundColor Red
    exit 1
}
Write-OK "Docker running"

if (-not (Test-Path $DockerDir)) {
    Write-Host "ERROR: docker/ directory not found at $DockerDir" -ForegroundColor Red
    exit 1
}

$ApiAvailable = Test-Path $ApiRepo
$UiAvailable  = Test-Path $UiRepo

if ($ApiAvailable) { Write-OK "FleetBits-api found" }
else { Write-Warn "FleetBits-api not found at $ApiRepo — clone it as a sibling of FleetBits-platform" }

if ($UiAvailable) { Write-OK "FleetBits-ui found" }
else { Write-Warn "FleetBits-ui not found at $UiRepo — clone it as a sibling of FleetBits-platform" }



# ── Secrets ───────────────────────────────────────────────────────────────────

Write-Step "Preparing secrets"

# Generate fresh values for all random secrets.
$secrets = [ordered]@{
    POSTGRES_PASSWORD                   = New-Secret 18
    FLEET_DB_PASSWORD                   = New-Secret 18
    SEMAPHORE_DB_PASSWORD               = New-Secret 18
    GRAFANA_ADMIN_PASSWORD              = New-Secret 18
    GRAFANA_PROXY_SECRET                = New-Secret 32
    SEMAPHORE_API_KEY                   = New-Hex 32
    FLEET_JWT_SECRET                    = New-Secret 48
    MQTT_BROKER_PASSWORD                = New-Secret 24
    FLEET_UI_SECRET_KEY                 = New-Secret 48
    SEMAPHORE_ACCESS_KEY_ENCRYPTION_KEY = New-Secret 48
    SEMAPHORE_ADMIN_PASSWORD            = New-Secret 18
    OPERATOR_PASSWORD                   = New-Secret 16
}

# Alertmanager bcrypt hash (generated via the caddy image to avoid host dependency).
$alertPw   = New-Secret 16
$alertHash = (docker run --rm caddy:2 caddy hash-password --plaintext $alertPw 2>$null)
if (-not $alertHash) {
    Write-Warn "Could not generate Alertmanager bcrypt hash — using placeholder"
    $alertHash = "CHANGE_ME_BCRYPT_HASH"
}
# Docker Compose interprets bare '$' in env-file values; double them.
if ($alertHash -match '\$' -and $alertHash -notmatch '\$\$') {
    $alertHash = $alertHash -replace '\$', '$$'
}

# Preserved pass-through vars (not randomly generated but must survive re-runs).
$vpsToken  = ""
$gpgKeyId  = ""
$alertUser = "admin"

# If secrets.env already exists (and no -Force), read all existing values and
# use them instead of the freshly-generated defaults. This replaces the old
# per-key backfill logic — existing values are preserved automatically, and
# any newly added key picks up its generated default.
if ((Test-Path $SecretsEnv) -and -not $Force) {
    Write-Warn "secrets.env already exists — preserving existing values (pass -Force to regenerate)"
    $existing = Read-EnvFile $SecretsEnv
    foreach ($k in @($secrets.Keys)) {
        if ($existing.ContainsKey($k) -and $existing[$k]) { $secrets[$k] = $existing[$k] }
    }
    if ($existing["GRAFANA_PROXY_SECRET"]) { } # covered by the loop above
    if ($existing["ALERTMANAGER_BASIC_AUTH_HASH"]) { $alertHash = $existing["ALERTMANAGER_BASIC_AUTH_HASH"] }
    if ($existing["ALERTMANAGER_BASIC_AUTH_USER"]) { $alertUser = $existing["ALERTMANAGER_BASIC_AUTH_USER"] }
    if ($existing["VPS_DEVICE_TOKEN"])              { $vpsToken  = $existing["VPS_DEVICE_TOKEN"] }
    if ($existing["APTLY_GPG_KEY_ID"])              { $gpgKeyId  = $existing["APTLY_GPG_KEY_ID"] }
}

Write-OK "Secrets ready"

# ── secrets.env ───────────────────────────────────────────────────────────────

Write-Step "Writing secrets.env"
@"
# ============================================================
# FleetBits Platform — LOCAL DEV secrets
# Generated by dev-setup.ps1 — DO NOT COMMIT
# ============================================================

FLEET_DOMAIN=localhost

POSTGRES_PASSWORD=$($secrets.POSTGRES_PASSWORD)
FLEET_DB_PASSWORD=$($secrets.FLEET_DB_PASSWORD)
SEMAPHORE_DB_PASSWORD=$($secrets.SEMAPHORE_DB_PASSWORD)

GRAFANA_ADMIN_PASSWORD=$($secrets.GRAFANA_ADMIN_PASSWORD)
GRAFANA_PROXY_SECRET=$($secrets.GRAFANA_PROXY_SECRET)

SEMAPHORE_API_KEY=$($secrets.SEMAPHORE_API_KEY)

FLEET_JWT_SECRET=$($secrets.FLEET_JWT_SECRET)
MQTT_BROKER_USERNAME=fleet_exporter
MQTT_BROKER_PASSWORD=$($secrets.MQTT_BROKER_PASSWORD)
FLEET_UI_SECRET_KEY=$($secrets.FLEET_UI_SECRET_KEY)
SEMAPHORE_ACCESS_KEY_ENCRYPTION_KEY=$($secrets.SEMAPHORE_ACCESS_KEY_ENCRYPTION_KEY)
SEMAPHORE_ADMIN_PASSWORD=$($secrets.SEMAPHORE_ADMIN_PASSWORD)

FLEETBITS_API_IMAGE=fleetbits-api:dev
FLEETBITS_UI_IMAGE=fleetbits-ui:dev

FLEET_API_INTERNAL_URL=http://fleet-api:8000
GRAFANA_INTERNAL_URL=http://grafana:3000
GRAFANA_PROXY_SECRET=$($secrets.GRAFANA_PROXY_SECRET)

APTLY_GPG_KEY_ID=$gpgKeyId

FLEET_ENV=development
ALLOW_ALL_ORIGINS=true
FLASK_DEBUG=true

OPERATOR_USERNAME=admin
OPERATOR_PASSWORD=$($secrets.OPERATOR_PASSWORD)

ALERTMANAGER_BASIC_AUTH_USER=$alertUser
ALERTMANAGER_BASIC_AUTH_HASH=$alertHash

VPS_DEVICE_TOKEN=$vpsToken
"@ | Set-Content -Encoding utf8 $SecretsEnv

Write-OK "secrets.env written  (login: admin / $($secrets.OPERATOR_PASSWORD))"


# ── docker-compose.override.yml ───────────────────────────────────────────────

Write-Step "Preparing docker/docker-compose.override.yml"

if (-not (Test-Path $Override)) {
    if (-not (Test-Path $OverrideExmp)) {
        Write-Host "ERROR: $OverrideExmp not found." -ForegroundColor Red; exit 1
    }
    Copy-Item $OverrideExmp $Override
    Write-OK "Copied from .example"
} else {
    Write-Warn "Override already exists — not changed (delete it to reset)"
}

# ── Sibling .env files ────────────────────────────────────────────────────────

if ($ApiAvailable) {
    $apiEnv = Join-Path $ApiRepo ".env"
    if (-not (Test-Path $apiEnv) -or $Force) {
        Write-Step "Writing FleetBits-api/.env"
        @"
# FleetBits API — local dev
# Generated by dev-setup.ps1 — DO NOT COMMIT

DATABASE_URL=postgresql+asyncpg://fleet:$($secrets.FLEET_DB_PASSWORD)@localhost:5432/fleet

SEMAPHORE_URL=http://localhost:3001
SEMAPHORE_API_KEY=$($secrets.SEMAPHORE_API_KEY)
SEMAPHORE_PROJECT_ID=1
SEMAPHORE_DEPLOY_TEMPLATE_ID=1
SEMAPHORE_ROLLBACK_TEMPLATE_ID=2
SEMAPHORE_RESTART_TEMPLATE_ID=3
SEMAPHORE_DIAGNOSTICS_TEMPLATE_ID=4
SEMAPHORE_LOGS_TEMPLATE_ID=5

FLEET_JWT_SECRET=$($secrets.FLEET_JWT_SECRET)
FLEET_JWT_ALGORITHM=HS256
FLEET_JWT_EXPIRE_MINUTES=480

PROMETHEUS_URL=http://localhost:9090
LOKI_URL=http://localhost:3100
ALERTMANAGER_URL=http://localhost:9093

FLEET_ENV=development
ALLOW_ALL_ORIGINS=true
FLEET_API_URL=http://localhost:8000

OPERATOR_USERNAME=admin
OPERATOR_PASSWORD=$($secrets.OPERATOR_PASSWORD)

GRAFANA_INTERNAL_URL=http://localhost:3000
GRAFANA_ADMIN_PASSWORD=$($secrets.GRAFANA_ADMIN_PASSWORD)
GRAFANA_PROXY_SECRET=$($secrets.GRAFANA_PROXY_SECRET)
"@ | Set-Content -Encoding utf8 $apiEnv
        Write-OK "FleetBits-api/.env written"
    } else {
        Write-Warn "FleetBits-api/.env already exists — not changed (pass -Force to overwrite)"
    }
}

# ── Write FleetBits-ui .env ───────────────────────────────────────────────────

if ($UiAvailable) {
    $uiEnv = Join-Path $UiRepo ".env"
    if (-not (Test-Path $uiEnv) -or $Force) {
        Write-Step "Writing FleetBits-ui/.env"
        @"
# FleetBits UI — local dev
# Generated by dev-setup.ps1 — DO NOT COMMIT

SECRET_KEY=$($secrets.FLEET_UI_SECRET_KEY)
FLEET_API_URL=http://localhost:8000
# Dev: Grafana iframes go through Caddy /grafana/ so forward_auth is enforced.
GRAFANA_URL=http://localhost/grafana
SEMAPHORE_URL=http://localhost/semaphore
FLEET_DOMAIN=localhost
FLEET_ENV=development
FLASK_DEBUG=true
"@ | Set-Content -Encoding utf8 $uiEnv
        Write-OK "FleetBits-ui/.env written"
    } else {
        Write-Warn "FleetBits-ui/.env already exists — not changed (pass -Force to overwrite)"
    }
}

# ── docker compose up ─────────────────────────────────────────────────────────

if ($NoBuild) {
    Write-Host "`nSkipping docker compose (--NoBuild passed)." -ForegroundColor Yellow
} else {
    Write-Step "Starting stack  (docker compose up --build -d)"
    Write-Host "    This may take a few minutes on first run while images are pulled/built."

    Push-Location $DockerDir
    try {
        docker compose --env-file ../secrets.env up --build -d
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: docker compose exited with code $LASTEXITCODE" -ForegroundColor Red
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
    Write-OK "Stack is up"

    # ── Seed demo data ─────────────────────────────────────────────────────────
    Write-Step "Seeding demo data"
    $token = $null
    Write-Host "    Waiting for API to be ready ..."
    for ($i = 0; $i -lt 30 -and -not $token; $i++) {
        try {
            $r = Invoke-RestMethod -Method Post `
                -Uri "http://localhost:8000/api/v1/auth/login" `
                -ContentType "application/json" `
                -Body (@{ username = "admin"; password = $secrets.OPERATOR_PASSWORD } | ConvertTo-Json)
            $token = $r.access_token
        } catch { Start-Sleep 2 }
    }
    if ($token) {
        $h = @{ Authorization = "Bearer $token" }
        function Invoke-Seed([string]$uri, $body, [string]$label) {
            try {
                Invoke-RestMethod -Method Post -Uri "http://localhost:8000$uri" -Headers $h `
                    -ContentType "application/json" -Body ($body | ConvertTo-Json) | Out-Null
                Write-Host "    + $label" -ForegroundColor DarkGray
            } catch {
                $code = $_.Exception.Response.StatusCode.value__
                if ($code -eq 409) {
                    Write-Host "    + $label (already exists)" -ForegroundColor DarkGray
                } else {
                    Write-Warn "seed $label — $($_.Exception.Response.StatusCode)"
                }
            }
        }
        Invoke-Seed "/api/v1/profiles" @{ profile_id = "default-kiosk"; name = "Default Kiosk Profile"; baseline_stack = @{} } "profile/default-kiosk"
        Write-OK "Demo data seeded"
    } else {
        Write-Warn "API did not become ready in time — seed skipped (run manually)"
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor White
Write-Host " FleetBits dev stack ready" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor White
Write-Host ""
Write-Host "  Fleet UI        http://localhost             (admin / $($secrets.OPERATOR_PASSWORD))"
Write-Host "  Fleet API docs  http://localhost:8000/docs"
Write-Host "  Grafana         http://localhost:3000        (admin / $($secrets.GRAFANA_ADMIN_PASSWORD))"
Write-Host "  Semaphore       http://localhost/semaphore"
Write-Host "  Prometheus      http://localhost:9090"
Write-Host ""
Write-Host "  Credentials are saved in secrets.env — keep it private." -ForegroundColor Yellow
Write-Host ""
Write-Host "  To stop:   cd docker; docker compose --env-file ../secrets.env down" -ForegroundColor DarkGray
Write-Host "  To reset:  .\dev-setup.ps1 -Force" -ForegroundColor DarkGray
Write-Host ""
