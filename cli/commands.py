"""Miscellaneous sub-commands."""
import sys

from cli.ui import _C, _hr, _config_path, _get_version, _select_menu, _prompt_secret


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
    print(f"  {_C('Workspace  ', 'grey')}  :  {_C(str(cfg.get('workspace_path', '~/.Koza/workspace')), 'white')}")
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
    """Configure Telegram bot token. Once configured, the daemon runs it automatically."""
    from config import load_config, save_config, config_exists
    from cli.ui import _prompt_secret

    if not config_exists():
        print(_C("  ✗  No config found. Run: koza setup", "red"))
        return

    cfg = load_config()
    tg = cfg.setdefault("messaging", {}).setdefault("telegram", {})
    current_token = tg.get("token", "").strip()

    _hr()
    print(_C("\n  🤖  Koza Telegram Bot Setup\n", "bold", "cyan"))

    if current_token:
        masked = "*" * (len(current_token) - 6) + current_token[-6:]
        print(_C(f"  ✓  Token already configured:  {masked}", "green"))
        try:
            choice = _select_menu(
                "What do you want to do?",
                ["Keep current token", "Replace token", "Remove token (disable Telegram)"],
                default_idx=0,
            )
        except (KeyboardInterrupt, EOFError):
            return

        if choice == "Keep current token":
            print(_C("  No changes made.\n", "grey"))
            return
        elif choice == "Remove token (disable Telegram)":
            tg["token"] = ""
            tg["chat_id"] = ""
            save_config(cfg)
            print(_C("  ✓  Telegram disabled.\n", "green"))
            return

    print(_C("  1. Open Telegram → search @BotFather → /newbot", "grey"))
    print(_C("  2. Follow the steps and copy the bot token\n", "grey"))
    try:
        token = _prompt_secret("Paste bot token")
    except (KeyboardInterrupt, EOFError):
        return
    if not token:
        print(_C("  ✗  No token entered.\n", "red"))
        return

    tg["token"] = token
    save_config(cfg)

    _hr()
    print(_C("  ✓  Token saved.\n", "green"))
    print(_C("  The Telegram bot will start automatically next time Koza runs.", "teal"))
    print(_C("  To start it now, restart Koza (koza quit → koza).\n", "grey"))
    _hr()


def _clean_empty(root) -> tuple[int, int]:
    """Recursively delete empty files and empty directories. Returns (files_removed, dirs_removed)."""
    from pathlib import Path
    root = Path(root)
    files_removed = dirs_removed = 0
    if not root.exists():
        return 0, 0
    # Remove empty files
    for f in list(root.rglob("*")):
        if f.is_file() and f.stat().st_size == 0:
            try:
                f.unlink()
                files_removed += 1
            except Exception:
                pass
    # Remove empty dirs (bottom-up)
    for d in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            try:
                d.rmdir()
                dirs_removed += 1
            except Exception:
                pass
    return files_removed, dirs_removed


def cmd_clean(args: list) -> None:
    """Reset Koza to factory state — removes config, database, and daemon files."""
    import shutil
    from pathlib import Path
    from koza_daemon import get_daemon_port, PID_FILE, PORT_FILE, _cleanup

    _hr()
    print(_C("  ⚠   koza clean — Factory Reset\n", "red", "bold"))
    print(_C("  This will permanently delete:\n", "grey"))
    print(_C("    • ~/.Koza/config.yaml         (all provider keys & settings)", "grey"))
    print(_C("    • ~/.Koza/koza.db             (tasks, memory, cron jobs)", "grey"))
    print(_C("    • ~/.Koza/daemon.*            (daemon PID / port files)", "grey"))
    print(_C("    • ~/.Koza/workspace/**        (empty files & empty folders)\n", "grey"))
    print(_C("  The daemon will be stopped if running.\n", "grey"))

    try:
        answer = input(_C("  Type 'reset' to confirm: ", "red")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(_C("\n  Cancelled.\n", "grey"))
        return

    if answer != "reset":
        print(_C("  Cancelled.\n", "grey"))
        return

    # Stop daemon and wait a moment for it to release file handles
    port = get_daemon_port()
    if port:
        try:
            pid = int(PID_FILE.read_text().strip())
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.kernel32.TerminateProcess(
                    ctypes.windll.kernel32.OpenProcess(1, False, pid), 1
                )
            else:
                import signal as _sig
                import os as _os
                _os.kill(pid, _sig.SIGTERM)
            print(_C("  ✓  Daemon stopped.", "green"))
        except Exception:
            pass
        _cleanup()
        import time
        time.sleep(1)  # allow OS to release file handles before deletion

    # Remove files
    koza_dir = Path.home() / ".Koza"
    removed = []
    skipped = []
    for name in ["config.yaml", "koza.db", "daemon.pid", "daemon.port", "daemon.log"]:
        f = koza_dir / name
        if f.exists():
            try:
                f.unlink()
                removed.append(name)
            except PermissionError:
                skipped.append(name)

    if removed:
        print(_C(f"  ✓  Removed: {', '.join(removed)}", "green"))
    if skipped:
        print(_C(f"  ⚠  Could not delete (still in use): {', '.join(skipped)}", "yellow"))
        print(_C("     Close any open terminals using Koza and delete them manually.", "grey"))
    if not removed and not skipped:
        print(_C("  ℹ  Nothing to remove.", "grey"))

    # Clean empty files and folders in workspace
    ws = koza_dir / "workspace"
    if ws.exists():
        f_count, d_count = _clean_empty(ws)
        if f_count or d_count:
            print(_C(f"  ✓  Workspace: removed {f_count} empty file(s), {d_count} empty folder(s)", "green"))
        else:
            print(_C("  ℹ  Workspace: no empty files or folders found.", "grey"))

    _hr()
    print(_C("\n  ✅  Koza reset to factory defaults.\n", "green"))
    print(_C("  Run 'koza setup' to configure again.\n", "teal"))
    _hr()


def cmd_version(args: list) -> None:
    """Print Koza version."""
    ver = _get_version()
    print(_C(f"\n  Koza  ", "bold", "yellow") + _C(f"v{ver}\n", "cyan"))


def cmd_sync(args: list) -> None:
    """Multi-host sync management.

    Usage:
      koza sync             — show sync status
      koza sync status      — show sync status + ping master
      koza sync pull        — pull latest data from master
      koza sync push        — push local data to master
      koza sync now         — full bidirectional sync (pull + push)
      koza sync setup       — configure multi-host mode
    """
    from config import load_config, save_config, config_exists
    from cli.ui import _prompt, _prompt_secret, _select_menu

    if not config_exists():
        print(_C("  ✗  No config found. Run:  koza setup", "red"))
        return

    cfg  = load_config()
    sub  = args[0] if args else "status"

    # ── status ────────────────────────────────────────────────────────────────
    if sub in ("status", ""):
        from skills.sync import sync_status
        _hr()
        print(_C("\n  🔄  Koza Multi-Host Sync\n", "bold", "cyan"))
        print(sync_status())
        print()
        _hr()
        return

    # ── pull ──────────────────────────────────────────────────────────────────
    if sub == "pull":
        mh     = cfg.get("multi_host", {})
        master = mh.get("master_url", "").strip()
        token  = mh.get("sync_token", "").strip()
        db     = cfg.get("db_path", "")
        if not master or not token:
            print(_C("  ✗  master_url or sync_token not set. Run: koza sync setup", "red"))
            return
        try:
            from skills.sync.client import sync_pull
            counts = sync_pull(master, token, db)
            total  = sum(counts.values())
            _hr()
            print(_C(f"\n  ✅  Pull complete — {total} rows merged\n", "green"))
            for tbl, cnt in counts.items():
                print(f"  {_C(f'{tbl:<20}', 'cyan')}  {cnt} rows")
            print()
            _hr()
        except Exception as e:
            print(_C(f"  ✗  Pull failed: {e}", "red"))
        return

    # ── push ──────────────────────────────────────────────────────────────────
    if sub == "push":
        mh     = cfg.get("multi_host", {})
        master = mh.get("master_url", "").strip()
        token  = mh.get("sync_token", "").strip()
        db     = cfg.get("db_path", "")
        if not master or not token:
            print(_C("  ✗  master_url or sync_token not set. Run: koza sync setup", "red"))
            return
        try:
            from skills.sync.client import sync_push
            counts = sync_push(master, token, db)
            total  = sum(counts.values())
            _hr()
            print(_C(f"\n  ✅  Push complete — {total} rows sent\n", "green"))
            for tbl, cnt in counts.items():
                print(f"  {_C(f'{tbl:<20}', 'cyan')}  {cnt} rows")
            print()
            _hr()
        except Exception as e:
            print(_C(f"  ✗  Push failed: {e}", "red"))
        return

    # ── now (bidirectional) ───────────────────────────────────────────────────
    if sub == "now":
        mh     = cfg.get("multi_host", {})
        master = mh.get("master_url", "").strip()
        token  = mh.get("sync_token", "").strip()
        db     = cfg.get("db_path", "")
        if not master or not token:
            print(_C("  ✗  master_url or sync_token not set. Run: koza sync setup", "red"))
            return
        from skills.sync.client import sync_bidirectional_safe
        msg = sync_bidirectional_safe(master, token, db)
        icon = "✅" if msg.startswith("Sync OK") else "⚠"
        print(_C(f"\n  {icon}  {msg}\n", "green" if icon == "✅" else "yellow"))
        return

    # ── setup ─────────────────────────────────────────────────────────────────
    if sub == "setup":
        import secrets
        _hr()
        print(_C("\n  🔄  Multi-Host Sync Setup\n", "bold", "cyan"))
        print(_C("  Choose how this machine participates in multi-host sync:\n", "grey"))

        try:
            mode = _select_menu("Select mode", [
                "single    — no sync (default)",
                "master    — this machine holds the main data, others sync to it",
                "client    — this machine syncs from a master host",
                "demo      — same machine, two instances (for testing)",
            ], default_idx=0)
        except (KeyboardInterrupt, EOFError):
            return

        mh = cfg.setdefault("multi_host", {})

        if mode.startswith("single"):
            mh["mode"] = "single"
            save_config(cfg)
            print(_C("\n  ✅  Multi-host disabled.\n", "green"))

        elif mode.startswith("master"):
            mh["mode"] = "master"
            port_str  = _prompt("Sync port (clients will connect here)", default="7420")
            mh["sync_port"] = int(port_str) if port_str.isdigit() else 7420
            existing_token = mh.get("sync_token", "")
            if existing_token:
                keep = _prompt("Token already set. Keep it?", default="y", choices=["y", "n"])
                if keep.lower() != "y":
                    mh["sync_token"] = secrets.token_hex(20)
            else:
                mh["sync_token"] = secrets.token_hex(20)
            mh["host_name"] = _prompt("Host name (optional, e.g. 'home-pc')", default="")
            save_config(cfg)
            _hr()
            print(_C("\n  ✅  Master mode configured!\n", "green"))
            print(_C(f"  Token  : {_C(mh['sync_token'], 'yellow')}", "white"))
            print(_C(f"  Port   : {mh['sync_port']}", "white"))
            print(_C("\n  Share these with your client machines.\n", "grey"))
            print(_C("  Client config example:", "grey"))
            print(_C(f"    master_url: http://<your-ip>:{mh['sync_port']}", "grey"))
            print(_C(f"    sync_token: {mh['sync_token']}", "grey"))
            print(_C("\n  Make sure port is open in your firewall!\n", "grey"))
            _hr()

        elif mode.startswith("client"):
            mh["mode"]       = "client"
            mh["master_url"] = _prompt("Master URL (e.g. http://192.168.1.10:7420)")
            while not mh["master_url"].strip():
                print(_C("  ✗  URL required.", "red"))
                mh["master_url"] = _prompt("Master URL")
            mh["sync_token"] = _prompt_secret("Sync token (from master)")
            while not mh["sync_token"].strip():
                print(_C("  ✗  Token required.", "red"))
                mh["sync_token"] = _prompt_secret("Sync token")
            on_start = _prompt("Sync on startup?", default="y", choices=["y", "n"])
            on_exit  = _prompt("Sync on shutdown?", default="y", choices=["y", "n"])
            interval = _prompt("Auto-sync interval in minutes (0 = disabled)", default="5")
            mh["sync_on_startup"]        = (on_start.lower() == "y")
            mh["sync_on_exit"]           = (on_exit.lower()  == "y")
            mh["sync_interval_minutes"]  = int(interval) if interval.isdigit() else 5
            mh["host_name"] = _prompt("Host name (optional)", default="")
            save_config(cfg)

            # Test connection
            print(_C("\n  Testing connection to master…\n", "grey"))
            try:
                from skills.sync.client import check_master
                ok, msg = check_master(mh["master_url"], mh["sync_token"])
                if ok:
                    print(_C(f"  ✅  {msg}\n", "green"))
                    do_pull = _prompt("Pull data from master now?", default="y", choices=["y", "n"])
                    if do_pull.lower() == "y":
                        from skills.sync.client import sync_pull
                        db = cfg.get("db_path", "")
                        counts = sync_pull(mh["master_url"], mh["sync_token"], db)
                        total  = sum(counts.values())
                        print(_C(f"  ✅  Pulled {total} rows from master.\n", "green"))
                else:
                    print(_C(f"  ⚠  {msg}\n  (Config saved, but verify connection later)\n", "yellow"))
            except Exception as e:
                print(_C(f"  ⚠  Connection test failed: {e}\n", "yellow"))
            _hr()

        elif mode.startswith("demo"):
            mh["mode"]       = "demo"
            token = secrets.token_hex(20)
            mh["sync_token"] = token
            mh["master_url"] = "http://localhost:7421"
            mh["sync_port"]  = 7420
            save_config(cfg)
            _hr()
            print(_C("\n  ✅  Demo mode configured!\n", "green"))
            print(_C("  Run two Koza daemons on the same machine:\n", "grey"))
            print(_C("    Instance 1 (master):  set mode=master, sync_port=7421", "grey"))
            print(_C("    Instance 2 (client):  set mode=client, master_url=http://localhost:7421", "grey"))
            print(_C(f"\n  Shared token: {_C(token, 'yellow')}\n", "white"))
            _hr()
        return

    # Unknown subcommand
    print(_C(f"  ✗  Unknown subcommand: {sub}", "red"))
    print(_C("  Usage: koza sync [status|pull|push|now|setup]", "grey"))


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
        ("provider",       "Switch active provider / model"),
        ("kanban",         "Show Kanban board and cron jobs"),
        ("telegram",       "Configure Telegram bot token"),
        ("status",         "Show daemon status"),
        ("quit",           "Stop Koza daemon"),
        ("version",        "Show Koza version"),
        ("clean",          "Factory reset — remove all config & data"),
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
