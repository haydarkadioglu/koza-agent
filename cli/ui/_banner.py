"""Banner, logo, inline help."""
from pathlib import Path
from ._colors import _C, _hr

_LOGO = r"""
   ██╗  ██╗ ██████╗ ███████╗ █████╗
   ██║ ██╔╝██╔═══██╗╚══███╔╝██╔══██╗
   █████╔╝ ██║   ██║  ███╔╝ ███████║
   ██╔═██╗ ██║   ██║ ███╔╝  ██╔══██║
   ██║  ██╗╚██████╔╝███████╗██║  ██║
   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
""".strip("\n")

# Teal-to-cyan gradient for logo lines
_GRADIENT = [
    "\033[36m",      # teal
    "\033[36m",      # teal
    "\033[38;5;44m", # teal-cyan blend
    "\033[38;5;80m", # mid cyan
    "\033[96m",      # bright cyan
    "\033[96m",      # bright cyan
]

_RESET = "\033[0m"


def _get_version() -> str:
    try:
        from importlib.metadata import version
        return version("koza")
    except Exception:
        try:
            import re
            # cli/ui/_banner.py → project root is 3 parents up
            toml = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
            m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
            return m.group(1) if m else "dev"
        except Exception:
            return "dev"


def _print_banner(cfg: dict) -> None:
    ver = _get_version()
    model = cfg.get("model") or "default"

    # Print logo with teal-to-cyan gradient
    for i, line in enumerate(_LOGO.split("\n")):
        color = _GRADIENT[i % len(_GRADIENT)]
        print(f"{color}{line}{_RESET}")

    # Version, model, and help hint below logo
    print(_C(f"  v{ver}", "grey"))
    print(_C(f"  model: {model}", "grey"))
    print(_C("  type /help for commands", "grey"))
    print()


def _print_inline_help() -> None:
    print(_C("\n  Commands", "bold"))
    cmds = [
        ("/help",   "Show this help"),
        ("/kanban", "Show Kanban board & cron jobs"),
        ("/memory", "Show working memory"),
        ("/reset",  "Clear conversation history"),
        ("exit",    "Quit Koza"),
    ]
    for cmd, desc in cmds:
        print(f"  {_C(cmd, 'cyan'):<28}  {desc}")
    print()
