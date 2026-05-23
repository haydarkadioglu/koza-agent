"""Koza CLI commands — start, status, quit."""
import sys
import os

from cli.ui import (
    _C, _hr, _print_banner, _print_inline_help, _print_error,
    _spinner_start, _spinner_stop, _select_menu, _render_md,
)
from cli.chat import _plain_cli


def cmd_start(args: list) -> None:
    """Start Koza — create agent in-process, start background services, run CLI."""
    from config import load_config, config_exists
    if not config_exists():
        print(_C("  No config found. Running setup first…\n", "grey"))
        from cli.setup import cmd_setup
        cmd_setup([])

    cfg = load_config()

    # If no provider configured, run setup
    if not cfg.get("provider"):
        print(_C("  No provider configured. Running setup…\n", "grey"))
        from cli.setup import cmd_setup
        cmd_setup([])
        cfg = load_config()
        if not cfg.get("provider"):
            print(_C("  ✗  No provider set. Cannot start.\n", "red"))
            return

    try:
        from providers.factory import get_provider
        from core import Agent
        agent = Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg)
    except Exception as exc:
        _print_error(exc, fatal=True)
        return

    _plain_cli(agent, cfg)


def cmd_status(args: list) -> None:
    """Show whether background services are running."""
    from koza_daemon import get_daemon_port, PID_FILE
    port = get_daemon_port()
    if port is not None:
        pid = PID_FILE.read_text().strip()
        mode = "services-only" if port == 0 else f"port {port}"
        print(_C(f"\n  ✓  Koza background services running  (PID {pid}, {mode})\n", "green"))
    else:
        print(_C("\n  ✗  No background services running.\n", "grey"))


def cmd_quit(args: list) -> None:
    """Stop ALL Koza background services and processes (cross-platform)."""
    import time
    import subprocess
    from pathlib import Path
    from koza_daemon import get_daemon_port, PID_FILE, _cleanup

    killed = []
    current_pid = os.getpid()

    # 1. Kill the registered daemon process (if PID file exists)
    port = get_daemon_port()
    if port is not None:
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid != current_pid:
                _kill_pid(pid)
                killed.append(f"daemon (PID {pid})")
        except Exception:
            pass
        _cleanup()

    # 2. Find and kill ALL koza-related processes using psutil (cross-platform)
    try:
        import psutil
        koza_keywords = ["koza_daemon", "koza_run", "services-only",
                         "telegram", ".koza-agent"]
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = proc.info["pid"]
                if pid == current_pid:
                    continue
                name = (proc.info["name"] or "").lower()
                cmdline = " ".join(proc.info["cmdline"] or []).lower()

                # Only target python processes related to koza
                if "python" not in name and "koza" not in name:
                    continue
                if not any(kw in cmdline for kw in koza_keywords):
                    continue

                proc.kill()
                killed.append(f"{proc.info['name']} (PID {pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except ImportError:
        # psutil not available — fall back to platform-specific methods
        _quit_fallback(current_pid, killed)

    # 3. Clean up PID/port files
    _cleanup()

    # Also remove stale lock files
    koza_dir = Path.home() / ".Koza"
    for lock_file in koza_dir.glob("*.lock"):
        try:
            lock_file.unlink()
        except Exception:
            pass

    # Report
    if killed:
        # Deduplicate
        killed = list(dict.fromkeys(killed))
        print(_C("\n  ✓  Stopped:\n", "green"))
        for k in killed:
            print(f"    {_C(k, 'grey')}")
        print()
    else:
        print(_C("\n  No Koza services were running.\n", "grey"))


def _kill_pid(pid: int) -> None:
    """Kill a process by PID (cross-platform)."""
    if sys.platform == "win32":
        os.system(f"taskkill /F /PID {pid} >nul 2>&1")
    else:
        import signal as _sig
        try:
            os.kill(pid, _sig.SIGTERM)
        except ProcessLookupError:
            pass


def _quit_fallback(current_pid: int, killed: list) -> None:
    """Fallback process killing when psutil is not available."""
    import subprocess

    if sys.platform == "win32":
        # Windows: use tasklist + findstr
        try:
            result = subprocess.run(
                'tasklist /FO CSV /FI "IMAGENAME eq python.exe"',
                capture_output=True, text=True, shell=True, timeout=5
            )
            for line in result.stdout.splitlines()[1:]:  # skip header
                parts = line.strip('"').split('","')
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1].strip('"'))
                        if pid == current_pid:
                            continue
                        # Check if this python process is koza-related
                        cmd_result = subprocess.run(
                            f'wmic process where "ProcessId={pid}" get CommandLine',
                            capture_output=True, text=True, shell=True, timeout=3
                        )
                        if "koza" in cmd_result.stdout.lower():
                            os.system(f"taskkill /F /PID {pid} >nul 2>&1")
                            killed.append(f"python.exe (PID {pid})")
                    except (ValueError, subprocess.TimeoutExpired):
                        pass
        except Exception:
            pass
    else:
        # Linux/macOS: use pgrep + pkill
        try:
            patterns = ["koza_daemon", "koza.*services-only", "koza_run.*telegram"]
            for pattern in patterns:
                result = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.strip().splitlines():
                    try:
                        pid = int(line.strip())
                        if pid != current_pid:
                            import signal as _sig
                            os.kill(pid, _sig.SIGTERM)
                            killed.append(f"koza process (PID {pid})")
                    except (ValueError, ProcessLookupError):
                        pass
        except Exception:
            pass
