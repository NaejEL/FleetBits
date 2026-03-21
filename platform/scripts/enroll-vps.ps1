#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Enroll the VPS platform host as a managed fleet-bits device.

.DESCRIPTION
    Idempotent — safe to run multiple times.
    Performs the following steps:
      1. Parse secrets.env to get OPERATOR_USERNAME / OPERATOR_PASSWORD
      2. Obtain an operator JWT from Fleet API
      3. Create site  'control-plane'    (skip if 409)
      4. Create zone  'vps'              (skip if 409)
      5. Create device 'vps-control-plane' (skip if 409)
      6. Issue a new device token
      7. Write VPS_DEVICE_TOKEN to secrets.env

.PARAMETER FleetApiUrl
    Base URL of the Fleet API. Default: http://localhost:8000

.PARAMETER SecretsEnvPath
    Path to secrets.env. Default: <script>/../secrets.env

.EXAMPLE
    .\enroll-vps.ps1
    .\enroll-vps.ps1 -FleetApiUrl http://localhost:8000
#>
[CmdletBinding()]
param(
    [string]$FleetApiUrl    = 'http://localhost:8000',
    [string]$SecretsEnvPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── helpers ──────────────────────────────────────────────────────────────────

function Read-SecretsEnv([string]$Path) {
    $map = @{}
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $key, $val = $line -split '=', 2
        $map[$key.Trim()] = $val.Trim()
    }
    return $map
}

function Update-SecretsEnv([string]$Path, [string]$Key, [string]$Value) {
    $content = Get-Content $Path -Raw
    if ($content -match "(?m)^${Key}=") {
        $content = $content -replace "(?m)^${Key}=.*", "${Key}=${Value}"
    }
    else {
        $content = $content.TrimEnd() + "`n${Key}=${Value}`n"
    }
    Set-Content -Path $Path -Value $content -NoNewline
    Write-Host "  [secrets.env] ${Key} updated."
}

function Invoke-Api([string]$Method, [string]$Url, $Body, [hashtable]$Headers = @{}) {
    $params = @{
        Method      = $Method
        Uri         = $Url
        Headers     = $Headers
        ContentType = 'application/json'
    }
    if ($Body) { $params.Body = ($Body | ConvertTo-Json -Compress -Depth 5) }
    try {
        return Invoke-RestMethod @params
    }
    catch {
        $code = $_.Exception.Response?.StatusCode?.value__
        if ($code -eq 409) { return $null }   # already exists — idempotent
        Write-Error "API call failed [$Method $Url]: $_"
        exit 1
    }
}

# ── resolve paths ─────────────────────────────────────────────────────────────

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SecretsEnvPath) {
    $SecretsEnvPath = Join-Path $scriptDir '..\secrets.env'
}
$SecretsEnvPath = (Resolve-Path $SecretsEnvPath).Path

if (-not (Test-Path $SecretsEnvPath)) {
    Write-Error "secrets.env not found at: $SecretsEnvPath`nCopy secrets.env.example to secrets.env and fill in the values."
    exit 1
}

# ── 1. read credentials ───────────────────────────────────────────────────────

Write-Host "`n[1/6] Reading credentials from secrets.env..."
$secrets = Read-SecretsEnv $SecretsEnvPath

$username = $secrets['OPERATOR_USERNAME']
$password = $secrets['OPERATOR_PASSWORD']

if (-not $username -or -not $password) {
    Write-Warning "OPERATOR_USERNAME / OPERATOR_PASSWORD not found in secrets.env."
    $username = Read-Host 'Fleet operator username'
    $password = Read-Host 'Fleet operator password' -AsSecureString |
                    ForEach-Object { [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($_)) }
}

# ── 2. obtain JWT ─────────────────────────────────────────────────────────────

Write-Host "[2/6] Authenticating as operator '$username'..."
$authResp = Invoke-Api POST "$FleetApiUrl/api/v1/auth/login" @{
    username = $username
    password = $password
}
$jwt = $authResp.access_token
if (-not $jwt) {
    Write-Error "Login failed — no access_token in response."
    exit 1
}
$authHeader = @{ Authorization = "Bearer $jwt" }
Write-Host "  JWT obtained."

# ── 3. create site ────────────────────────────────────────────────────────────
# SiteCreate: { site_id, name, timezone?, quiet_hours? }

Write-Host "[3/6] Creating site 'control-plane'..."
$site = Invoke-Api POST "$FleetApiUrl/api/v1/sites" @{
    site_id = 'control-plane'
    name    = 'Control Plane'
} $authHeader
if ($site) { Write-Host "  Site created." } else { Write-Host "  Site already exists (skipped)." }

# ── 4. create zone ────────────────────────────────────────────────────────────
# ZoneCreate: { zone_id, name, site_id, criticality?, profile_id? }

Write-Host "[4/6] Creating zone 'vps' under 'control-plane'..."
$zone = Invoke-Api POST "$FleetApiUrl/api/v1/zones" @{
    zone_id = 'vps'
    name    = 'VPS'
    site_id = 'control-plane'
} $authHeader
if ($zone) { Write-Host "  Zone created." } else { Write-Host "  Zone already exists (skipped)." }

# ── 5. create device ──────────────────────────────────────────────────────────
# DeviceCreate: { device_id, role, hostname, zone_id?, site_id?, ring?, ... }

Write-Host "[5/6] Creating device 'vps-control-plane'..."
$device = Invoke-Api POST "$FleetApiUrl/api/v1/devices" @{
    device_id = 'vps-control-plane'
    role      = 'control-plane-vps'
    hostname  = 'vps-control-plane'
    site_id   = 'control-plane'
    zone_id   = 'vps'
    ring      = 0
} $authHeader
if ($device) { Write-Host "  Device created." } else { Write-Host "  Device already exists (skipped)." }

# ── 6. issue device token ─────────────────────────────────────────────────────

Write-Host "[6/6] Issuing a new device token for 'vps-control-plane'..."
$tokenResp = Invoke-Api POST "$FleetApiUrl/api/v1/devices/vps-control-plane/token" $null $authHeader
$deviceToken = $tokenResp.device_token
if (-not $deviceToken) {
    Write-Error "Token issuance failed — no device_token in response."
    exit 1
}
Write-Host "  Token issued (shown once, saved to secrets.env)."

# ── 7. write token to secrets.env ─────────────────────────────────────────────

Update-SecretsEnv $SecretsEnvPath 'VPS_DEVICE_TOKEN' $deviceToken

Write-Host @"

Done!  VPS device enrolled successfully.
  Device ID : vps-control-plane
  Site      : control-plane
  Zone      : vps
  Token     : written to secrets.env as VPS_DEVICE_TOKEN

Next steps:
  cd FleetBits-platform\docker
  docker compose --env-file ..\secrets.env up -d --build vps-device
  docker compose --env-file ..\secrets.env logs vps-device -f --tail 30
"@
