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


def _configure_logging() -> None:
    try:
        import logging
        from logging.handlers import RotatingFileHandler
        from pathlib import Path
        
        log_dir = Path.home() / ".Koza"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "koza.log"
        
        root_logger = logging.getLogger()
        if not root_logger.handlers:
            handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            handler.setFormatter(formatter)
            handler.setLevel(logging.WARNING)
            
            root_logger.setLevel(logging.WARNING)
            root_logger.addHandler(handler)
            
            # Suppress noisy library loggers
            for logger_name in ["httpx", "httpcore", "urllib3", "asyncio", "openai", "google"]:
                logging.getLogger(logger_name).setLevel(logging.WARNING)
    except Exception:
        pass


def main() -> None:
    _configure_console_encoding()
    _configure_logging()
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
