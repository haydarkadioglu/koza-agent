"""Miscellaneous sub-commands."""
import sys

from cli.ui import _C, _hr, _config_path, _get_version


def cmd_config(args: list) -> None:
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


def cmd_kanban(args: list) -> None:
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


def cmd_uninstall(args: list) -> None:
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


def cmd_telegram(args: list) -> None:
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


def cmd_version(args: list) -> None:
    """Print Koza version."""
    ver = _get_version()
    print(_C(f"\n  Koza  ", "bold", "yellow") + _C(f"v{ver}\n", "cyan"))


def cmd_help(args: list) -> None:
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
