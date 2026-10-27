#!/usr/bin/env pwsh
<#
.SYNOPSIS
    xarrtools Cross-Platform PowerShell Initialization Script (init.ps1)
.DESCRIPTION
    Works across Windows PowerShell 5.1 and PowerShell Core (pwsh) on Windows,
    macOS, Linux, and Android Linux VMs. Sets up the Python virtual environment
    (with automatic $HOME/.cache ext4 fallback on shared FUSE/virtiofs mounts),
    installs runtime and test/development dependencies, creates .env from
    .env.example, and initializes the local SQLite database schema.
#>

param(
    [switch]$EnvOnly,
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location -LiteralPath $RepoRoot

$IsWin = ($env:OS -eq "Windows_NT") -or ([System.Environment]::OSVersion.Platform -eq "Win32NT")

# 1. Locate Python 3 interpreter
$PythonCmd = $null
$PythonArgs = @()

foreach ($candidate in @("python3", "python")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            & $cmd.Source -c "import sys; sys.exit(0 if sys.version_info.major >= 3 else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                $PythonCmd = $cmd.Source
                break
            }
        } catch {}
    }
}

if (-not $PythonCmd -and $IsWin) {
    $pyCmd = Get-Command "py" -ErrorAction SilentlyContinue
    if ($pyCmd) {
        try {
            & $pyCmd.Source -3 -c "import sys; sys.exit(0 if sys.version_info.major >= 3 else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                $PythonCmd = $pyCmd.Source
                $PythonArgs = @("-3")
            }
        } catch {}
    }
}

if (-not $PythonCmd) {
    Write-Error "[Error] Python 3 is not installed or not in your PATH. Please install Python 3 and try again."
    exit 1
}

# 2. Clean up broken local .venv if present
$LocalVenv = Join-Path $RepoRoot ".venv"
$LocalWinPy = Join-Path $LocalVenv "Scripts/python.exe"
$LocalUnixPy = Join-Path $LocalVenv "bin/python"

if ((Test-Path -LiteralPath $LocalVenv) -and (-not (Test-Path -LiteralPath $LocalWinPy)) -and (-not (Test-Path -LiteralPath $LocalUnixPy))) {
    if (-not $EnvOnly) {
        Write-Host "[Init] Removing incomplete local .venv directory..."
    }
    Remove-Item -LiteralPath $LocalVenv -Recurse -Force
}

# 3. Resolve Virtual Environment Path (with ext4 cache fallback on Unix shared mounts)
$ProjectCacheDir = ""
$UseExt4Cache = $false

if (-not $IsWin) {
    $ResolvedPath = (Resolve-Path -LiteralPath $RepoRoot).Path
    if ($ResolvedPath -like "/storage/emulated/*" -or $ResolvedPath -like "/mnt/shared/*") {
        $UseExt4Cache = $true
    }
    if (-not $UseExt4Cache) {
        $TestLink = Join-Path $RepoRoot ".venv_symlink_probe_$PID"
        try {
            New-Item -ItemType SymbolicLink -Path $TestLink -Target $RepoRoot -ErrorAction Stop | Out-Null
            Remove-Item -LiteralPath $TestLink -Force -ErrorAction SilentlyContinue
        } catch {
            $UseExt4Cache = $true
        }
    }
}

if ($env:XARRTOOLS_VENV_DIR) {
    $VenvDir = $env:XARRTOOLS_VENV_DIR
} elseif ($UseExt4Cache) {
    $ResolvedPath = (Resolve-Path -LiteralPath $RepoRoot).Path
    if ($ResolvedPath.StartsWith("/storage/emulated/10")) {
        $ResolvedPath = "/mnt/shared" + $ResolvedPath.Substring(20)
    }
    $Sha1 = [System.Security.Cryptography.SHA1]::Create()
    $Bytes = [System.Text.Encoding]::UTF8.GetBytes($ResolvedPath + "`n")
    $HashBytes = $Sha1.ComputeHash($Bytes)
    $PathHash = ([System.BitConverter]::ToString($HashBytes).Replace("-", "").ToLower()).Substring(0, 8)
    $ProjectName = Split-Path -Leaf $RepoRoot
    $HomeDir = if ($env:HOME) { $env:HOME } else { [Environment]::GetFolderPath("UserProfile") }
    $ProjectCacheDir = Join-Path $HomeDir ".cache/projects/$ProjectName-$PathHash"
    $VenvDir = Join-Path $ProjectCacheDir "venv"
    $env:PYTHONPYCACHEPREFIX = Join-Path $ProjectCacheDir "pycache"
    $env:PIP_CACHE_DIR = Join-Path $ProjectCacheDir "pip"
    if (-not $env:COVERAGE_FILE) {
        $env:COVERAGE_FILE = Join-Path $ProjectCacheDir ".coverage"
    }
} else {
    $VenvDir = $LocalVenv
}

if ($IsWin) {
    $VenvPython = Join-Path $VenvDir "Scripts/python.exe"
    $VenvPip = Join-Path $VenvDir "Scripts/pip.exe"
    $VenvPyInstaller = Join-Path $VenvDir "Scripts/pyinstaller.exe"
} else {
    $VenvPython = Join-Path $VenvDir "bin/python"
    $VenvPip = Join-Path $VenvDir "bin/pip"
    $VenvPyInstaller = Join-Path $VenvDir "bin/pyinstaller"
}

$env:XARRTOOLS_PROJECT_CACHE_DIR = $ProjectCacheDir
$env:XARRTOOLS_RESOLVED_VENV = $VenvDir
$env:XARRTOOLS_RESOLVED_PYTHON = $VenvPython
$env:XARRTOOLS_RESOLVED_PIP = $VenvPip
$env:XARRTOOLS_RESOLVED_PYINSTALLER = $VenvPyInstaller

if ($EnvOnly) {
    return
}

Write-Host "=================================================="
Write-Host "  xarrtools Project Initialization (PowerShell)"
Write-Host "=================================================="
Write-Host "[Init] Project directory : $RepoRoot"
Write-Host "[Init] Virtualenv path   : $VenvDir"

if ($ProjectCacheDir) {
    New-Item -ItemType Directory -Force -Path $ProjectCacheDir, $env:PYTHONPYCACHEPREFIX, $env:PIP_CACHE_DIR | Out-Null
}

# 4. Create virtual environment if missing
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[Init] Creating Python virtual environment at $VenvDir..."
    & $PythonCmd @PythonArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Init] Retrying venv creation with --copies..."
        if (Test-Path -LiteralPath $VenvDir) {
            Remove-Item -LiteralPath $VenvDir -Recurse -Force
        }
        & $PythonCmd @PythonArgs -m venv --copies $VenvDir
        if ($LASTEXITCODE -ne 0) {
            Write-Error "[Error] Failed to create Python virtual environment."
            exit 1
        }
    }
}

# 5. Install runtime and test/development dependencies
if (-not $SkipDeps) {
    Write-Host "[Init] Installing runtime dependencies from requirements.txt..."
    & $VenvPip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[Error] Failed to install runtime requirements."
        exit 1
    }

    Write-Host "[Init] Installing test and development dependencies (pytest, pytest-cov, pyinstaller)..."
    & $VenvPip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[Error] Failed to install test/development dependencies."
        exit 1
    }
}

# 5b. Install frontend build dependencies
$PackageJson = Join-Path $RepoRoot "package.json"
if ((-not $SkipDeps) -and (Test-Path -LiteralPath $PackageJson)) {
    $NodeCmd = Get-Command "node" -ErrorAction SilentlyContinue
    $NpmCmd = Get-Command "npm" -ErrorAction SilentlyContinue
    if ((-not $NodeCmd) -or (-not $NpmCmd)) {
        Write-Error "[Error] Node.js (npm) is required to build the frontend: install it from https://nodejs.org"
        exit 1
    }
    Write-Host "[Init] Installing frontend dependencies from package.json..."
    if ($ProjectCacheDir) {
        $env:npm_config_cache = Join-Path $ProjectCacheDir "npm"
    }
    & npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[Error] Failed to install frontend dependencies."
        exit 1
    }
    Write-Host "[Init] Compiling the TypeScript frontend (src/xarrtools/web/static/dist)..."
    & npm run build --silent
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[Error] Frontend build failed."
        exit 1
    }
}

# 6. Generate .env configuration from template if missing
$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    if (Test-Path -LiteralPath $EnvExample) {
        Write-Host "[Init] Creating .env configuration file from .env.example..."
        Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
        Write-Host "[Note] Default .env created. You can configure Radarr/Sonarr credentials in .env or via the Web UI Settings."
    } else {
        Write-Host "[Warning] .env.example not found; skipping .env creation."
    }
} else {
    Write-Host "[Init] Existing .env configuration found."
}

# 7. Initialize SQLite database schema and prune expired cache
Write-Host "[Init] Initializing SQLite database schema (xarrtools.db)..."
$env:PYTHONPATH = (Join-Path $RepoRoot "src") + $(if ($env:PYTHONPATH) { [IO.Path]::PathSeparator + $env:PYTHONPATH } else { "" })
& $VenvPython -c "from xarrtools.core.db import init_db, clean_expired_cache; init_db(); clean_expired_cache()"
if ($LASTEXITCODE -ne 0) {
    Write-Error "[Error] Failed to initialize SQLite database schema."
    exit 1
}

Write-Host "=================================================="
Write-Host "  [Success] xarrtools initialization complete!"
Write-Host "=================================================="
