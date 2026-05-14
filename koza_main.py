#!/usr/bin/env python3
"""Koza Agent — Entry point."""
import sys


# ── Sub-command handlers ──────────────────────────────────────────────────────

def cmd_start(args: list[str]) -> None:
    """Default: launch the TUI agent (or plain CLI with --plain)."""
    plain = "--plain" in args

    from config import load_config, config_exists
    if not config_exists():
        print("No config found. Running setup first...\n")
        cmd_setup([])

    cfg = load_config()

    from providers.factory import get_provider
    from core import Agent
    provider = get_provider(cfg)
    agent    = Agent(provider, db_path=cfg["db_path"], cfg=cfg)

    if plain:
        _plain_cli(agent, cfg)
    else:
        from tui.chat_app import ChatApp
        ChatApp(agent).run()


def cmd_setup(args: list[str]) -> None:
    """Interactive setup wizard — configure provider, API keys, etc."""
    from tui.setup_wizard import SetupWizard
    result = SetupWizard().run()
    if result is None:
        print("Setup cancelled.")
    else:
        from config import save_config
        save_config(result)
        print(f"✅ Config saved → {_config_path()}")


def cmd_config(args: list[str]) -> None:
    """Show current configuration (API keys masked)."""
    from config import load_config, config_exists
    if not config_exists():
        print("No config file found. Run:  koza setup")
        return

    cfg = load_config()
    print(f"Config file : {_config_path()}")
    print(f"DB path     : {cfg.get('db_path', '?')}")
    print(f"Provider    : {cfg.get('provider', '?')}")
    print(f"Model       : {cfg.get('model') or '(default)'}")
    print(f"Vault path  : {cfg.get('vault_path', '?')}")
    print()
    print("Providers:")
    for name, vals in cfg.get("providers", {}).items():
        key = vals.get("api_key") or vals.get("token", "")
        masked = ("*" * 6 + key[-4:]) if len(key) > 6 else ("set" if key else "—")
        base = vals.get("base_url", "")
        print(f"  {name:<12} key={masked:<16}  {base}")
    print()
    print("Messaging:")
    for plat, vals in cfg.get("messaging", {}).items():
        tok = vals.get("token") or vals.get("webhook_url") or vals.get("account_sid", "")
        status = "configured" if tok else "—"
        print(f"  {plat:<12} {status}")


def cmd_kanban(args: list[str]) -> None:
    """Open the interactive Kanban board."""
    from config import load_config
    cfg = load_config()
    from skills.kanban import init_db
    from skills.cron_db import init_db as cron_init
    init_db(cfg["db_path"])
    cron_init(cfg["db_path"])
    from tui.kanban_app import KanbanApp
    KanbanApp().run()


def cmd_uninstall(args: list[str]) -> None:
    """Remove config and database files from ~/.koza/."""
    import shutil
    from pathlib import Path
    Koza_dir = Path.home() / ".Koza"
    if not Koza_dir.exists():
        print("Nothing to remove — ~/.koza does not exist.")
        return
    answer = input(f"Remove {Koza_dir} (config + DB)? [y/N] ").strip().lower()
    if answer == "y":
        shutil.rmtree(Koza_dir)
        print(f"✅ Removed {Koza_dir}")
    else:
        print("Cancelled.")


def cmd_help(args: list[str]) -> None:
    """Print this help text."""
    print("""
Koza Agent — AI assistant with tools, memory, and TUI

USAGE
  koza [command] [options]

COMMANDS
  (none)       Start Koza TUI (default)
  start        Start Koza TUI
    --plain    Use plain terminal instead of TUI

  setup        Run setup wizard (providers, API keys)
  config       Show current configuration
  kanban       Open Kanban board
  uninstall    Remove ~/.koza config and database
  help         Show this help

EXAMPLES
  koza
  koza setup
  koza config
  koza kanban
  koza start --plain
  koza uninstall
""")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _config_path() -> str:
    from pathlib import Path
    return str(Path.home() / ".Koza" / "config.yaml")


def _plain_cli(agent, cfg: dict) -> None:
    print(f"Koza [{cfg['provider']} / {cfg.get('model') or 'default'}]")
    print("Commands: /reset  /kanban  /tasks  exit\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break
        if user_input == "/reset":
            agent.reset()
            print("Chat reset.\n")
            continue
        if user_input == "/kanban":
            from skills.kanban import list_tasks
            from skills.cron import list_crons
            print(list_tasks())
            print("\n--- CRON JOBS ---")
            print(list_crons())
            continue
        print("Koza: ", end="", flush=True)
        for token in agent.stream_chat(user_input):
            print(token, end="", flush=True)
        print("\n")


# ── Dispatch table ────────────────────────────────────────────────────────────

_COMMANDS = {
    "start":     cmd_start,
    "setup":     cmd_setup,
    "config":    cmd_config,
    "kanban":    cmd_kanban,
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
    rest    = argv[1:]

    handler = _COMMANDS.get(command)
    if handler:
        handler(rest)
    else:
        print(f"Unknown command: {command!r}")
        print("Run  koza help  for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()

