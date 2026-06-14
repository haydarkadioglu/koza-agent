# ─────────────────────────────────────────────────────────────────────────────
#  Koza Agent — Windows installer (PowerShell)
#  Usage:
#    powershell -c "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; irm https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/install.ps1 | iex"
#  Or locally:
#    .\install.ps1
# ─────────────────────────────────────────────────────────────────────────────

# Force TLS 1.2 — Windows PowerShell 5.1 defaults to TLS 1.0 which GitHub rejects
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ErrorActionPreference = "Stop"

function Wait-KeyPress {
    if ($Host.Name -eq "ConsoleHost") {
        try {
            Write-Host "  Press Enter to close ..." -ForegroundColor DarkGray
            $null = Read-Host
        } catch { Start-Sleep -Seconds 5 }
    } else {
        Start-Sleep -Seconds 5
    }
}

# Prevent window from closing on error when run via irm | iex
trap {
    Write-Host ""
    Write-Host "  ✗  Installation failed: $_" -ForegroundColor Red
    Write-Host ""
    Wait-KeyPress
    exit 1
}

$RepoUrl    = "https://github.com/haydarkadioglu/koza-agent.git"
$ZipUrl     = "https://github.com/haydarkadioglu/koza-agent/archive/refs/heads/main.zip"
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
function Write-Err($msg)     { Write-Host "  ✗  $msg" -ForegroundColor Red; Wait-KeyPress; exit 1 }

Write-Banner

# ── 1. Execution Policy check ────────────────────────────────────────────────

$currentPolicy = Get-ExecutionPolicy -Scope Process
if ($currentPolicy -eq "Restricted") {
    Write-Info "Setting execution policy for this session ..."
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
    Write-Ok "Execution policy set to Bypass (this session only)."
}

# ── 2. Python check ─────────────────────────────────────────────────────────

$PythonCmd = $null
$BestFoundCmd = $null
$BestFoundVer = ""

foreach ($cmd in @("python", "python3", "py -3")) {
    try {
        $ver = & ($cmd.Split(" ")[0]) ($cmd.Split(" ") | Select-Object -Skip 1) --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            
            if ($null -eq $BestFoundCmd) {
                $BestFoundCmd = $cmd
                $BestFoundVer = $ver
            }

            if ($major -ge 3 -and $minor -ge 11) {
                $PythonCmd = $cmd
                break
            }
        }
    } catch { }
}

if (-not $PythonCmd) {
    if ($BestFoundCmd) {
        Write-Warn "Python 3.11+ not found. Found older version: $BestFoundVer"
    } else {
        Write-Warn "Python is not installed or not found in PATH."
    }
    
    $installNow = ""
    if ($Host.Name -eq "ConsoleHost") {
        try {
            $installNow = Read-Host "  ▸  Do you want to automatically download and install Python 3.12? (Y/n)"
        } catch {}
    }

    if ($installNow -match "^[Yy]?$") {
        Write-Info "Downloading Python 3.12 installer..."
        $pyUrl = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
        $pyInstaller = "$env:TEMP\python-3.12.4-amd64.exe"
        Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing
        
        Write-Info "Installing Python 3.12 silently (this may take a minute)..."
        $installArgs = "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0"
        $process = Start-Process -FilePath $pyInstaller -ArgumentList $installArgs -Wait -PassThru
        
        if ($process.ExitCode -eq 0) {
            Write-Ok "Python 3.12 installed successfully."
            
            $localPythonPath = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
            if (Test-Path -LiteralPath $localPythonPath) {
                $PythonCmd = $localPythonPath
            } else {
                $PythonCmd = "python"
            }
        } else {
            Write-Warn "Python installation failed with exit code $($process.ExitCode)."
        }
    }

    if (-not $PythonCmd) {
        if ($BestFoundCmd) {
            Write-Info "Proceeding with older version: $BestFoundVer as requested."
            $PythonCmd = $BestFoundCmd
        } else {
            Write-Err "Python is required to install Koza Agent. Cannot proceed."
        }
    }
}

# Resolve to actual executable
if ($PythonCmd -eq "py -3") {
    $PythonExe = "py"
    $PythonArgs = @("-3")
} elseif (Test-Path -LiteralPath $PythonCmd -ErrorAction SilentlyContinue) {
    $PythonExe = $PythonCmd
    $PythonArgs = @()
} else {
    $PythonExe = $PythonCmd.Split(" ")[0]
    $PythonArgs = @()
}

try {
    $pyVer = & $PythonExe @PythonArgs --version 2>&1
    Write-Ok "Using Python: $pyVer"
} catch {
    Write-Err "Failed to execute Python ($PythonExe)."
}

# ── 3. Git check (optional) ──────────────────────────────────────────────────

$HasGit = $false
$gitPath = Get-Command git -ErrorAction SilentlyContinue
if ($gitPath) {
    $HasGit = $true
    Write-Ok "git found: $($gitPath.Source)"
} else {
    Write-Warn "git not found — will use ZIP download instead."
}

# ── 4. Clone, update, or download ZIP ───────────────────────────────────────

if ($HasGit) {
    if (Test-Path "$InstallDir\.git") {
        Write-Info "Updating existing install at $InstallDir ..."
        git -C $InstallDir pull --ff-only --quiet
        Write-Ok "Repository updated."
    } else {
        if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
        Write-Info "Cloning koza-agent into $InstallDir ..."
        git clone --depth=1 $RepoUrl $InstallDir
        Write-Ok "Repository cloned."
    }
} else {
    Write-Info "Downloading koza-agent as ZIP ..."
    $TempZip = "$env:TEMP\koza-agent.zip"
    $TempExtract = "$env:TEMP\koza-agent-extract"
    Invoke-WebRequest -Uri $ZipUrl -OutFile $TempZip -UseBasicParsing
    if (Test-Path $TempExtract) { Remove-Item -Recurse -Force $TempExtract }
    Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force
    # GitHub ZIP extracts to koza-agent-main/
    $ExtractedDir = Get-ChildItem $TempExtract | Select-Object -First 1
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    Move-Item -Path $ExtractedDir.FullName -Destination $InstallDir
    Remove-Item -Force $TempZip
    Remove-Item -Recurse -Force $TempExtract -ErrorAction SilentlyContinue
    Write-Ok "Downloaded and extracted to $InstallDir"
}

# ── 5. Virtual environment ───────────────────────────────────────────────────

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

# ── 6. Install package ───────────────────────────────────────────────────────

Write-Info "Installing Koza and dependencies (this may take a minute) ..."
& $VenvPip install --quiet --upgrade pip
& $VenvPip install --quiet -e $InstallDir
Write-Ok "Koza installed."

Write-Info "Installing optional dependencies (Telegram bot) ..."
try {
    & $VenvPip install --quiet "python-telegram-bot>=21.0"
    Write-Ok "python-telegram-bot installed."
} catch {
    Write-Warn "python-telegram-bot install failed (optional)."
}

if (-not (Test-Path $VenvKoza)) {
    Write-Err "pip install did not create '$VenvKoza'. Check pyproject.toml."
}

# ── 7. Add to PATH (user-level, persistent) ─────────────────────────────────

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

# Verify koza is accessible in current session
$env:PATH = "$ScriptsDir;$env:PATH"
$kozaCheck = Get-Command koza -ErrorAction SilentlyContinue
if ($kozaCheck) {
    Write-Ok "koza command is ready: $($kozaCheck.Source)"
    Write-Host ""
    Write-Host "  Run " -NoNewline
    Write-Host "koza" -ForegroundColor White -NoNewline
    Write-Host " to start."
} else {
    Write-Warn "koza is installed but not found in this session."
    Write-Host ""
    Write-Host "  Run directly:" -ForegroundColor White
    Write-Host "    $VenvKoza" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Or open a NEW PowerShell/terminal window and type:" -ForegroundColor DarkGray
    Write-Host "    koza" -ForegroundColor Yellow
}
Write-Host "  Setup wizard will run on first launch." -ForegroundColor DarkGray
Write-Host ""

# Keep window open when run via irm | iex so user can see the result
Wait-KeyPress
