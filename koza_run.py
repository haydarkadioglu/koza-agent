#!/usr/bin/env python3
"""Koza Agent — Typer entry point."""
import sys

from cli.ui import _C, _print_error


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> None:
    _configure_console_encoding()
    try:
        from cli.typer_app import app
        app(prog_name="koza")
    except KeyboardInterrupt:
        print(_C("\n  Interrupted.\n", "grey"))
    except SystemExit:
        raise
    except Exception as exc:
        _print_error(exc, fatal=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
