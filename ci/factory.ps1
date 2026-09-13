<#
.SYNOPSIS
    Exécution headless d'un cycle de l'usine logicielle FleetBits.

.DESCRIPTION
    Équivalent PowerShell de ci/factory.sh.
    La spec doit exister et porter « Statut : APPROUVEE » : un cycle headless ne
    rédige jamais de spec, la gate humaine de /factory-run n'est pas contournable.

    Sortie JSON : factory-logs/factory-<horodatage>.json
    Exit code   : celui de `claude`.

.EXAMPLE
    pwsh -File ci/factory.ps1 specs/SPEC-mon-besoin.md

.EXAMPLE
    pwsh -File ci/factory.ps1 specs/SPEC-mon-besoin.md -Yolo
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
    Write-Error "ci/factory.ps1 : spec introuvable : $SpecAbs"
    exit 2
}

if (-not (Select-String -LiteralPath $SpecAbs -Pattern 'Statut : APPROUVEE' -SimpleMatch -Quiet)) {
    Write-Host "ci/factory.ps1 : « $SpecAbs » ne porte pas « Statut : APPROUVEE »." -ForegroundColor Red
    Write-Host "                 Un cycle CI exige une spec deja approuvee par l'utilisateur."
    Write-Host "                 Lancer d'abord, en session interactive : /factory-run `"<votre besoin>`""
    exit 2
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Error "ci/factory.ps1 : la commande « claude » est introuvable dans le PATH."
    exit 127
}

# Liste blanche d'outils : outils de base de l'usine, git sur les quatre dépôts,
# et les commandes réellement utilisées par la stack FleetBits
# (python3/venv pour -api et -ui, docker pour shellcheck, bats, ansible-lint,
# compose, et bash -n pour les scripts de -agent et -platform).
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
    $ModeLabel = 'YOLO (permissions ignorees)'
} else {
    $ClaudeArgs += @('--permission-mode', 'acceptEdits', '--allowedTools', $AllowedTools)
    $ModeLabel = 'acceptEdits + liste blanche'
}

Write-Host "ci/factory.ps1 : spec      = $SpecAbs"
Write-Host "ci/factory.ps1 : journal   = $LogFile"
Write-Host "ci/factory.ps1 : mode      = $ModeLabel"

Push-Location $RootDir
try {
    & claude @ClaudeArgs | Tee-Object -FilePath $LogFile
    $ExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Host "ci/factory.ps1 : exit code claude = $ExitCode"
exit $ExitCode
