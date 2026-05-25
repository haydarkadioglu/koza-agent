#!/usr/bin/env python3
"""Koza Agent — Entry point."""
import sys

# ── Windows: Enable VT100/ANSI escape sequences in cmd.exe ───────────────────
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Set console title
        kernel32.SetConsoleTitleW("Koza Agent")
        # Enable ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004) on stdout
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(handle, mode)
        # Also enable on stderr
        handle_err = kernel32.GetStdHandle(-12)  # STD_ERROR_HANDLE
        mode_err = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle_err, ctypes.byref(mode_err))
        mode_err.value |= 0x0004
        kernel32.SetConsoleMode(handle_err, mode_err)
    except Exception:
        pass
try:
    import setproctitle
    setproctitle.setproctitle("koza")
except ImportError:
    pass

from cli.setup_constants import PROVIDERS, PROVIDER_MODELS, NEEDS_KEY, _OTHER  # noqa: F401
from cli.daemon import cmd_start, cmd_status, cmd_quit
from cli.setup import cmd_setup, cmd_provider
from cli.commands import cmd_config, cmd_kanban, cmd_uninstall, cmd_telegram, cmd_version, cmd_update, cmd_help, cmd_clean, cmd_sync
from cli.voice_cmd import cmd_voice
from cli.coding_cmd import cmd_coding
from cli.ui import _C, _hr, _print_error

# ── Dispatch table ────────────────────────────────────────────────────────────

_COMMANDS = {
    "start":     cmd_start,
    "setup":     cmd_setup,
    "config":    cmd_config,
    "provider":  cmd_provider,
    "kanban":    cmd_kanban,
    "telegram":  cmd_telegram,
    "status":    cmd_status,
    "quit":      cmd_quit,
    "stop":      cmd_quit,
    "version":   cmd_version,
    "--version": cmd_version,
    "-v":        cmd_version,
    "update":    cmd_update,
    "uninstall": cmd_uninstall,
    "reset":     cmd_clean,
    "sync":      cmd_sync,
    "voice":     cmd_voice,
    "coding":    cmd_coding,
    "help":      cmd_help,
    "--help":    cmd_help,
    "-h":        cmd_help,
}


def main() -> None:
    argv = sys.argv[1:]
    try:
        if not argv:
            cmd_start([])
            return

        command = argv[0].lower()
        rest = argv[1:]

        handler = _COMMANDS.get(command)
        if handler:
            handler(rest)
        else:
            _hr()
            print(_C(f"\n  ✗  Unknown command: {command!r}", "red"))
            print(_C("  Run  koza help  for usage.\n", "grey"))
            _hr()
            sys.exit(1)
    except KeyboardInterrupt:
        print(_C("\n  Interrupted.\n", "grey"))
    except SystemExit:
        raise  # let sys.exit() pass through
    except Exception as exc:
        _print_error(exc, fatal=True)
        sys.exit(1)


if __name__ == "__main__":
    main()