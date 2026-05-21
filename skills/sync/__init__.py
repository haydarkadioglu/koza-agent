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

    if mode == "single":
        return "⚠ Multi-host is not enabled (mode=single). Run: koza sync setup"
    if mode == "master":
        return "ℹ This is the master host. Other clients sync to you. Use 'pull' if you want to receive from a remote master."
    if not master:
        return "✗ master_url not configured. Run: koza sync setup"
    if not token:
        return "✗ sync_token not configured. Run: koza sync setup"

    from .client import sync_pull, sync_push, sync_bidirectional_safe

    try:
        if direction == "pull":
            from .client import sync_pull
            counts = sync_pull(master, token, dbpath)
            total  = sum(counts.values())
            return f"✅ Pull complete — {total} rows merged\n{counts}"
        elif direction == "push":
            from .client import sync_push
            counts = sync_push(master, token, dbpath)
            total  = sum(counts.values())
            return f"✅ Push complete — {total} rows sent\n{counts}"
        else:
            return sync_bidirectional_safe(master, token, dbpath)
    except Exception as e:
        return f"✗ Sync error: {e}"


def sync_status() -> str:
    """Show current multi-host sync configuration and last sync info."""
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

    lines = [
        f"Multi-Host Sync Status",
        f"  Mode          : {mode}",
        f"  Host name     : {name}",
    ]
    if mode == "master":
        tok_display = ("*" * 8 + token[-4:]) if len(token) > 6 else (token or "—")
        lines.append(f"  Sync port     : {port}  (listening on 0.0.0.0:{port})")
        lines.append(f"  Token         : {tok_display}")
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

    return "\n".join(lines)


def list_hosts() -> str:
    """List configured hosts in multi-host mode."""
    from config import load_config
    cfg  = load_config()
    mh   = cfg.get("multi_host", {})
    mode = mh.get("mode", "single")

    if mode == "single":
        return "Single-host mode. Enable multi-host with: koza sync setup"
    if mode == "master":
        return (f"This is the MASTER host.\n"
                f"  Port   : {mh.get('sync_port', 7420)}\n"
                f"  Clients can connect by setting master_url in their config.\n"
                f"  Share your IP:port + token with clients.")
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
        "description": "Show current multi-host sync configuration and connectivity status.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_hosts",
        "description": "List configured hosts in multi-host mode.",
        "parameters": {"type": "object", "properties": {}},
    },
]

HANDLERS: dict = {
    "sync_now":     lambda direction="both": sync_now(direction),
    "sync_status":  lambda **_: sync_status(),
    "list_hosts":   lambda **_: list_hosts(),
}
