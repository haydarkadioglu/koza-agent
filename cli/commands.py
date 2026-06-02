"""Miscellaneous sub-commands."""
import sys

from cli.ui import _C, _hr, _config_path, _get_version, _select_menu, _prompt_secret
from cli.uninstall_cmd import cmd_uninstall   # noqa: F401
from cli.update_cmd import cmd_version, cmd_update  # noqa: F401
from cli.cmd_sync import cmd_sync             # noqa: F401

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
    print(_C("    • ~/.Koza/.env                (environment variable overrides)", "grey"))
    print(_C("    • ~/.Koza/koza.db             (tasks, memory, cron jobs)", "grey"))
    print(_C("    • ~/.Koza/daemon.*            (daemon PID / port files)", "grey"))
    print(_C("    • ~/.Koza/workspace/**        (empty files & empty folders)", "grey"))
    print(_C("    • ~/.koza-agent/.env          (install dir env overrides)\n", "grey"))
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
    install_dir = Path.home() / ".koza-agent"
    removed = []
    skipped = []
    for name in ["config.yaml", "koza.db", "daemon.pid", "daemon.port", "daemon.log", ".env"]:
        f = koza_dir / name
        if f.exists():
            try:
                f.unlink()
                removed.append(name)
            except PermissionError:
                skipped.append(name)
    # Also clear .env in install dir (load_dotenv picks it up on startup)
    install_env = install_dir / ".env"
    if install_env.exists():
        try:
            install_env.unlink()
            removed.append(f".koza-agent/.env")
        except PermissionError:
            skipped.append(f".koza-agent/.env")

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






def cmd_sessions(args: list) -> None:
    """Browse, load, or delete saved sessions. Usage: koza sessions [delete <id>]"""
    from config import load_config
    from skills.session_memory import get_session_rows, delete_session, init_db, load_session
    import time

    cfg = load_config()
    init_db(cfg["db_path"])

    # koza sessions load <id>
    if args and args[0] == "load":
        if len(args) < 2:
            print(_C("  ✗  Usage: koza sessions load <id>", "red"))
            return
        try:
            sid = int(args[1])
        except ValueError:
            print(_C(f"  ✗  Invalid session ID: {args[1]}", "red"))
            return
        if not load_session(sid):
            print(_C(f"  ✗  Session #{sid} not found or empty.", "red"))
            return
        from cli.daemon import cmd_start
        cmd_start(["--session", str(sid)])
        return

    # koza sessions delete <id>
    if args and args[0] == "delete":
        if len(args) < 2:
            print(_C("  ✗  Usage: koza sessions delete <id>", "red"))
            return
        try:
            sid = int(args[1])
        except ValueError:
            print(_C(f"  ✗  Invalid session ID: {args[1]}", "red"))
            return
        print(delete_session(sid))
        return

    rows = get_session_rows(limit=20)
    if not rows:
        print(_C("  ℹ  No saved sessions.", "grey"))
        return

    _hr()
    print(_C("  KOZA  ·  Saved Sessions", "bold", "yellow"))
    _hr()
    for r in rows:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["started"]))
        summary = f"  {_C(r['summary'][:70], 'grey')}" if r.get("summary") else ""
        rid = r["id"]
        print(f"  {_C(f'#{rid}', 'cyan')}  {_C(ts, 'grey')}  {r['title']}{summary}")
    print()

    labels = []
    for r in rows:
        ts = time.strftime("%m-%d %H:%M", time.localtime(r["started"]))
        labels.append(f"#{r['id']}  {ts}  {r['title'][:50]}")
    labels.append("— Cancel —")

    try:
        choice = _select_menu("Select session", labels, default_idx=len(labels) - 1)
    except (KeyboardInterrupt, EOFError):
        return

    if choice == "— Cancel —":
        return

    # Parse selected session id from label
    sid = int(choice.split()[0].lstrip("#"))

    try:
        action = _select_menu(f"Session #{sid}", ["Load (resume this session)", "Delete", "Cancel"], default_idx=0)
    except (KeyboardInterrupt, EOFError):
        return

    if action.startswith("Load"):
        msgs = load_session(sid)
        if not msgs:
            print(_C(f"  ✗  Session #{sid} not found or empty.", "red"))
            return
        user_msgs = [m for m in msgs if m.get("role") in ("user", "assistant")]
        print(_C(f"\n  ✓  Session #{sid} loaded ({len(user_msgs)} messages).", "green"))
        print(_C(f"  Start a chat with it:  koza sessions load {sid}", "grey"))
    elif action.startswith("Delete"):
        try:
            confirm = input(_C(f"  Delete session #{sid}? Type 'yes' to confirm: ", "red")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(_C("  Cancelled.", "grey"))
            return
        if confirm == "yes":
            print(delete_session(sid))
        else:
            print(_C("  Cancelled.", "grey"))


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
        ("tui",            "Start Textual cockpit UI"),
        ("setup",          "Configure provider, API keys, fallback"),
        ("config",         "Show current configuration"),
        ("provider",       "Switch active provider / model"),
        ("sessions",        "Browse, load or delete saved sessions"),
        ("kanban",         "Show Kanban board and cron jobs"),
        ("telegram",       "Configure Telegram bot token"),
        ("sync",           "Multi-host sync (status / pull / push / setup)"),
        ("status",         "Show daemon status"),
        ("quit",           "Stop Koza daemon"),
        ("update",         "Self-update Koza to the latest version"),
        ("version",        "Show Koza version (checks for updates)"),
        ("clean",          "Factory reset — remove all config & data"),
        ("uninstall",      "Remove ~/.Koza config and database"),
        ("help",           "Show this help"),
    ]
    for cmd, desc in cmds:
        print(f"    {_C(f'{cmd:<22}', 'cyan')}  {desc}")
    print(_C("\n  EXAMPLES\n", "bold"))
    examples = ["koza", "koza tui", "koza start --ui tui", "koza setup", "koza config", "koza sync status", "koza version"]
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
