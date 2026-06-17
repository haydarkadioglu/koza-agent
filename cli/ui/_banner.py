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
    model_short = model.split("/")[-1] if "/" in model else model

    # Print logo with enhanced teal-to-cyan gradient
    for i, line in enumerate(_LOGO.split("\n")):
        color = _GRADIENT[i % len(_GRADIENT)]
        print(f"{color}{line}{_RESET}")

    # Stylish info bar
    import shutil
    w = min(shutil.get_terminal_size((80, 24)).columns, 60)
    print(_C("┄" * w, "grey"))
    print(
        _C("  🦎 Koza ", "cyan", "bold")
        + _C(f"v{ver}", "grey")
        + _C("  │  ", "grey")
        + _C(f"🧠 {model_short}", "teal")
    )
    from cli.i18n import _T
    print(
        _C(_T("  💡 /help for commands  │  /model to switch"), "grey")
    )
    print(_C("┄" * w, "grey"))
    print()


def _print_inline_help() -> None:
    from cli.i18n import _T
    print(_C(_T("  Commands"), "bold"))
    cmds = [
        ("/help",         _T("Show this help")),
        ("/sessions",     _T("Browse / load / delete saved sessions")),
        ("/save [title]", _T("Save current session")),
        ("/kanban",       _T("Show Kanban board & cron jobs")),
        ("/memory",       _T("Show working memory")),
        ("/reset",        _T("Clear conversation history")),
        ("/provider",     _T("Switch LLM provider")),
        ("exit",          _T("Quit Koza")),
    ]
    for cmd, desc in cmds:
        print(f"  {_C(cmd, 'cyan'):<28}  {desc}")
    print()
