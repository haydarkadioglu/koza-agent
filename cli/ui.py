"""UI helpers — ANSI colours, menus, spinners, banner."""
import sys
import os
import threading as _threading

# ── ANSI colours ──────────────────────────────────────────────────────────────
_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "teal": "\033[36m",  "cyan": "\033[96m",
    "green": "\033[92m", "red": "\033[91m", "blue": "\033[94m",
    "white": "\033[97m", "grey": "\033[90m", "magenta": "\033[95m",
    # legacy aliases kept so nothing breaks
    "yellow": "\033[36m", "gold": "\033[96m",
}


def _C(text: str, *styles: str) -> str:
    """Wrap text in ANSI codes if terminal supports colour."""
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
    """Print a styled section header."""
    _hr()
    print(_C(f"  {title}", "bold", "yellow"))
    _hr()


def _config_path() -> str:
    from pathlib import Path
    return str(Path.home() / ".Koza" / "config.yaml")


def _print_error(exc: Exception, fatal: bool = False) -> None:
    """Display a styled error message instead of a raw traceback."""
    etype = type(exc).__name__
    msg = str(exc)

    # Friendly messages for common API errors
    hint = ""
    msg_lower = msg.lower()
    if "401" in msg or "authentication" in msg_lower or "api key" in msg_lower:
        hint = "Check your API key in:  koza config  or re-run  koza setup"
    elif "400" in msg or "bad request" in msg_lower or "deserialize" in msg_lower:
        hint = "The request was rejected by the provider. Try a different model or check tool format."
    elif "429" in msg or "rate limit" in msg_lower:
        hint = "Rate limit hit. Wait a moment and try again, or configure a fallback provider."
    elif "connection" in msg_lower or "timeout" in msg_lower or "refused" in msg_lower:
        hint = "Cannot reach the provider. Check your internet / Ollama is running."
    elif "model" in msg_lower and ("not found" in msg_lower or "does not exist" in msg_lower):
        hint = "Model not found. Run  koza config  to check the configured model."

    _hr("─", "red")
    print(_C(f"\n  ✗  {etype}", "red", "bold") + _C(f"  {'(fatal) ' if fatal else ''}", "red"))
    display_msg = msg if len(msg) <= 200 else msg[:200] + "…"
    print(_C(f"  {display_msg}\n", "white"))
    if hint:
        print(_C(f"  💡 {hint}\n", "yellow"))
    _hr("─", "red")
    print()


def _select_menu(label: str, options: list, default_idx: int = 0) -> str:
    """
    Arrow-key interactive menu. Returns selected item.
    Works on Windows (msvcrt) and Unix (tty/termios).
    Falls back to plain input if terminal is not interactive.
    """
    try:
        if not os.isatty(sys.stdin.fileno()):
            raise OSError("not a tty")
    except Exception:
        return _prompt(label, default=options[default_idx] if options else "", choices=options)

    idx = default_idx

    def _draw(idx):
        for i, opt in enumerate(options):
            if i == idx:
                print(f"  {_C('❯', 'yellow')} {_C(opt, 'white', 'bold')}", flush=True)
            else:
                print(f"    {_C(opt, 'grey')}", flush=True)

    def _clear(n):
        for _ in range(n):
            sys.stdout.write("\033[1A\033[2K")
        sys.stdout.flush()

    print(f"  {_C(label, 'cyan', 'bold')}", flush=True)
    _draw(idx)

    if sys.platform == "win32":
        import msvcrt
        while True:
            ch = msvcrt.getch()
            if ch in (b"\xe0", b"\x00"):
                arrow = msvcrt.getch()
                if arrow == b"H" and idx > 0:            # Up
                    idx -= 1
                elif arrow == b"P" and idx < len(options) - 1:  # Down
                    idx += 1
            elif ch == b"\r":  # Enter
                break
            _clear(len(options))
            _draw(idx)
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    seq = sys.stdin.read(2)
                    if seq == "[A" and idx > 0:        # Up
                        idx -= 1
                    elif seq == "[B" and idx < len(options) - 1:  # Down
                        idx += 1
                elif ch in ("\r", "\n"):
                    break
                elif ch == "\x03":
                    raise KeyboardInterrupt
                _clear(len(options))
                _draw(idx)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # Print final confirmed selection
    _clear(len(options))
    print(f"  {_C(label, 'cyan')}  {_C('❯', 'yellow')} {_C(options[idx], 'white', 'bold')}", flush=True)
    return options[idx]


def _prompt(label: str, default: str = "", choices: list = None) -> str:
    hint = _C(f" [{default}]", "grey") if default else ""
    if choices:
        hint += _C(f" ({'/'.join(choices)})", "grey")
    try:
        val = input(f"  {_C(label, 'cyan')}{hint}{_C(' › ', 'gold')}").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)
    return val if val else default


def _extract_gemini_cookies() -> tuple:
    """Try to extract Gemini __Secure-1PSID cookies from installed browsers.
    Returns (cookie_1psid, cookie_1psidts, browser_name) or ("", "", "").
    """
    try:
        import browser_cookie3
    except ImportError:
        return "", "", ""

    browsers = [
        ("Chrome",  browser_cookie3.chrome),
        ("Edge",    browser_cookie3.edge),
        ("Firefox", browser_cookie3.firefox),
        ("Brave",   browser_cookie3.brave),
        ("Opera",   browser_cookie3.opera),
    ]
    for name, loader in browsers:
        try:
            jar = loader(domain_name=".google.com")
            psid = psidts = ""
            for c in jar:
                if c.name == "__Secure-1PSID":
                    psid = c.value
                elif c.name == "__Secure-1PSIDTS":
                    psidts = c.value
            if psid:
                return psid, psidts, name
        except Exception:
            continue
    return "", "", ""


def _prompt_secret(label: str) -> str:
    import getpass
    try:
        return getpass.getpass(f"  {_C(label, 'cyan')}{_C(' › ', 'gold')}").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)


# ── Spinner ───────────────────────────────────────────────────────────────────

_spinner_active = False
_spinner_thread = None
_spinner_msg    = "  Working…"

_SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _spinner_active_check() -> bool:
    return _spinner_active


def _spinner_set(msg: str) -> None:
    """Update spinner message while it's running."""
    global _spinner_msg
    _spinner_msg = msg


def _spinner_start(msg: str) -> None:
    import itertools, time as _time
    global _spinner_active, _spinner_thread, _spinner_msg
    _spinner_msg = msg
    if _spinner_active:
        return  # already running — just update message via _spinner_set
    _spinner_active = True

    def _spin():
        for ch in itertools.cycle(_SPINNER_CHARS):
            if not _spinner_active:
                break
            current = _spinner_msg
            print(f"\r{_C(ch, 'cyan')} {_C(current, 'grey')}   ", end="", flush=True)
            _time.sleep(0.08)
        print("\r" + " " * 80 + "\r", end="", flush=True)

    _spinner_thread = _threading.Thread(target=_spin, daemon=True)
    _spinner_thread.start()


def _spinner_stop() -> None:
    global _spinner_active, _spinner_thread
    _spinner_active = False
    if _spinner_thread:
        _spinner_thread.join(timeout=0.5)
        _spinner_thread = None
    import time as _t
    _t.sleep(0.05)  # let terminal settle before next print
    print("\r" + " " * 80 + "\r", end="", flush=True)


# ── Markdown renderer ─────────────────────────────────────────────────────────

def _render_md(text: str) -> str:
    """
    Convert Markdown to ANSI-styled plain text.
    Handles: headings, bold, italic, code, tables, hr, bullet/numbered lists.
    """
    import re, shutil
    tw = shutil.get_terminal_size((100, 24)).columns - 6  # usable width inside box

    def _inline(s: str) -> str:
        """Apply inline formatting (bold/italic/code)."""
        s = re.sub(r"\*\*(.+?)\*\*", lambda m: _C(m.group(1), "white", "bold"), s)
        s = re.sub(r"\*(.+?)\*",     lambda m: _C(m.group(1), "white"), s)
        s = re.sub(r"`([^`]+)`",     lambda m: _C(m.group(1), "cyan"), s)
        return s

    lines = text.splitlines()
    out = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── Heading (# / ## / ###) ────────────────────────────────────────────
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))
            title = _inline(m.group(2))
            if level == 1:
                out.append(_C(title, "yellow", "bold"))
                out.append(_C("─" * min(len(m.group(2)) + 2, tw), "gold"))
            elif level == 2:
                out.append(_C("  " + title, "yellow", "bold"))
            else:
                out.append(_C("    " + title, "cyan", "bold"))
            i += 1
            continue

        # ── Horizontal rule (---  or  ===) ───────────────────────────────────
        if re.match(r"^[-=]{3,}\s*$", stripped):
            out.append(_C("─" * tw, "grey"))
            i += 1
            continue

        # ── Markdown table  (|...|...|) ───────────────────────────────────────
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            # Filter out separator rows (|---|---|)
            data_rows = [r for r in table_lines if not re.match(r"^\|[-| :]+\|$", r)]
            if data_rows:
                # Parse cells
                rows = [[c.strip() for c in r.strip("|").split("|")] for r in data_rows]
                n_cols = max(len(r) for r in rows)
                rows = [r + [""] * (n_cols - len(r)) for r in rows]
                col_w = [max(len(re.sub(r"\x1b\[[^m]*m", "", c)) for c in col) for col in zip(*rows)]
                # Header separator
                sep = _C("  " + "┼".join("─" * (w + 2) for w in col_w), "grey")
                for ri, row in enumerate(rows):
                    cells = []
                    for ci, cell in enumerate(row):
                        plain = re.sub(r"\x1b\[[^m]*m", "", cell)
                        pad = col_w[ci] - len(plain)
                        cells.append(" " + _inline(cell) + " " * (pad + 1))
                    styled_row = _C("  │", "grey") + _C("│", "grey").join(cells) + _C("│", "grey")
                    if ri == 0:
                        out.append(_C("  " + "┬".join("─" * (w + 2) for w in col_w), "grey"))
                    out.append(styled_row)
                    if ri == 0:
                        out.append(sep)
                out.append(_C("  " + "┴".join("─" * (w + 2) for w in col_w), "grey"))
            continue

        # ── Bullet list (- item  or  * item) ─────────────────────────────────
        m = re.match(r"^[-*]\s+(.+)$", stripped)
        if m:
            out.append(_C("  • ", "yellow") + _inline(m.group(1)))
            i += 1
            continue

        # ── Numbered list (1. item) ────────────────────────────────────────────
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            out.append(_C(f"  {m.group(1)}. ", "yellow") + _inline(m.group(2)))
            i += 1
            continue

        # ── Normal text ───────────────────────────────────────────────────────
        out.append(_inline(stripped) if stripped else "")
        i += 1

    return "\n".join(out)


# ── Banner ────────────────────────────────────────────────────────────────────

# Koza ASCII logo (koza = cocoon 🪡)
_LOGO = r"""
   ██╗  ██╗ ██████╗ ███████╗ █████╗
   ██║ ██╔╝██╔═══██╗╚══███╔╝██╔══██╗
   █████╔╝ ██║   ██║  ███╔╝ ███████║
   ██╔═██╗ ██║   ██║ ███╔╝  ██╔══██║
   ██║  ██╗╚██████╔╝███████╗██║  ██║
   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
""".strip("\n")

# Tool categories for the startup panel
_TOOL_CATEGORIES = {
    "config":      ["get_config", "set_config", "delete_config"],
    "filesystem":  ["read_file", "write_file", "list_dir", "delete_file"],
    "shell":       ["run_command"],
    "web":         ["web_search", "fetch_url"],
    "code":        ["run_python", "run_node", "run_script", "run_jupyter_cell"],
    "kanban":      ["create_task", "list_tasks", "move_task"],
    "cron":        ["create_cron", "list_crons", "delete_cron"],
    "memory":      ["memory_store", "memory_recall", "wm_add", "wm_get"],
    "agents":      ["spawn_subagent", "get_subagent_status"],
    "messaging":   ["send_message", "telegram_send", "discord_send", "whatsapp_send"],
    "github":      ["github_search_code", "github_create_issue"],
    "finance":     ["crypto_price", "stock_price"],
    "media":       ["spotify_search", "youtube_search", "gif_search"],
    "research":    ["arxiv_search", "wikipedia_search"],
    "security":    ["port_scan", "ssl_check", "whois_lookup"],
    "social":      ["twitter_search", "bluesky_search", "hackernews_top", "linkedin_post"],
    "smarthome":   ["hue_set_light", "mqtt_publish"],
    "email":       ["send_email", "read_emails"],
    "devops":      ["git_operation", "docker_run"],
    "notes":       ["note_create", "note_search"],
    "productivity": ["google_calendar_list", "airtable_query"],
}


def _get_version() -> str:
    try:
        from importlib.metadata import version
        return version("koza")
    except Exception:
        try:
            from pathlib import Path
            import re
            # cli/ui.py lives one level below the project root
            toml = (Path(__file__).parent.parent / "pyproject.toml").read_text()
            m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
            return m.group(1) if m else "dev"
        except Exception:
            return "dev"


def _print_banner(cfg: dict) -> None:
    from datetime import date
    import shutil

    ver = _get_version()
    today = date.today().strftime("%Y.%m.%d")
    provider = cfg.get("provider", "?")
    model = cfg.get("model") or "default"
    fallback = cfg.get("fallback_provider", "")
    term_w = shutil.get_terminal_size((100, 24)).columns

    # ── Header bar ──────────────────────────────────────────────────────────
    header = f" Koza Agent v{ver} ({today}) · {provider} / {model} "
    if fallback:
        header += f"· fallback: {fallback} "
    bar = "─" * max(0, term_w - 2)
    print(_C(f"\n┌{bar}┐", "teal"))
    pad = max(0, term_w - 2 - len(header))
    print(_C(f"│{header}{' ' * pad}│", "teal"))
    print(_C(f"└{bar}┘", "teal"))

    # ── Logo + tool panel (side-by-side) ─────────────────────────────────
    logo_lines = _LOGO.split("\n")
    logo_w = max(len(l) for l in logo_lines) + 2

    panel_lines: list = []
    panel_lines.append(_C("  Available Tools", "bold") + _C("", "yellow"))

    for cat, tools in _TOOL_CATEGORIES.items():
        preview = ", ".join(tools[:3])
        if len(tools) > 3:
            preview += f", …+{len(tools)-3}"
        panel_lines.append(
            f"  {_C(cat + ':', 'cyan')}  {_C(preview, 'white')}"
        )

    # Pad logo and panel to same height
    height = max(len(logo_lines), len(panel_lines))
    logo_lines += [""] * (height - len(logo_lines))
    panel_lines += [""] * (height - len(panel_lines))

    for logo_l, panel_l in zip(logo_lines, panel_lines):
        padded = f"  {logo_l:<{logo_w}}"
        print(f"{_C(padded, 'teal')}  {panel_l}")

    # ── Tool count bar ───────────────────────────────────────────────────
    try:
        from tools.registry import ALL_TOOLS
        n_tools = len(ALL_TOOLS)
    except Exception:
        n_tools = 0
    n_cats = len(_TOOL_CATEGORIES)
    summary = f"  {n_tools} tools · {n_cats} categories · type /help for commands"
    print(_C("─" * term_w, "teal"))
    print(_C(summary, "grey"))
    print(_C("─" * term_w, "teal"))
    print(_C("  Welcome to Koza! Type your message or /help for commands.\n", "green"))


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
