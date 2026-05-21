#!/usr/bin/env python3
"""Koza Agent — Entry point."""
import sys

from cli.setup import PROVIDERS, PROVIDER_MODELS, NEEDS_KEY, _OTHER  # noqa: F401
from cli.daemon import cmd_start, cmd_status, cmd_quit
from cli.setup import cmd_setup, cmd_provider
from cli.commands import cmd_config, cmd_kanban, cmd_uninstall, cmd_telegram, cmd_version, cmd_update, cmd_help, cmd_clean, cmd_sync
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
    "clean":     cmd_clean,
    "sync":      cmd_sync,
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