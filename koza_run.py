#!/usr/bin/env python3
"""Koza Agent — Typer entry point."""
import sys

from cli.ui import _C, _print_error


def _configure_console_encoding() -> None:
    import os
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONUTF8", "1")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        if stream is not None:
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


def _set_console_icon() -> None:
    import os
    if os.name == "nt":
        try:
            import ctypes
            from pathlib import Path
            icon_path = Path(__file__).resolve().parent / "icon.ico"
            if icon_path.exists():
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd:
                    # LR_LOADFROMFILE = 0x0010, IMAGE_ICON = 1
                    hicon = ctypes.windll.user32.LoadImageW(0, str(icon_path), 1, 0, 0, 0x0010)
                    if hicon:
                        # ICON_SMALL = 0, ICON_BIG = 1
                        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, hicon)
                        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, hicon)
        except Exception:
            pass


def main() -> None:
    _configure_console_encoding()
    _configure_logging()
    _set_console_icon()
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
