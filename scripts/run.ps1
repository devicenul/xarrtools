#!/usr/bin/env pwsh
<#
.SYNOPSIS
    xarrtools Cross-Platform PowerShell Auto-Startup Launcher (run.ps1)
#>

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location -LiteralPath $RepoRoot

Write-Host "=================================================="
Write-Host "  xarrtools Auto-Startup Launcher (PowerShell)"
Write-Host "=================================================="

# 1. Resolve environment paths via init.ps1
& "$ScriptDir/init.ps1" -EnvOnly

$VenvPython = $env:XARRTOOLS_RESOLVED_PYTHON
$EnvFile = Join-Path $RepoRoot ".env"
$DbFile = Join-Path $RepoRoot "xarrtools.db"

$NeedsFullInit = (-not (Test-Path -LiteralPath $VenvPython)) -or (-not (Test-Path -LiteralPath $EnvFile)) -or (-not (Test-Path -LiteralPath $DbFile))

if (-not $NeedsFullInit) {
    try {
        & $VenvPython -c "import flask, requests, bs4, rich, dotenv, waitress, defusedxml" 2>$null
        if ($LASTEXITCODE -ne 0) {
            $NeedsFullInit = $true
        }
    } catch {
        $NeedsFullInit = $true
    }
}

if ($NeedsFullInit) {
    & "$ScriptDir/init.ps1"
} else {
    & "$ScriptDir/init.ps1" -SkipDeps
}

# 2. Run the application, forwarding all CLI arguments
Write-Host ""
Write-Host "Booting xarrtools..."
Write-Host "--------------------------------------------------"
& $VenvPython main.py @args
$ExitCode = $LASTEXITCODE
Write-Host "--------------------------------------------------"
Write-Host "Application closed."
exit $ExitCode
