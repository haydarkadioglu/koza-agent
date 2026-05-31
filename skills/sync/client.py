"""
Sync Client — connects to master's sync server to pull/push data.

Used by client-mode hosts to stay in sync with the master.
"""
import json
import time
import uuid
from pathlib import Path
from typing import Optional

import requests

from .server import SYNCABLE_TABLES, _dump_table, _upsert_rows, _ensure_clients_table, _append_sync_log

_TIMEOUT = 15  # seconds per HTTP request


def _headers(token: str) -> dict:
    return {"X-Koza-Token": token, "Content-Type": "application/json"}


def _get_client_id(db_path: str) -> str:
    """Return a stable client ID stored in the local DB (auto-creates if missing)."""
    _ensure_clients_table(db_path)
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, check_same_thread=False)
        row = conn.execute(
            "SELECT value FROM sync_clients WHERE id = '__self__' LIMIT 1"
        ).fetchone()
        if row:
            conn.close()
            return row[0]
        # Generate a new client ID
        new_id = str(uuid.uuid4())
        conn.execute(
            "INSERT OR IGNORE INTO sync_clients (id, host_name, ip_addr, last_seen, first_seen) VALUES (?, ?, '', ?, ?)",
            ("__self__", new_id, time.time(), time.time())
        )
        conn.commit()
        conn.close()
        return new_id
    except Exception:
        return str(uuid.uuid4())


def _save_last_sync_at(ts: float) -> None:
    """Persist last_sync_at into config so next sync can use it."""
    try:
        from config import load_config, save_config
        cfg = load_config()
        cfg.setdefault("multi_host", {})["last_sync_at"] = ts
        save_config(cfg)
    except Exception:
        pass


def check_master(master_url: str, token: str) -> tuple[bool, str]:
    """
    Ping master's /api/sync/status.
    Returns (reachable: bool, message: str).
    """
    url = master_url.rstrip("/") + "/api/sync/status"
    try:
        r = requests.get(url, headers=_headers(token), timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            n_clients = len(data.get("clients", []))
            return True, (f"Master OK — host={data.get('host_name','?')} "
                          f"uptime={data.get('uptime_s','?')}s "
                          f"clients={n_clients}")
        elif r.status_code == 401:
            return False, "Authentication failed — check your sync_token"
        else:
            return False, f"Master returned HTTP {r.status_code}"
    except requests.ConnectionError:
        return False, f"Cannot reach master at {master_url}"
    except Exception as e:
        return False, f"Error: {e}"


def register_with_master(master_url: str, token: str, db_path: str, host_name: str = "") -> bool:
    """
    Register this client with the master.
    Returns True on success.
    """
    client_id = _get_client_id(db_path)
    url = master_url.rstrip("/") + "/api/sync/register"
    try:
        payload = json.dumps({
            "client_id": client_id,
            "host_name": host_name or "koza-client",
        }).encode()
        r = requests.post(url, headers=_headers(token), data=payload, timeout=_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def sync_pull(master_url: str, token: str, db_path: str,
              tables: Optional[list[str]] = None,
              since: float = 0.0) -> dict[str, int]:
    """
    Pull tables from master and merge into local DB.
    If since > 0, only fetch rows updated after that timestamp.
    Returns dict of {table: rows_merged}.
    """
    # Heartbeat: register with master on every sync to keep last_seen current
    try:
        register_with_master(master_url, token, db_path)
    except Exception:
        pass

    tables = tables or list(SYNCABLE_TABLES.keys())
    qs = "tables=" + ",".join(tables)
    if since > 0:
        qs += f"&since={since}"
    url = master_url.rstrip("/") + f"/api/sync/pull?{qs}"
    try:
        r = requests.get(url, headers=_headers(token), timeout=_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except requests.ConnectionError as e:
        raise ConnectionError(f"Cannot reach master: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Pull failed: {e}") from e

    data   = payload.get("data", {})
    counts = {}
    for table, rows in data.items():
        if isinstance(rows, list):
            counts[table] = _upsert_rows(table, rows, db_path)
    _append_sync_log("pull", master_url, sum(counts.values()), "ok", "", db_path)
    return counts


def sync_push(master_url: str, token: str, db_path: str,
              tables: Optional[list[str]] = None,
              since: float = 0.0) -> dict[str, int]:
    """
    Push local tables to master for merging.
    If since > 0, only send rows updated after that timestamp.
    Returns dict of {table: rows_sent} from master's response.
    """
    tables  = tables or list(SYNCABLE_TABLES.keys())
    payload = {"data": {}}
    for table in tables:
        payload["data"][table] = _dump_table(table, db_path, since=since)

    url = master_url.rstrip("/") + "/api/sync/push"
    try:
        r = requests.post(url, headers=_headers(token),
                          data=json.dumps(payload, ensure_ascii=False).encode(),
                          timeout=_TIMEOUT)
        r.raise_for_status()
        merged = r.json().get("merged", {})
        _append_sync_log("push", master_url, sum(merged.values()), "ok", "", db_path)
        return merged
    except requests.ConnectionError as e:
        raise ConnectionError(f"Cannot reach master: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Push failed: {e}") from e


def sync_pull_config(master_url: str, token: str) -> dict:
    """
    Pull credential config from master and merge into local config.
    Only syncs providers, messaging tokens, and social keys.
    Returns the merged config dict (keys that were updated).
    """
    url = master_url.rstrip("/") + "/api/sync/config"
    try:
        r = requests.get(url, headers=_headers(token), timeout=_TIMEOUT)
        r.raise_for_status()
        remote_cfg = r.json().get("config", {})
    except requests.ConnectionError as e:
        raise ConnectionError(f"Cannot reach master: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Config pull failed: {e}") from e

    if not remote_cfg:
        return {}

    try:
        from config import load_config, save_config
        local = load_config()
        _deep_merge_config(local, remote_cfg)
        save_config(local)
        return remote_cfg
    except Exception as e:
        raise RuntimeError(f"Config save failed: {e}") from e


def _deep_merge_config(base: dict, overlay: dict) -> None:
    """Recursively merge overlay into base dict (in-place). Never overwrites with empty values."""
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge_config(base[key], val)
        elif val not in (None, "", [], {}):
            base[key] = val


def sync_bidirectional(master_url: str, token: str, db_path: str,
                       tables: Optional[list[str]] = None,
                       since: float = 0.0,
                       sync_config: bool = True) -> dict:
    """
    Pull then push — full bidirectional sync.
    If sync_config=True, also pulls credentials from master config.
    Returns summary dict.
    """
    pulled = sync_pull(master_url, token, db_path, tables, since=since)
    pushed = sync_push(master_url, token, db_path, tables, since=since)
    config_synced = False
    if sync_config:
        try:
            merged = sync_pull_config(master_url, token)
            config_synced = bool(merged)
        except Exception:
            pass
    synced_at = time.time()
    _save_last_sync_at(synced_at)
    return {"pulled": pulled, "pushed": pushed, "synced_at": synced_at, "config_synced": config_synced}


def sync_bidirectional_safe(master_url: str, token: str, db_path: str,
                             since: float = 0.0,
                             sync_config: bool = True) -> str:
    """
    Same as sync_bidirectional but catches all errors and returns human-readable string.
    Safe to call from daemon startup/shutdown.
    """
    try:
        result = sync_bidirectional(master_url, token, db_path, since=since, sync_config=sync_config)
        pulled_total = sum(result["pulled"].values())
        pushed_total = sum(result["pushed"].values())
        mode = "(delta)" if since > 0 else "(full)"
        cfg_note = " +config" if result.get("config_synced") else ""
        return f"Sync OK {mode}{cfg_note} — pulled {pulled_total} rows, pushed {pushed_total} rows"
    except ConnectionError as e:
        return f"Sync skipped (master unreachable): {e}"
    except Exception as e:
        return f"Sync error: {e}"


# ── Remote task execution ─────────────────────────────────────────────────────

def fetch_pending_tasks(master_url: str, token: str, host_name: str) -> list[dict]:
    """Fetch tasks assigned to this client from master."""
    url = master_url.rstrip("/") + f"/api/sync/tasks/pending?host_name={host_name}"
    try:
        r = requests.get(url, headers=_headers(token), timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json().get("tasks", [])
    except Exception:
        return []


def submit_task_result(master_url: str, token: str, task_id: str, result: str, error: str = "") -> bool:
    """Post task result back to master."""
    url = master_url.rstrip("/") + f"/api/sync/task/{task_id}/result"
    try:
        payload = json.dumps({"result": result, "error": error}).encode()
        r = requests.post(url, headers=_headers(token), data=payload, timeout=_TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def process_pending_tasks(master_url: str, token: str, db_path: str, host_name: str) -> int:
    """
    Fetch pending tasks from master, execute each via the local agent, and post results back.
    Returns number of tasks processed.
    """
    tasks = fetch_pending_tasks(master_url, token, host_name)
    if not tasks:
        return 0

    processed = 0
    for task in tasks:
        task_id   = task.get("id", "")
        task_text = task.get("task_text", "")
        if not task_id or not task_text:
            continue
        try:
            from config import load_config
            cfg = load_config()
            from providers.factory import get_provider
            from core import Agent
            agent = Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg, channel="remote_task")
            result = agent.chat(task_text)
            submit_task_result(master_url, token, task_id, result or "")
        except Exception as e:
            submit_task_result(master_url, token, task_id, "", error=str(e))
        processed += 1

    return processed
