#!/usr/bin/env pwsh
<#
.SYNOPSIS
    xarrtools Cross-Platform PowerShell Compiler Script (build.ps1)
#>

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location -LiteralPath $RepoRoot

Write-Host "=================================================="
Write-Host "  xarrtools Compiler Script (PowerShell)"
Write-Host "=================================================="

# 1. Resolve environment paths via init.ps1 and initialize if needed
& "$ScriptDir/init.ps1" -EnvOnly

$VenvPython = $env:XARRTOOLS_RESOLVED_PYTHON

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[Build] Virtual environment not found. Running init.ps1 first..."
    & "$ScriptDir/init.ps1"
}

# 2. Compile (icon/data-path/workpath selection and PyInstaller install live in build.py)
Write-Host ""
& $VenvPython (Join-Path $ScriptDir 'build.py') @args
if ($LASTEXITCODE -ne 0) {
    exit 1
}
