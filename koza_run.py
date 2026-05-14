#!/usr/bin/env python3
"""Koza Agent — Entry point (plain CLI)."""
import sys

# ── ANSI colours (defined first so every function can use _C) ─────────────────
_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "yellow": "\033[93m", "gold": "\033[33m", "cyan": "\033[96m",
    "green": "\033[92m", "red": "\033[91m", "blue": "\033[94m",
    "white": "\033[97m", "grey": "\033[90m", "magenta": "\033[95m",
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
        print("No config found. Running setup first...\n")
        cmd_setup([])

    cfg = load_config()
    from providers.factory import get_provider
    from core import Agent
    provider = get_provider(cfg)
    agent = Agent(provider, db_path=cfg["db_path"], cfg=cfg)
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
    print(_C(f"  Options: {', '.join(PROVIDERS)}", "grey"))
    provider = _prompt("Provider", default="ollama", choices=PROVIDERS)

    default_model = PROVIDER_MODELS.get(provider, [""])[0]
    model = _prompt("Model", default=default_model)

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
        print(_C(f"  Options: {', '.join(remaining)}", "grey"))
        fallback_provider = _prompt("Fallback provider", choices=remaining)
        fallback_model = _prompt(
            "Fallback model",
            default=PROVIDER_MODELS.get(fallback_provider, [""])[0],
        )
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
    _print_banner(cfg)
    while True:
        try:
            user_input = input(_C("\n  You  › ", "cyan", "bold")).strip()
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
        print(_C("  Koza › ", "yellow", "bold"), end="", flush=True)
        for token in agent.stream_chat(user_input):
            print(token, end="", flush=True)
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
    print(_C(f"\n┌{bar}┐", "gold"))
    pad = max(0, term_w - 2 - len(header))
    print(_C(f"│{header}{' ' * pad}│", "gold"))
    print(_C(f"└{bar}┘", "gold"))

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
        print(f"{_C(padded, 'yellow')}  {panel_l}")

    # ── Tool count bar ───────────────────────────────────────────────────
    try:
        from tools.registry import ALL_TOOLS
        n_tools = len(ALL_TOOLS)
    except Exception:
        n_tools = 0
    n_cats = len(_TOOL_CATEGORIES)
    summary = f"  {n_tools} tools · {n_cats} categories · type /help for commands"
    print(_C("─" * term_w, "gold"))
    print(_C(summary, "grey"))
    print(_C("─" * term_w, "gold"))
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


if __name__ == "__main__":
    main()

