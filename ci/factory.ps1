<#
.SYNOPSIS
    Headless execution of one FleetBits software factory cycle.

.DESCRIPTION
    PowerShell equivalent of ci/factory.sh.
    The spec must exist and carry "Statut : APPROUVEE": a headless cycle never
    writes a spec, the human gate of /factory-run cannot be bypassed.

    JSON output : factory-logs/factory-<timestamp>.json
    Exit code   : that of `claude`.

.EXAMPLE
    pwsh -File ci/factory.ps1 specs/SPEC-my-requirement.md

.EXAMPLE
    pwsh -File ci/factory.ps1 specs/SPEC-my-requirement.md -Yolo
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $Spec,

    [switch] $Yolo
)

$ErrorActionPreference = 'Stop'

$RootDir = Split-Path -Parent $PSScriptRoot

if ([System.IO.Path]::IsPathRooted($Spec)) {
    $SpecAbs = $Spec
} else {
    $SpecAbs = Join-Path $RootDir $Spec
}

if (-not (Test-Path -LiteralPath $SpecAbs -PathType Leaf)) {
    Write-Error "ci/factory.ps1: spec not found: $SpecAbs"
    exit 2
}

if (-not (Select-String -LiteralPath $SpecAbs -Pattern 'Statut : APPROUVEE' -SimpleMatch -Quiet)) {
    Write-Host "ci/factory.ps1: `"$SpecAbs`" does not carry `"Statut : APPROUVEE`"." -ForegroundColor Red
    Write-Host "                A CI cycle requires a spec already approved by the user."
    Write-Host "                Run first, in an interactive session: /factory-run `"<your requirement>`""
    exit 2
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Error "ci/factory.ps1: the `"claude`" command was not found in the PATH."
    exit 127
}

# Tool allowlist: the factory's basic tools, git on the monorepo,
# and the commands actually used by the FleetBits stack
# (python3/venv for api/ and ui/, docker for shellcheck, bats, ansible-lint,
# compose, and bash -n for the -agent and -platform scripts).
$AllowedTools = 'Read,Glob,Grep,Write,Edit,Bash(git *),Bash(python3 *),Bash(pip *),Bash(pytest *),Bash(ruff *),Bash(bandit *),Bash(alembic *),Bash(docker *),Bash(bash -n *),Bash(shellcheck *),Bash(ansible-lint *),Bash(ansible-playbook *)'

$LogDir = Join-Path $RootDir 'factory-logs'
if (-not (Test-Path -LiteralPath $LogDir -PathType Container)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$Stamp   = Get-Date -Format yyyyMMdd-HHmmss
$LogFile = Join-Path $LogDir "factory-$Stamp.json"

$ClaudeArgs = @(
    '-p', "/factory-run '$SpecAbs'",
    '--output-format', 'json',
    '--max-turns', '100'
)

if ($Yolo) {
    $ClaudeArgs += '--dangerously-skip-permissions'
    $ModeLabel = 'YOLO (permissions ignored)'
} else {
    $ClaudeArgs += @('--permission-mode', 'acceptEdits', '--allowedTools', $AllowedTools)
    $ModeLabel = 'acceptEdits + allowlist'
}

Write-Host "ci/factory.ps1: spec      = $SpecAbs"
Write-Host "ci/factory.ps1: log       = $LogFile"
Write-Host "ci/factory.ps1: mode      = $ModeLabel"

Push-Location $RootDir
try {
    & claude @ClaudeArgs | Tee-Object -FilePath $LogFile
    $ExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Host "ci/factory.ps1: claude exit code = $ExitCode"
exit $ExitCode
