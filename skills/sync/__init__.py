"""
Sync skill — tools for multi-host data synchronization.

Exposes TOOL_DEFINITIONS and HANDLERS for tools/registry.py.
"""
import time


def sync_now(direction: str = "both") -> str:
    """
    Manually trigger a sync with the master host.
    direction: 'pull' | 'push' | 'both'
    """
    from config import load_config
    cfg    = load_config()
    mh     = cfg.get("multi_host", {})
    mode   = mh.get("mode", "single")
    master = mh.get("master_url", "").strip()
    token  = mh.get("sync_token", "").strip()
    dbpath = cfg.get("db_path", "")
    since  = float(mh.get("last_sync_at", 0) or 0)

    if mode == "single":
        return "⚠ Multi-host is not enabled (mode=single). Run: koza sync setup"
    if mode == "master":
        return "ℹ This is the master host. Other clients sync to you."
    if not master:
        return "✗ master_url not configured. Run: koza sync setup"
    if not token:
        return "✗ sync_token not configured. Run: koza sync setup"

    from .client import sync_pull, sync_push, sync_bidirectional_safe

    try:
        if direction == "pull":
            from .client import sync_pull
            counts = sync_pull(master, token, dbpath, since=since)
            total  = sum(counts.values())
            return f"✅ Pull complete — {total} rows merged\n{counts}"
        elif direction == "push":
            from .client import sync_push
            counts = sync_push(master, token, dbpath, since=since)
            total  = sum(counts.values())
            return f"✅ Push complete — {total} rows sent\n{counts}"
        else:
            return sync_bidirectional_safe(master, token, dbpath, since=since)
    except Exception as e:
        return f"✗ Sync error: {e}"


def sync_status() -> str:
    """Show current multi-host sync configuration, registered clients, and recent log."""
    from config import load_config
    cfg = load_config()
    mh  = cfg.get("multi_host", {})
    mode   = mh.get("mode", "single")
    master = mh.get("master_url", "—") or "—"
    port   = mh.get("sync_port", 7420)
    token  = mh.get("sync_token", "")
    name   = mh.get("host_name", "") or "(unnamed)"
    on_start  = mh.get("sync_on_startup", True)
    on_exit   = mh.get("sync_on_exit",    True)
    interval  = int(mh.get("sync_interval_minutes", 5))
    last_sync = mh.get("last_sync_at", 0)
    dbpath    = cfg.get("db_path", "")

    lines = [
        f"Multi-Host Sync Status",
        f"  Mode          : {mode}",
        f"  Host name     : {name}",
    ]
    if last_sync:
        import datetime
        dt = datetime.datetime.fromtimestamp(last_sync).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"  Last sync     : {dt}")

    if mode == "master":
        tok_display = ("*" * 8 + token[-4:]) if len(token) > 6 else (token or "—")
        from .server import is_running
        server_status = "✅ running" if is_running() else "❌ not running"
        lines.append(f"  Sync server   : {server_status} on 0.0.0.0:{port}")
        lines.append(f"  Token         : {tok_display}")

        # Registered clients
        try:
            from .server import get_registered_clients
            clients = get_registered_clients(dbpath)
            if clients:
                lines.append(f"  Clients ({len(clients)})   :")
                for c in clients:
                    import datetime
                    last = datetime.datetime.fromtimestamp(c["last_seen"]).strftime("%m-%d %H:%M")
                    lines.append(f"    • {c['host_name'] or c['id'][:8]}  {c['ip_addr']}  last:{last}")
            else:
                lines.append("  Clients       : none registered yet")
        except Exception:
            pass

    elif mode in ("client", "demo"):
        lines.append(f"  Master URL    : {master}")
        tok_display = ("*" * 8 + token[-4:]) if len(token) > 6 else (token or "—")
        lines.append(f"  Token         : {tok_display}")
        lines.append(f"  Sync on start : {on_start}")
        lines.append(f"  Sync on exit  : {on_exit}")
        lines.append(f"  Auto sync     : {'every ' + str(interval) + ' min' if interval > 0 else 'disabled'}")
    else:
        lines.append("  Multi-host disabled. Run: koza sync setup")

    # Ping master if client
    if mode in ("client", "demo") and master != "—":
        from .client import check_master
        ok, msg = check_master(master, token)
        status_icon = "✅" if ok else "⚠"
        lines.append(f"  Master status : {status_icon} {msg}")

    # Recent sync log
    try:
        from .server import get_sync_log
        log_entries = get_sync_log(dbpath, limit=5)
        if log_entries:
            lines.append("")
            lines.append("  Recent sync log:")
            for entry in log_entries:
                import datetime
                dt = datetime.datetime.fromtimestamp(entry["ts"]).strftime("%m-%d %H:%M")
                icon = "✅" if entry["status"] == "ok" else "❌"
                lines.append(f"    {icon} [{dt}] {entry['direction']:5} {entry['rows_synced']} rows — {entry['host_name']}")
    except Exception:
        pass

    return "\n".join(lines)


def list_hosts() -> str:
    """List configured hosts and registered clients in multi-host mode."""
    from config import load_config
    cfg  = load_config()
    mh   = cfg.get("multi_host", {})
    mode = mh.get("mode", "single")
    dbpath = cfg.get("db_path", "")

    if mode == "single":
        return "Single-host mode. Enable multi-host with: koza sync setup"

    if mode == "master":
        lines = [
            f"MASTER host — port {mh.get('sync_port', 7420)}",
            f"  Share your IP:port + token with clients.",
            "",
        ]
        try:
            from .server import get_registered_clients
            clients = get_registered_clients(dbpath)
            if clients:
                lines.append(f"  Registered clients ({len(clients)}):")
                for c in clients:
                    import datetime
                    last = datetime.datetime.fromtimestamp(c["last_seen"]).strftime("%Y-%m-%d %H:%M:%S")
                    first = datetime.datetime.fromtimestamp(c["first_seen"]).strftime("%Y-%m-%d")
                    lines.append(f"    • {c['host_name'] or c['id'][:8]}  IP:{c['ip_addr']}  last:{last}  since:{first}")
            else:
                lines.append("  No clients registered yet.")
                lines.append("  Clients register automatically on their first sync.")
        except Exception as e:
            lines.append(f"  (Could not read client list: {e})")
        return "\n".join(lines)

    master = mh.get("master_url", "")
    return (f"CLIENT mode — master: {master or '(not set)'}\n"
            f"Run sync_status() to check connectivity.")


TOOL_DEFINITIONS = [
    {
        "name": "sync_now",
        "description": (
            "Sync data with the master host (pull latest from master, push local changes). "
            "Use direction='pull' to only download, 'push' to only upload, 'both' for full sync. "
            "Only works when multi_host mode is 'client' or 'demo'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type":    "string",
                    "enum":    ["both", "pull", "push"],
                    "default": "both",
                    "description": "Sync direction",
                },
            },
            "required": [],
        },
    },
    {
        "name": "sync_status",
        "description": "Show current multi-host sync configuration, registered clients, server status, and recent sync log.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_hosts",
        "description": "List configured hosts and registered clients in multi-host mode.",
        "parameters": {"type": "object", "properties": {}},
    },
]

HANDLERS: dict = {
    "sync_now":     lambda direction="both": sync_now(direction),
    "sync_status":  lambda **_: sync_status(),
    "list_hosts":   lambda **_: list_hosts(),
}
