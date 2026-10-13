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
Set-Location -LiteralPath $ScriptDir

$IsWin = ($env:OS -eq "Windows_NT") -or ([System.Environment]::OSVersion.Platform -eq "Win32NT")
$IsMac = (-not $IsWin) -and ($IsMacOS -or ([System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::OSX)))

Write-Host "=================================================="
Write-Host "  xarrtools Compiler Script (PowerShell)"
Write-Host "=================================================="

# 1. Resolve environment paths via init.ps1 and initialize if needed
& "$ScriptDir/init.ps1" -EnvOnly

$VenvPython = $env:XARRTOOLS_RESOLVED_PYTHON
$VenvPip = $env:XARRTOOLS_RESOLVED_PIP
$VenvPyInstaller = $env:XARRTOOLS_RESOLVED_PYINSTALLER

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[Build] Virtual environment not found. Running init.ps1 first..."
    & "$ScriptDir/init.ps1"
}

Write-Host "Ensuring PyInstaller is installed in the virtual environment..."
& $VenvPip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    Write-Error "[Error] Failed to install PyInstaller."
    exit 1
}

# 2. Configure platform-specific icon and data separator
if ($IsWin) {
    $IconFile = "web/templates/favicon.ico"
    $DataArg = "web/templates;web/templates"
    $BinaryOut = "dist\xarrtools.exe"
} elseif ($IsMac) {
    $IconFile = "web/templates/favicon.icns"
    $DataArg = "web/templates:web/templates"
    $BinaryOut = "dist/xarrtools"
} else {
    $IconFile = "web/templates/favicon.png"
    $DataArg = "web/templates:web/templates"
    $BinaryOut = "dist/xarrtools"
}

$PyInstallerArgs = @(
    "--onefile",
    "--name", "xarrtools",
    "--icon=$IconFile",
    "--add-data", $DataArg
)

if ($env:XARRTOOLS_PROJECT_CACHE_DIR) {
    $WorkPath = Join-Path $env:XARRTOOLS_PROJECT_CACHE_DIR "pyinstaller-build"
    $PyInstallerArgs += @("--workpath", $WorkPath)
}

$PyInstallerArgs += "main.py"

Write-Host ""
Write-Host "Compiling xarrtools to a single executable..."
& $VenvPyInstaller @PyInstallerArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[Success] Compilation complete!"
    Write-Host "Binary available at: $BinaryOut"
} else {
    Write-Error "[Error] Compilation failed."
    exit 1
}
