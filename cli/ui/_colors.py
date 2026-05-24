"""ANSI colour helpers."""
import sys
import os

_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "italic": "\033[3m", "underline": "\033[4m",
    "teal": "\033[36m",  "cyan": "\033[96m",
    "green": "\033[92m", "red": "\033[91m", "blue": "\033[94m",
    "white": "\033[97m", "grey": "\033[90m", "magenta": "\033[95m",
    "yellow": "\033[33m", "gold": "\033[38;5;178m",
    "orange": "\033[38;5;208m",
}


def _C(text: str, *styles: str) -> str:
    try:
        if not os.isatty(sys.stdout.fileno()):
            return text
    except Exception:
        return text
    codes = "".join(_ANSI.get(s, "") for s in styles)
    return f"{codes}{text}{_ANSI['reset']}"


def _hr(char: str = "─", style: str = "gold") -> None:
    import shutil
    w = shutil.get_terminal_size((100, 24)).columns
    print(_C(char * w, style))


def _section(title: str) -> None:
    _hr()
    print(_C(f"  {title}", "bold", "yellow"))
    _hr()
