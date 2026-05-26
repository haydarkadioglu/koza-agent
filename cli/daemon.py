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

    # ── Multi-host sync (CLI mode) ─────────────────────────────────────────────
    mh = cfg.get("multi_host", {})
    mh_mode = mh.get("mode", "single")
    if mh_mode == "master":
        try:
            from skills.sync.server import start_sync_server
            port  = int(mh.get("sync_port", 7420))
            token = mh.get("sync_token", "")
            hname = mh.get("host_name", "")
            if token:
                ok = start_sync_server(cfg["db_path"], token, port=port, host_name=hname)
                if ok:
                    print(_C(f"  ✓  Sync server listening on port {port}\n", "teal"))
        except Exception:
            pass
    elif mh_mode in ("client", "demo"):
        master = mh.get("master_url", "").strip()
        token  = mh.get("sync_token", "").strip()
        hname  = mh.get("host_name", "")
        if master and token:
            # Register with master
            try:
                from skills.sync.client import register_with_master
                register_with_master(master, token, cfg["db_path"], host_name=hname)
            except Exception:
                pass
            # Startup sync
            if mh.get("sync_on_startup", True):
                try:
                    from skills.sync.client import sync_bidirectional_safe
                    since = float(mh.get("last_sync_at", 0) or 0)
                    msg = sync_bidirectional_safe(master, token, cfg["db_path"], since=since)
                    print(_C(f"  ✓  Startup sync: {msg}\n", "teal"))
                except Exception:
                    pass
            # Periodic sync background thread
            interval = int(mh.get("sync_interval_minutes", 5))
            if interval > 0:
                import threading
                _cli_sync_stop = threading.Event()

                def _periodic_sync_loop():
                    while not _cli_sync_stop.wait(timeout=interval * 60):
                        try:
                            from config import load_config as _lc
                            _cfg = _lc()
                            _mh  = _cfg.get("multi_host", {})
                            _since = float(_mh.get("last_sync_at", 0) or 0)
                            from skills.sync.client import sync_bidirectional_safe as _sbs
                            _sbs(_mh.get("master_url", master), _mh.get("sync_token", token),
                                 _cfg.get("db_path", cfg["db_path"]), since=_since)
                        except Exception:
                            pass

                _t = threading.Thread(target=_periodic_sync_loop, daemon=True, name="koza-cli-sync")
                _t.start()

    # ── Auto-start Telegram bot if token is configured ─────────────────────────
    _tg_token = (
        cfg.get("telegram_token", "").strip()
        or cfg.get("messaging", {}).get("telegram", {}).get("token", "").strip()
    )
    if _tg_token:
        try:
            from bots.telegram import start_bot_thread
            from providers.factory import get_provider as _get_prov

            def _tg_agent_factory(channel="telegram"):
                from core import Agent
                _cfg = cfg
                return Agent(_get_prov(_cfg), db_path=_cfg["db_path"], cfg=_cfg, channel=channel)

            if start_bot_thread(_tg_agent_factory, cfg):
                print(_C("  ✓  Telegram bot started\n", "teal"))
        except Exception as _e:
            print(_C(f"  ✗  Telegram bot failed to start: {_e}\n", "yellow"))

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
