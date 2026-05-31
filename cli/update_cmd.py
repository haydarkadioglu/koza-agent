"""CLI commands: koza version, koza update — version check and self-update."""
import urllib.request
import json

from cli.ui import _C, _hr, _get_version


def _check_latest_version() -> tuple[str, str]:
    """Fetch latest version from GitHub.

    Strategy:
    1. Try GitHub Releases API (tag_name)
    2. Fall back to reading pyproject.toml from main branch
    Returns (latest_version_str, current_version_str).
    """
    current = _get_version()

    def _fetch(url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "koza-agent"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode()

    # 1 — GitHub Releases API
    try:
        data = json.loads(_fetch(
            "https://api.github.com/repos/haydarkadioglu/koza-agent/releases/latest"
        ))
        tag = data.get("tag_name", "").lstrip("v")
        if tag:
            return tag, current
    except Exception:
        pass

    # 2 — Raw pyproject.toml on main branch
    try:
        import re
        toml = _fetch(
            "https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/pyproject.toml"
        )
        m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
        if m:
            return m.group(1), current
    except Exception:
        pass

    return "", current



def cmd_version(args: list) -> None:
    """Print Koza version and check for updates."""
    from packaging.version import Version
    ver = _get_version()
    _hr()
    print(_C(f"\n  Koza  ", "bold", "yellow") + _C(f"v{ver}", "cyan"))
    latest, current = _check_latest_version()
    if latest:
        try:
            if Version(latest) > Version(current):
                print(_C(f"\n  🆕  Update available:  v{latest}  →  run  koza update", "yellow"))
            else:
                print(_C("  ✓  You are on the latest version.", "green"))
        except Exception:
            pass
    print()
    _hr()


def cmd_update(args: list) -> None:
    """Self-update Koza by pulling the latest code from GitHub and reinstalling."""
    import subprocess, shutil
    from pathlib import Path

    _hr()
    print(_C("\n  🔄  Koza Self-Update\n", "bold", "cyan"))

    latest, current = _check_latest_version()
    if latest:
        try:
            from packaging.version import Version
            if Version(latest) == Version(current):
                print(_C(f"  ✓  Already on the latest version (v{current}).\n", "green"))
                _hr()
                return
            elif Version(latest) > Version(current):
                print(_C(f"  Updating  v{current}  →  v{latest}…\n", "grey"))
            else:
                print(_C(f"  ℹ  Local version (v{current}) is ahead of release (v{latest}) — pulling latest code…\n", "yellow"))
        except Exception:
            pass
    else:
        print(_C("  ℹ  Could not fetch latest release info — updating from main branch…\n", "yellow"))

    repo_root = Path(__file__).resolve().parent.parent
    git = shutil.which("git")
    pip = shutil.which("pip") or shutil.which("pip3")

    if not git:
        print(_C("  ✗  git not found. Cannot self-update.\n", "red"))
        _hr()
        return

    try:
        result = subprocess.run(
            [git, "pull", "--ff-only"],
            cwd=repo_root, capture_output=True, text=True
        )
        if result.returncode == 0:
            print(_C("  ✓  Code updated.\n", "green"))
            for line in result.stdout.strip().splitlines():
                print(f"    {_C(line, 'grey')}")
            print()
        else:
            print(_C(f"  ✗  git pull failed:\n    {result.stderr.strip()}\n", "red"))
            _hr()
            return
    except Exception as e:
        print(_C(f"  ✗  git pull error: {e}\n", "red"))
        _hr()
        return

    import os, sys

    # Always use the same python's pip (handles venv on Linux, avoids system pip)
    pip_cmd = [sys.executable, "-m", "pip"]
    try:
        result = subprocess.run(
            pip_cmd + ["install", "-e", ".", "--quiet"],
            cwd=repo_root, capture_output=True, text=True
        )
        if result.returncode == 0:
            print(_C("  ✓  Package reinstalled.\n", "green"))
        else:
            stderr = result.stderr.strip()
            if "WinError 32" in stderr or "being used by another process" in stderr:
                print(_C("  ⚠  Skipped package reinstall (koza.exe in use — will apply on next start).\n", "yellow"))
            elif "externally-managed-environment" in stderr:
                # Try with --break-system-packages as last resort
                r2 = subprocess.run(
                    pip_cmd + ["install", "-e", ".", "--quiet", "--break-system-packages"],
                    cwd=repo_root, capture_output=True, text=True
                )
                if r2.returncode == 0:
                    print(_C("  ✓  Package reinstalled.\n", "green"))
                else:
                    print(_C("  ⚠  pip install skipped (git pull already updated the code).\n", "yellow"))
            else:
                print(_C(f"  ⚠  pip install warning:\n    {stderr[:200]}\n", "yellow"))
    except Exception as e:
        print(_C(f"  ⚠  pip reinstall skipped: {e}\n", "yellow"))

    new_ver = _get_version()
    print(_C(f"  ✅  Koza is now v{new_ver}. Restarting…\n", "green"))
    _hr()

    # Windows: os.execv doesn't work reliably (locked exe, no shebang support).
    # Spawn a fresh process and exit current one instead.
    if sys.platform == "win32":
        import time
        try:
            koza_exe = Path(sys.executable).parent / "koza.exe"
            if not koza_exe.exists():
                koza_exe = Path(sys.executable).parent / "Scripts" / "koza.exe"

            if koza_exe.exists():
                # Restart koza without 'update' arg to avoid re-triggering update
                subprocess.Popen([str(koza_exe)],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen([sys.executable, "-m", "koza_run"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            print(_C("  ℹ  Please restart koza manually.\n", "grey"))
        time.sleep(0.5)
        os._exit(0)

    # Unix: exec-replace, but restart as plain 'koza' without 'update' arg
    koza_bin = shutil.which("koza")
    if koza_bin:
        os.execv(koza_bin, [koza_bin])
    else:
        os.execv(sys.executable, [sys.executable, str(repo_root / "koza_run.py")])
