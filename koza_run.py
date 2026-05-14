#!/usr/bin/env python3
"""Koza Agent — Entry point (plain CLI)."""
import sys

# ── ANSI colours (defined first so every function can use _C) ─────────────────
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
    import os
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

PROVIDERS = ["ollama", "openai", "anthropic", "deepseek", "gemini"]
PROVIDER_MODELS = {
    "openai":    ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"],
    "deepseek":  ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
    "gemini":    ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"],
    "ollama":    ["llama3", "mistral", "codellama", "phi3"],
}
NEEDS_KEY = {"openai", "anthropic", "deepseek", "gemini"}


# ── Sub-command handlers ──────────────────────────────────────────────────────

def cmd_start(args: list[str]) -> None:
    """Start the Koza plain CLI chat."""
    from config import load_config, config_exists
    if not config_exists():
        print(_C("  No config found. Running setup first…\n", "grey"))
        cmd_setup([])

    try:
        cfg = load_config()
        from providers.factory import get_provider
        from core import Agent
        provider = get_provider(cfg)
        agent = Agent(provider, db_path=cfg["db_path"], cfg=cfg)
    except Exception as exc:
        _print_error(exc, fatal=True)
        return

    # Auto-start Telegram bot in background if token is configured
    if cfg.get("telegram_token"):
        try:
            from tg_bot import start_bot_thread
            started = start_bot_thread(agent, cfg)
            if started:
                print(_C("  🤖  Telegram bot arka planda dinleniyor.\n", "grey"))
        except Exception:
            pass

    _plain_cli(agent, cfg)


def cmd_setup(args: list[str]) -> None:
    """Interactive plain-terminal setup wizard."""
    from config import save_config, default_config

    _hr()
    print(_C("\n  ✦  K O Z A   A G E N T  ·  Setup Wizard\n", "bold", "yellow"))
    print(_C("  Configure your LLM provider. Press Enter to accept defaults.\n", "grey"))

    # ── Provider ──────────────────────────────────────────────────────────────
    _hr("·", "grey")
    print(_C("  Primary Provider", "cyan", "bold"))
    _hr("·", "grey")
    try:
        provider = _select_menu("Select provider", PROVIDERS, default_idx=0)
    except (KeyboardInterrupt, EOFError):
        sys.exit(0)

    default_model = PROVIDER_MODELS.get(provider, [""])[0]
    models = PROVIDER_MODELS.get(provider, [default_model])
    try:
        model = _select_menu("Select model", models, default_idx=0)
    except (KeyboardInterrupt, EOFError):
        sys.exit(0)

    api_key = ""
    if provider in NEEDS_KEY:
        api_key = _prompt_secret(f"API key for {provider} (required)")
        while not api_key:
            print(_C(f"  ⚠  API key is required for {provider}.", "red"))
            api_key = _prompt_secret(f"API key for {provider}")

    ollama_url = "http://localhost:11434"
    if provider == "ollama":
        ollama_url = _prompt("Ollama base URL", default="http://localhost:11434")

    # ── Fallback provider ─────────────────────────────────────────────────────
    _hr("·", "grey")
    print(_C("  Fallback Provider", "cyan", "bold"))
    print(_C("  Used automatically if primary provider fails or is unavailable.", "grey"))
    _hr("·", "grey")
    enable_fallback = _prompt("Enable fallback provider?", default="n", choices=["y", "n"])

    fallback_provider = ""
    fallback_model = ""
    fallback_key = ""
    if enable_fallback.lower() == "y":
        remaining = [p for p in PROVIDERS if p != provider]
        try:
            fallback_provider = _select_menu("Select fallback provider", remaining, default_idx=0)
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
        fb_models = PROVIDER_MODELS.get(fallback_provider, [PROVIDER_MODELS.get(fallback_provider, [""])[0]])
        try:
            fallback_model = _select_menu("Select fallback model", fb_models, default_idx=0)
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
        if fallback_provider in NEEDS_KEY:
            fallback_key = _prompt_secret(f"API key for {fallback_provider} (optional if already set)")

    # ── Build config ──────────────────────────────────────────────────────────
    cfg = default_config()
    cfg["provider"] = provider
    cfg["model"] = model
    if api_key:
        cfg["providers"][provider]["api_key"] = api_key
    if provider == "ollama":
        cfg["providers"]["ollama"]["base_url"] = ollama_url
    if fallback_provider:
        cfg["fallback_provider"] = fallback_provider
        cfg["fallback_model"] = fallback_model
        if fallback_key:
            cfg["providers"].setdefault(fallback_provider, {})["api_key"] = fallback_key

    save_config(cfg)
    _hr()
    print(_C(f"\n  ✅  Config saved → {_config_path()}\n", "green"))
    _hr()


def cmd_config(args: list[str]) -> None:
    """Show current configuration (API keys masked)."""
    from config import load_config, config_exists
    if not config_exists():
        print(_C("  ✗  No config file found.", "red") + _C("  Run:  koza setup", "grey"))
        return

    cfg = load_config()
    _hr()
    print(_C("  KOZA  ·  Current Configuration", "bold", "yellow"))
    _hr()
    print(f"\n  {_C('Config file', 'grey')}  :  {_C(_config_path(), 'white')}")
    print(f"  {_C('DB path    ', 'grey')}  :  {_C(str(cfg.get('db_path', '?')), 'white')}")
    print(f"  {_C('Provider   ', 'grey')}  :  {_C(str(cfg.get('provider', '?')), 'cyan')}")
    print(f"  {_C('Model      ', 'grey')}  :  {_C(str(cfg.get('model') or '(default)'), 'cyan')}")
    fallback = cfg.get("fallback_provider", "")
    if fallback:
        print(f"  {_C('Fallback   ', 'grey')}  :  {_C(fallback, 'cyan')} / {cfg.get('fallback_model') or 'default'}")
    print(f"  {_C('Vault path ', 'grey')}  :  {_C(str(cfg.get('vault_path', '?')), 'white')}")

    print(_C("\n  ┌ Providers ─────────────────────────────────────┐", "grey"))
    for name, vals in cfg.get("providers", {}).items():
        key = vals.get("api_key") or vals.get("token", "")
        masked = ("*" * 6 + key[-4:]) if len(key) > 6 else (_C("set", "green") if key else _C("—", "red"))
        base = vals.get("base_url", "")
        print(f"  │  {_C(f'{name:<12}', 'cyan')}  key={masked:<16}  {_C(base, 'grey')}")
    print(_C("  └────────────────────────────────────────────────┘", "grey"))

    print(_C("\n  ┌ Messaging ──────────────────────────────────────┐", "grey"))
    for plat, vals in cfg.get("messaging", {}).items():
        tok = vals.get("token") or vals.get("webhook_url") or vals.get("account_sid", "")
        status = _C("configured", "green") if tok else _C("—", "red")
        print(f"  │  {_C(f'{plat:<12}', 'cyan')}  {status}")
    print(_C("  └────────────────────────────────────────────────┘", "grey"))
    print()


def cmd_kanban(args: list[str]) -> None:
    """Show Kanban board and cron jobs in the terminal."""
    from config import load_config
    cfg = load_config()
    from skills.kanban import init_db, list_tasks
    from skills.cron_db import init_db as cron_init
    from skills.cron import list_crons
    init_db(cfg["db_path"])
    cron_init(cfg["db_path"])
    _hr()
    print(_C("  KANBAN  ·  Tasks", "bold", "yellow"))
    _hr()
    print(list_tasks())
    _hr()
    print(_C("  CRON JOBS", "bold", "cyan"))
    _hr()
    print(list_crons())
    print()


def cmd_uninstall(args: list[str]) -> None:
    """Remove config and database files from ~/.koza/."""
    import shutil
    from pathlib import Path
    koza_dir = Path.home() / ".Koza"
    if not koza_dir.exists():
        print(_C("  ✗  Nothing to remove — ~/.Koza does not exist.", "yellow"))
        return
    _hr()
    print(_C(f"\n  ⚠  This will permanently delete: {koza_dir}", "red", "bold"))
    print(_C("  (config file, database, all data)\n", "grey"))
    try:
        answer = input(_C("  Type 'yes' to confirm: ", "red")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return
    if answer == "yes":
        shutil.rmtree(koza_dir)
        _hr()
        print(_C(f"\n  ✅  Removed {koza_dir}\n", "green"))
        _hr()
    else:
        print(_C("  Cancelled.", "grey"))


def cmd_telegram(args: list[str]) -> None:
    """Configure and start the Koza Telegram bot (foreground)."""
    from config import load_config, save_config
    cfg = load_config()
    token = cfg.get("telegram_token", "").strip()

    if not token:
        _hr()
        print(_C("\n  🤖  Koza Telegram Bot Kurulumu\n", "bold", "cyan"))
        print(_C("  1. @BotFather'a git → /newbot → bir isim ver\n", "grey"))
        print(_C("  2. BotFather'ın verdiği token'ı buraya yapıştır:\n", "grey"))
        token = input(_C("  Bot token › ", "cyan")).strip()
        if not token:
            print(_C("  ✗  Token girilmedi.\n", "red"))
            return
        cfg["telegram_token"] = token
        save_config(cfg)
        print(_C("\n  ✓  Token kaydedildi.", "green"))
        print(_C("  İlk mesajı atan kullanıcı otomatik olarak sahip olarak kaydedilecek.\n", "grey"))
        _hr()

    owner_id = cfg.get("telegram_owner_id")
    if owner_id:
        print(_C(f"  👤  Kayıtlı sahip: chat_id={owner_id}", "grey"))
        reset = input(_C("  Sahip kaydını sıfırla? (e/H) › ", "cyan")).strip().lower()
        if reset == "e":
            cfg.pop("telegram_owner_id", None)
            save_config(cfg)
            print(_C("  ✓  Sıfırlandı. İlk mesajı atan yeni sahip olacak.\n", "green"))

    try:
        from tg_bot import run_bot_foreground
        run_bot_foreground(token=token, cfg=cfg)
    except KeyboardInterrupt:
        print(_C("\n  Telegram bot durduruldu.\n", "grey"))
    except ImportError as e:
        print(_C(f"\n  ✗  {e}\n  pip install python-telegram-bot\n", "red"))


def cmd_version(args: list[str]) -> None:
    """Print Koza version."""
    ver = _get_version()
    print(_C(f"\n  Koza  ", "bold", "yellow") + _C(f"v{ver}\n", "cyan"))


def cmd_help(args: list[str]) -> None:
    """Print this help text."""
    _hr()
    print(_C("  KOZA  ·  Command Reference", "bold", "yellow"))
    _hr()
    print(_C("\n  USAGE\n", "bold"))
    print(f"    {_C('koza', 'cyan')} {_C('[command]', 'grey')}\n")
    print(_C("  COMMANDS\n", "bold"))
    cmds = [
        ("(none) / start", "Start interactive chat (default)"),
        ("setup",          "Configure provider, API keys, fallback"),
        ("config",         "Show current configuration"),
        ("kanban",         "Show Kanban board and cron jobs"),
        ("telegram",       "Start Telegram bot (remote chat)"),
        ("version",        "Show Koza version"),
        ("uninstall",      "Remove ~/.Koza config and database"),
        ("help",           "Show this help"),
    ]
    for cmd, desc in cmds:
        print(f"    {_C(f'{cmd:<22}', 'cyan')}  {desc}")
    print(_C("\n  EXAMPLES\n", "bold"))
    examples = ["koza", "koza setup", "koza config", "koza kanban", "koza version"]
    for ex in examples:
        print(f"    {_C(ex, 'white')}")
    print(_C("\n  CHAT COMMANDS  (inside chat)\n", "bold"))
    chat_cmds = [
        ("/help",   "Show inline help"),
        ("/kanban", "Show Kanban board"),
        ("/memory", "Show working memory"),
        ("/reset",  "Clear conversation history"),
        ("exit",    "Quit Koza"),
    ]
    for cmd, desc in chat_cmds:
        print(f"    {_C(f'{cmd:<22}', 'cyan')}  {desc}")
    print()
    _hr()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _config_path() -> str:
    from pathlib import Path
    return str(Path.home() / ".Koza" / "config.yaml")


# ── Spinner ───────────────────────────────────────────────────────────────────
import threading as _threading

_spinner_active = False
_spinner_thread = None

_SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

def _spinner_start(msg: str) -> None:
    import itertools, time as _time
    global _spinner_active, _spinner_thread
    _spinner_active = True
    def _spin():
        for ch in itertools.cycle(_SPINNER_CHARS):
            if not _spinner_active:
                break
            print(f"\r{_C(ch, 'cyan')} {_C(msg, 'grey')}   ", end="", flush=True)
            _time.sleep(0.08)
        print("\r" + " " * (len(msg) + 6) + "\r", end="", flush=True)
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
    print("\r" + " " * 70 + "\r", end="", flush=True)


def _print_error(exc: Exception, fatal: bool = False) -> None:
    """Display a styled error message instead of a raw traceback."""
    import traceback
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
    print(_C(f"\n  ✗  {etype}", "red", "bold") + _C(f"  {'(fatal) ' if fatal else ''}","red"))
    # Trim the message if it's very long
    display_msg = msg if len(msg) <= 200 else msg[:200] + "…"
    print(_C(f"  {display_msg}\n", "white"))
    if hint:
        print(_C(f"  💡 {hint}\n", "yellow"))
    _hr("─", "red")
    print()


def _select_menu(label: str, options: list[str], default_idx: int = 0) -> str:
    """
    Arrow-key interactive menu. Returns selected item.
    Works on Windows (msvcrt) and Unix (tty/termios).
    Falls back to plain input if terminal is not interactive.
    """
    import os, sys
    try:
        if not os.isatty(sys.stdin.fileno()):
            raise OSError("not a tty")
    except Exception:
        # Non-interactive: just use _prompt
        return _prompt(label, default=options[default_idx] if options else "", choices=options)

    idx = default_idx

    def _draw(idx):
        for i, opt in enumerate(options):
            if i == idx:
                print(f"  {_C('❯', 'yellow')} {_C(opt, 'white', 'bold')}", flush=True)
            else:
                print(f"    {_C(opt, 'grey')}", flush=True)

    def _clear(n):
        import sys as _sys
        for _ in range(n):
            _sys.stdout.write("\033[1A\033[2K")
        _sys.stdout.flush()

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


def _prompt(label: str, default: str = "", choices: list = None) -> str:
    hint = _C(f" [{default}]", "grey") if default else ""
    if choices:
        hint += _C(f" ({'/'.join(choices)})", "grey")
    try:
        val = input(f"  {_C(label, 'cyan')}{hint}{_C(' › ', 'gold')}").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)
    return val if val else default


def _prompt_secret(label: str) -> str:
    import getpass
    try:
        return getpass.getpass(f"  {_C(label, 'cyan')}{_C(' › ', 'gold')}").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)


def _plain_cli(agent, cfg: dict) -> None:
    import time, shutil
    _print_banner(cfg)

    session_start = time.time()
    total_tokens = 0

    # Token limits per provider (rough estimates)
    _TOKEN_LIMITS = {
        "deepseek": 64_000, "openai": 128_000, "anthropic": 200_000,
        "gemini": 1_000_000, "ollama": 32_000,
    }
    provider_name = cfg.get("provider", "")
    model_name = cfg.get("model") or provider_name
    token_limit = _TOKEN_LIMITS.get(provider_name, 32_000)

    # ── Tool permission system ────────────────────────────────────────────────
    # Tools that are always auto-allowed (read-only / non-destructive)
    _SAFE_TOOLS = {
        "web_search", "fetch_url", "list_dir", "read_file", "wm_add", "wm_get",
        "memory_recall", "memory_search", "memory_list", "recall_sessions",
        "list_sessions", "list_tasks", "list_crons", "list_subagents",
        "get_subagent_status", "github_search_code", "github_list_prs",
        "github_repo_info", "pandas_query", "matplotlib_plot",
    }
    _session_allowed: set[str] = set()
    _permanent_allowed: set[str] = set(cfg.get("allowed_tools", []))
    _session_allow_all = [False]  # mutable flag for closure

    def _ask_permission(name: str, args: dict) -> bool:
        if _session_allow_all[0]:
            return True
        if name in _SAFE_TOOLS or name in _session_allowed or name in _permanent_allowed:
            return True
        _spinner_stop()
        arg_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in list(args.items())[:3])
        print()
        print(_C("  ┌─ Permission Required ", "yellow", "bold") + _C("─" * 40, "gold"))
        print(_C("  │  Tool  : ", "grey") + _C(name, "cyan", "bold"))
        if arg_preview:
            print(_C("  │  Args  : ", "grey") + _C(arg_preview, "white"))
        print(_C("  └" + "─" * 53, "yellow"))
        try:
            choice = _select_menu(
                "Allow this tool?",
                ["Allow (this session)", "Allow all tools (this session)", "Allow permanently", "Allow (once)", "Deny"],
                default_idx=0,
            )
        except (KeyboardInterrupt, EOFError):
            return False

        if choice == "Allow (this session)":
            _session_allowed.add(name)
            return True
        elif choice == "Allow all tools (this session)":
            _session_allow_all[0] = True
            print(_C("  ✓  Bu oturumda tüm tool'lar otomatik izinli.\n", "green"))
            return True
        elif choice == "Allow permanently":
            _permanent_allowed.add(name)
            try:
                from config import load_config, save_config
                c = load_config()
                existing = set(c.get("allowed_tools", []))
                existing.add(name)
                c["allowed_tools"] = sorted(existing)
                save_config(c)
            except Exception:
                pass
            return True
        elif choice == "Allow (once)":
            return True
        else:
            print(_C(f"  ✗  {name} denied.\n", "red"))
            return False

    agent.permission_callback = _ask_permission

    # Inject launch CWD into the agent's system prompt so model knows where it is
    from skills.shell import get_cwd as _get_cwd
    _launch_cwd = _get_cwd()
    if agent.messages and agent.messages[0]["role"] == "system":
        agent.messages[0]["content"] += f"\n\n**Current working directory:** `{_launch_cwd}`\nAll relative paths resolve from here. Use run_command with 'cd <path>' to change directory."

    def _status_bar():
        elapsed = int(time.time() - session_start)
        h, m = divmod(elapsed // 60, 60)
        s_time = f"{h}h {m:02d}m" if h else f"{m}m"
        pct = min(100, int(total_tokens / token_limit * 100))
        bar_w = 12
        filled = int(bar_w * pct / 100)
        bar = "█" * filled + "░" * (bar_w - filled)
        tok_str = f"{total_tokens//1000}K/{token_limit//1000}K" if total_tokens >= 1000 else f"{total_tokens}/{token_limit//1000}K"
        tw = shutil.get_terminal_size((100, 24)).columns
        line = (
            f"  {_C(model_name, 'cyan')}  {_C('│', 'grey')}  "
            f"{_C(tok_str, 'white')}  {_C('│', 'grey')}  "
            f"[{_C(bar, 'green' if pct < 70 else 'yellow' if pct < 90 else 'red')}]  "
            f"{_C(f'{pct}%', 'grey')}  {_C('│', 'grey')}  "
            f"{_C(s_time, 'grey')}"
        )
        print(_C("─" * tw, "grey"))
        print(line)
        print(_C("─" * tw, "grey"))

    while True:
        try:
            user_input = input(
                _C("\n  ● ", "yellow", "bold") + _C("You  › ", "cyan", "bold")
            ).strip()
        except (EOFError, KeyboardInterrupt):
            _hr()
            print(_C("\n  Goodbye! 👋\n", "yellow"))
            _hr()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            _hr()
            print(_C("\n  Goodbye! 👋\n", "yellow"))
            _hr()
            break
        if user_input == "/reset":
            agent.reset()
            total_tokens = 0
            print(_C("  ✓  Chat reset.\n", "green"))
            continue
        if user_input == "/kanban":
            cmd_kanban([])
            continue
        if user_input == "/memory":
            from skills.working_memory import wm_get_context
            ctx = wm_get_context()
            _hr("·", "grey")
            print(ctx or _C("  (working memory is empty)", "dim"))
            _hr("·", "grey")
            continue
        if user_input in ("/help", "/?"):
            _print_inline_help()
            continue

        # Rough token estimate for user message (4 chars ≈ 1 token)
        total_tokens += max(1, len(user_input) // 4)

        # ── Streaming response with live status ──────────────────────────────
        t_start = time.time()
        text_started = False
        full_response = ""

        try:
            for event in agent.stream_chat(user_input):
                if not isinstance(event, dict):
                    continue

                etype = event.get("type")

                if etype == "thinking":
                    if not text_started:
                        _spinner_start("  Koza is thinking…")

                elif etype == "tool_start":
                    _spinner_stop()
                    name = event["name"]
                    args = event.get("args", {})
                    arg_str = ", ".join(f"{k}={repr(v)}" for k, v in list(args.items())[:2])
                    print(
                        _C(f"  ⚙  {name}", "cyan") +
                        (_C(f"  ({arg_str})", "grey") if arg_str else ""),
                        flush=True
                    )
                    _spinner_start(f"  Running {name}…")

                elif etype == "tool_done":
                    _spinner_stop()
                    name = event["name"]
                    elapsed = event.get("elapsed", 0)
                    result = str(event.get("result", ""))
                    lines = [l for l in result.splitlines() if l.strip()]
                    summary = lines[0][:80] + ("…" if len(lines[0]) > 80 else "") if lines else "(no output)"
                    extra = _C(f"  +{len(lines)-1} lines", "grey") if len(lines) > 1 else ""
                    print(
                        _C(f"  ✓  {name}", "green") +
                        _C(f"  {elapsed:.2f}s", "grey") +
                        _C(f"  → {summary}", "white") + extra,
                        flush=True
                    )

                elif etype == "text":
                    token = event.get("token", "")
                    if not text_started:
                        _spinner_stop()
                        text_started = True
                    full_response += token
                    total_tokens += max(1, len(token) // 4)

        except KeyboardInterrupt:
            _spinner_stop()
            print(_C("\n  (interrupted)", "grey"))
            continue
        except Exception as exc:
            _spinner_stop()
            print()
            _print_error(exc)
            continue

        _spinner_stop()
        if text_started and full_response.strip():
            elapsed = time.time() - t_start
            tw = shutil.get_terminal_size((100, 24)).columns
            # ── Render buffered response with markdown ────────────────────────
            rendered_lines = _render_md(full_response).splitlines()
            print()
            print(_C("  ╭─ Koza ", "yellow", "bold") + _C("─" * (tw - 10), "gold"))
            for rline in rendered_lines:
                # Strip ANSI to measure actual display length for padding
                import re as _re
                plain_len = len(_re.sub(r"\x1b\[[^m]*m", "", rline))
                if plain_len == 0 and not rline.strip():
                    print(_C("  │", "yellow"))
                else:
                    print(_C("  │ ", "yellow") + rline)
            print(_C("  ╰─", "yellow") + _C(f"  {elapsed:.1f}s", "grey"))
            print()
            _status_bar()
        print()


# ── Banner & colours ──────────────────────────────────────────────────────────

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
    "productivity":["google_calendar_list", "airtable_query"],
}


def _get_version() -> str:
    try:
        from importlib.metadata import version
        return version("koza")
    except Exception:
        try:
            from pathlib import Path
            import re
            toml = (Path(__file__).parent / "pyproject.toml").read_text()
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

    panel_lines: list[str] = []
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
        # Pad raw text first, then colour — so terminal width calc stays correct
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


# ── Dispatch table ────────────────────────────────────────────────────────────

_COMMANDS = {
    "start":     cmd_start,
    "setup":     cmd_setup,
    "config":    cmd_config,
    "kanban":    cmd_kanban,
    "telegram":  cmd_telegram,
    "version":   cmd_version,
    "--version": cmd_version,
    "-v":        cmd_version,
    "uninstall": cmd_uninstall,
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

