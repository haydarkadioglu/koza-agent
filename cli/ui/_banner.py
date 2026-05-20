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
            import re
            # cli/ui/_banner.py → project root is 3 parents up
            toml = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text()
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

    header = f" Koza Agent v{ver} ({today}) · {provider} / {model} "
    if fallback:
        header += f"· fallback: {fallback} "
    bar = "─" * max(0, term_w - 2)
    print(_C(f"\n┌{bar}┐", "teal"))
    pad = max(0, term_w - 2 - len(header))
    print(_C(f"│{header}{' ' * pad}│", "teal"))
    print(_C(f"└{bar}┘", "teal"))

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

    height = max(len(logo_lines), len(panel_lines))
    logo_lines += [""] * (height - len(logo_lines))
    panel_lines += [""] * (height - len(panel_lines))

    for logo_l, panel_l in zip(logo_lines, panel_lines):
        padded = f"  {logo_l:<{logo_w}}"
        print(f"{_C(padded, 'teal')}  {panel_l}")

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
