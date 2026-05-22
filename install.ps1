# ─────────────────────────────────────────────────────────────────────────────
#  Koza Agent — Windows installer (PowerShell)
#  Usage:
#    irm https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/install.ps1 | iex
#  Or locally:
#    .\install.ps1
# ─────────────────────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"

$RepoUrl    = "https://github.com/haydarkadioglu/koza-agent.git"
$InstallDir = "$env:USERPROFILE\.koza-agent"
$VenvDir    = "$InstallDir\.venv"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Banner {
    Write-Host ""
    Write-Host "   ██╗  ██╗ ██████╗ ███████╗ █████╗  " -ForegroundColor Cyan
    Write-Host "   ██║ ██╔╝██╔═══██╗╚══███╔╝██╔══██╗ " -ForegroundColor Cyan
    Write-Host "   █████╔╝ ██║   ██║  ███╔╝ ███████║ " -ForegroundColor Cyan
    Write-Host "   ██╔═██╗ ██║   ██║ ███╔╝  ██╔══██║ " -ForegroundColor Cyan
    Write-Host "   ██║  ██╗╚██████╔╝███████╗██║  ██║ " -ForegroundColor Cyan
    Write-Host "   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝ " -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Koza Agent Installer" -ForegroundColor White
    Write-Host "  ─────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host ""
}

function Write-Info($msg)    { Write-Host "  ▸  $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "  ✓  $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Host "  ⚠  $msg" -ForegroundColor Yellow }
function Write-Err($msg)     { Write-Host "  ✗  $msg" -ForegroundColor Red; exit 1 }

Write-Banner

# ── 1. Python check ─────────────────────────────────────────────────────────

$PythonCmd = $null
foreach ($cmd in @("python", "python3", "py -3")) {
    try {
        $ver = & ($cmd.Split(" ")[0]) ($cmd.Split(" ") | Select-Object -Skip 1) --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 11) {
                $PythonCmd = $cmd
                break
            }
        }
    } catch { }
}

if (-not $PythonCmd) {
    Write-Err "Python 3.11+ not found. Install from https://python.org/downloads"
}

# Resolve to actual executable
$PythonExe = if ($PythonCmd -eq "py -3") { "py" } else { $PythonCmd.Split(" ")[0] }
$PythonArgs = if ($PythonCmd -eq "py -3") { @("-3") } else { @() }

$pyVer = & $PythonExe @PythonArgs --version 2>&1
Write-Ok "Python found: $pyVer"

# ── 2. Git check ────────────────────────────────────────────────────────────

$gitPath = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitPath) {
    Write-Err "git not found. Install from https://git-scm.com/downloads"
}
Write-Ok "git found: $($gitPath.Source)"

# ── 3. Clone or update ──────────────────────────────────────────────────────

if (Test-Path "$InstallDir\.git") {
    Write-Info "Updating existing install at $InstallDir ..."
    git -C $InstallDir pull --ff-only --quiet
    Write-Ok "Repository updated."
} else {
    Write-Info "Cloning koza-agent into $InstallDir ..."
    git clone --depth=1 $RepoUrl $InstallDir
    Write-Ok "Repository cloned."
}

# ── 4. Virtual environment ───────────────────────────────────────────────────

if (-not (Test-Path $VenvDir)) {
    Write-Info "Creating virtual environment ..."
    & $PythonExe @PythonArgs -m venv $VenvDir
    Write-Ok "Virtualenv created at $VenvDir"
} else {
    Write-Host "      Virtualenv already exists, skipping." -ForegroundColor DarkGray
}

$VenvPython  = "$VenvDir\Scripts\python.exe"
$VenvPip     = "$VenvDir\Scripts\pip.exe"
$VenvKoza    = "$VenvDir\Scripts\koza.exe"
$ScriptsDir  = "$VenvDir\Scripts"

# ── 5. Install package ───────────────────────────────────────────────────────

Write-Info "Installing Koza and dependencies (this may take a minute) ..."
& $VenvPip install --quiet --upgrade pip
& $VenvPip install --quiet -e $InstallDir
Write-Ok "Koza installed."

Write-Info "Installing optional dependencies (Telegram bot) ..."
try {
    & $VenvPip install --quiet "python-telegram-bot>=20.0"
    Write-Ok "python-telegram-bot installed."
} catch {
    Write-Warn "python-telegram-bot install failed (optional)."
}

if (-not (Test-Path $VenvKoza)) {
    Write-Err "pip install did not create '$VenvKoza'. Check pyproject.toml."
}

# ── 6. Add to PATH (user-level, persistent) ─────────────────────────────────

$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
$pathEntries = $currentPath -split ";" | Where-Object { $_.Trim() -ne "" }

if ($pathEntries -notcontains $ScriptsDir) {
    $newPath = ($pathEntries + $ScriptsDir) -join ";"
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")

    # Also update current session so koza works immediately
    $env:PATH = "$ScriptsDir;$env:PATH"

    Write-Ok "Added to user PATH: $ScriptsDir"
    Write-Warn "Open a NEW PowerShell window for 'koza' to be available everywhere."
} else {
    Write-Ok "Already in PATH: $ScriptsDir"
}

# ── Done ─────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ─────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  Koza Agent installed successfully!" -ForegroundColor Green
Write-Host "  ─────────────────────────────────────────" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Run " -NoNewline
Write-Host "koza" -ForegroundColor White -NoNewline
Write-Host " to start."
Write-Host "  Setup wizard will run on first launch." -ForegroundColor DarkGray
Write-Host ""
