#!/usr/bin/env python3
"""
Koza Agent — Cross-platform installer
  Windows : python install.py
  Linux   : python3 install.py   (or use install.sh)

What it does:
  1. Checks Python 3.11+
  2. Creates a virtualenv at ~/.koza-agent/.venv
  3. Clones / updates the repo
  4. Installs koza + dependencies via pip
  5. Windows: adds Scripts dir to user PATH (registry)
     Linux:   symlinks to ~/.local/bin + adds to .bashrc/.zshrc
"""
import os
import sys
import platform
import subprocess
import shutil
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

REPO_URL    = "https://github.com/haydarkadioglu/koza-agent.git"
INSTALL_DIR = Path.home() / ".koza-agent"
VENV_DIR    = INSTALL_DIR / ".venv"

# ── Console helpers ───────────────────────────────────────────────────────────

IS_WIN = platform.system() == "Windows"

def _c(text, color):
    codes = {"green": "\033[92m", "teal": "\033[96m",
             "yellow": "\033[93m", "red": "\033[91m",
             "grey": "\033[90m", "bold": "\033[1m", "reset": "\033[0m"}
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7)
        except Exception:
            return text
    return f"{codes.get(color,'')}{text}{codes['reset']}"

def info(msg):    print(_c(f"  ▸  {msg}", "teal"))
def ok(msg):      print(_c(f"  ✓  {msg}", "green"))
def warn(msg):    print(_c(f"  ⚠  {msg}", "yellow"))
def err(msg):     print(_c(f"  ✗  {msg}", "red")); sys.exit(1)

def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)

# ── Banner ────────────────────────────────────────────────────────────────────

print(_c("""
   ██╗  ██╗ ██████╗ ███████╗ █████╗
   ██║ ██╔╝██╔═══██╗╚══███╔╝██╔══██╗
   █████╔╝ ██║   ██║  ███╔╝ ███████║
   ██╔═██╗ ██║   ██║ ███╔╝  ██╔══██║
   ██║  ██╗╚██████╔╝███████╗██║  ██║
   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
""", "teal"))
print(_c("  Koza Agent Installer", "bold"))
print(_c("  ─────────────────────────────────────────", "grey"))
print()

# ── 1. Python version check ───────────────────────────────────────────────────

vi = sys.version_info
if vi < (3, 11):
    err(f"Python 3.11+ required. You have {vi.major}.{vi.minor}.")
ok(f"Python {vi.major}.{vi.minor}.{vi.micro}")

# ── 2. git check ──────────────────────────────────────────────────────────────

if not shutil.which("git"):
    err("git not found. Install git first:\n      https://git-scm.com/downloads")
ok(f"git found: {shutil.which('git')}")

# ── 3. Clone or update repo ───────────────────────────────────────────────────

if (INSTALL_DIR / ".git").exists():
    info(f"Updating existing install at {INSTALL_DIR} …")
    run(["git", "-C", str(INSTALL_DIR), "pull", "--ff-only", "--quiet"])
    ok("Repository updated.")
else:
    info(f"Cloning koza-agent into {INSTALL_DIR} …")
    run(["git", "clone", "--depth=1", REPO_URL, str(INSTALL_DIR)])
    ok("Repository cloned.")

# ── 4. Virtualenv ─────────────────────────────────────────────────────────────

if not VENV_DIR.exists():
    info("Creating virtual environment …")
    run([sys.executable, "-m", "venv", str(VENV_DIR)])
    ok(f"Virtualenv created at {VENV_DIR}")
else:
    print(_c(f"      Virtualenv already exists, skipping.", "grey"))

if IS_WIN:
    venv_python = VENV_DIR / "Scripts" / "python.exe"
    venv_pip    = VENV_DIR / "Scripts" / "pip.exe"
    venv_koza   = VENV_DIR / "Scripts" / "koza.exe"
    scripts_dir = VENV_DIR / "Scripts"
else:
    venv_python = VENV_DIR / "bin" / "python"
    venv_pip    = VENV_DIR / "bin" / "pip"
    venv_koza   = VENV_DIR / "bin" / "koza"
    scripts_dir = VENV_DIR / "bin"

# ── 5. Install package + deps ─────────────────────────────────────────────────

info("Installing Koza and dependencies (this may take a minute) …")
run([str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
run([str(venv_python), "-m", "pip", "install", "--quiet", "-e", str(INSTALL_DIR)])
ok("Koza installed.")

info("Installing optional dependencies (Telegram bot) …")
try:
    run([str(venv_python), "-m", "pip", "install", "--quiet", "python-telegram-bot>=21.0"])
    ok("python-telegram-bot installed.")
except subprocess.CalledProcessError:
    warn("python-telegram-bot install failed (optional, Telegram bot won't work).")

if platform.system() == "Linux":
    info("Installing optional dependencies (PySide6 for GUI support) …")
    try:
        run([str(venv_python), "-m", "pip", "install", "--quiet", "PySide6>=6.0.0"])
        ok("PySide6 installed.")
    except subprocess.CalledProcessError:
        warn("PySide6 install failed (optional, GUI mode won't work without it or system GTK).")

if not venv_koza.exists():
    err(f"pip install did not create '{venv_koza}'. Check pyproject.toml [project.scripts].")

# ── 6. PATH setup ─────────────────────────────────────────────────────────────

def _windows_add_path(new_dir: str):
    """Add new_dir to the Windows user PATH via registry (persistent)."""
    import winreg
    key_path = r"Environment"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path,
                        0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            current, _ = winreg.QueryValueEx(key, "PATH")
        except FileNotFoundError:
            current = ""
        paths = [p for p in current.split(";") if p.strip()]
        if new_dir.lower() not in [p.lower() for p in paths]:
            paths.append(new_dir)
            new_val = ";".join(paths)
            winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_val)
            # Broadcast WM_SETTINGCHANGE so Explorer/shell picks it up
            try:
                import ctypes
                HWND_BROADCAST = 0xFFFF
                WM_SETTINGCHANGE = 0x001A
                ctypes.windll.user32.SendMessageTimeoutW(
                    HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None)
            except Exception:
                pass
            return True  # added
        return False  # already there


def _linux_add_path(scripts: str):
    """Add scripts dir to ~/.bashrc and ~/.zshrc if not already present."""
    line = f'\nexport PATH="{scripts}:$PATH"  # koza-agent\n'
    added = []
    for rc in [Path.home() / ".bashrc", Path.home() / ".zshrc", Path.home() / ".profile"]:
        if rc.exists():
            content = rc.read_text()
            if scripts not in content:
                rc.write_text(content + line)
                added.append(str(rc))
    return added


if IS_WIN:
    scripts_str = str(scripts_dir)
    if _windows_add_path(scripts_str):
        ok(f"Added to user PATH: {scripts_str}")
        warn("Open a NEW PowerShell / CMD window for 'koza' to be available.")
    else:
        ok(f"Already in PATH: {scripts_str}")
else:
    # Linux/macOS — also symlink to ~/.local/bin for good measure
    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    link = local_bin / "koza"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(venv_koza)
    ok(f"Symlinked: {link} → {venv_koza}")

    added = _linux_add_path(str(local_bin))
    if added:
        ok(f"Added to PATH in: {', '.join(added)}")
        warn("Run: source ~/.bashrc   (or open a new terminal)")
    else:
        ok("~/.local/bin already in PATH.")

# ── Done ──────────────────────────────────────────────────────────────────────

print()
print(_c("  ─────────────────────────────────────────", "teal"))
print(_c("  Koza Agent installed successfully!", "green"))
print(_c("  ─────────────────────────────────────────", "teal"))
print()
print(f"  Run {_c('koza', 'bold')} to start.")
print(_c("  Setup wizard will run on first launch.", "grey"))
print()
