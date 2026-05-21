"""Multi-host sync command — koza sync [status|pull|push|now|setup]"""
import secrets

from cli.ui import _C, _hr, _select_menu, _prompt, _prompt_secret


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

    if not config_exists():
        print(_C("  ✗  No config found. Run:  koza setup", "red"))
        return

    cfg = load_config()
    sub = args[0] if args else "status"

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
        msg  = sync_bidirectional_safe(master, token, db)
        icon = "✅" if msg.startswith("Sync OK") else "⚠"
        print(_C(f"\n  {icon}  {msg}\n", "green" if icon == "✅" else "yellow"))
        return

    # ── setup ─────────────────────────────────────────────────────────────────
    if sub == "setup":
        _cmd_sync_setup(cfg)
        return

    print(_C(f"  ✗  Unknown subcommand: {sub}", "red"))
    print(_C("  Usage: koza sync [status|pull|push|now|setup]", "grey"))


def _cmd_sync_setup(cfg: dict) -> None:
    """Interactive wizard to configure multi-host sync."""
    from config import save_config

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
        _setup_master(mh, cfg)

    elif mode.startswith("client"):
        _setup_client(mh, cfg)

    elif mode.startswith("demo"):
        _setup_demo(mh, cfg)


def _setup_master(mh: dict, cfg: dict) -> None:
    from config import save_config
    mh["mode"] = "master"
    port_str   = _prompt("Sync port (clients will connect here)", default="7420")
    mh["sync_port"] = int(port_str) if port_str.isdigit() else 7420
    if mh.get("sync_token"):
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
    print(_C(f"    master_url: http://<your-ip>:{mh['sync_port']}", "grey"))
    print(_C(f"    sync_token: {mh['sync_token']}", "grey"))
    print(_C("\n  Make sure port is open in your firewall!\n", "grey"))
    _hr()


def _setup_client(mh: dict, cfg: dict) -> None:
    from config import save_config
    mh["mode"]       = "client"
    mh["master_url"] = _prompt("Master URL (e.g. http://192.168.1.10:7420)")
    while not mh["master_url"].strip():
        print(_C("  ✗  URL required.", "red"))
        mh["master_url"] = _prompt("Master URL")
    mh["sync_token"] = _prompt_secret("Sync token (from master)")
    while not mh["sync_token"].strip():
        print(_C("  ✗  Token required.", "red"))
        mh["sync_token"] = _prompt_secret("Sync token")
    on_start = _prompt("Sync on startup?",  default="y", choices=["y", "n"])
    on_exit  = _prompt("Sync on shutdown?", default="y", choices=["y", "n"])
    interval = _prompt("Auto-sync interval in minutes (0 = disabled)", default="5")
    mh["sync_on_startup"]       = (on_start.lower() == "y")
    mh["sync_on_exit"]          = (on_exit.lower()  == "y")
    mh["sync_interval_minutes"] = int(interval) if interval.isdigit() else 5
    mh["host_name"] = _prompt("Host name (optional)", default="")
    save_config(cfg)

    print(_C("\n  Testing connection to master…\n", "grey"))
    try:
        from skills.sync.client import check_master, sync_pull
        ok, msg = check_master(mh["master_url"], mh["sync_token"])
        if ok:
            print(_C(f"  ✅  {msg}\n", "green"))
            do_pull = _prompt("Pull data from master now?", default="y", choices=["y", "n"])
            if do_pull.lower() == "y":
                db     = cfg.get("db_path", "")
                counts = sync_pull(mh["master_url"], mh["sync_token"], db)
                total  = sum(counts.values())
                print(_C(f"  ✅  Pulled {total} rows from master.\n", "green"))
        else:
            print(_C(f"  ⚠  {msg}\n  (Config saved, verify connection later)\n", "yellow"))
    except Exception as e:
        print(_C(f"  ⚠  Connection test failed: {e}\n", "yellow"))
    _hr()


def _setup_demo(mh: dict, cfg: dict) -> None:
    from config import save_config
    mh["mode"]       = "demo"
    token            = secrets.token_hex(20)
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
