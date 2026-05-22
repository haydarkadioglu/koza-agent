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
    """Stop background services (mini-daemon)."""
    from koza_daemon import get_daemon_port
    port = get_daemon_port()
    if port is None:
        print(_C("\n  No background services running.\n", "grey"))
        return
    try:
        from koza_daemon import PID_FILE, _cleanup
        pid = int(PID_FILE.read_text().strip())
        if sys.platform == "win32":
            os.system(f"taskkill /F /PID {pid} >nul 2>&1")
        else:
            import signal as _sig
            os.kill(pid, _sig.SIGTERM)
        _cleanup()
        print(_C("\n  ✓  Background services stopped.\n", "green"))
    except Exception as e:
        print(_C(f"\n  ✗  Could not stop services: {e}\n", "red"))
