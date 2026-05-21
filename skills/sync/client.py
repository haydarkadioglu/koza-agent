"""
Sync Client — connects to master's sync server to pull/push data.

Used by client-mode hosts to stay in sync with the master.
"""
import json
import time
from typing import Optional

import requests

from .server import SYNCABLE_TABLES, _dump_table, _upsert_rows

_TIMEOUT = 15  # seconds per HTTP request


def _headers(token: str) -> dict:
    return {"X-Koza-Token": token, "Content-Type": "application/json"}


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
            return True, f"Master OK — host={data.get('host_name','?')} uptime={data.get('uptime_s','?')}s"
        elif r.status_code == 401:
            return False, "Authentication failed — check your sync_token"
        else:
            return False, f"Master returned HTTP {r.status_code}"
    except requests.ConnectionError:
        return False, f"Cannot reach master at {master_url}"
    except Exception as e:
        return False, f"Error: {e}"


def sync_pull(master_url: str, token: str, db_path: str,
              tables: Optional[list[str]] = None) -> dict[str, int]:
    """
    Pull all tables from master and merge into local DB.
    Returns dict of {table: rows_merged}.
    """
    tables = tables or list(SYNCABLE_TABLES.keys())
    url    = master_url.rstrip("/") + "/api/sync/pull?tables=" + ",".join(tables)
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
    return counts


def sync_push(master_url: str, token: str, db_path: str,
              tables: Optional[list[str]] = None) -> dict[str, int]:
    """
    Push local tables to master for merging.
    Returns dict of {table: rows_sent} from master's response.
    """
    tables  = tables or list(SYNCABLE_TABLES.keys())
    payload = {"data": {}}
    for table in tables:
        payload["data"][table] = _dump_table(table, db_path)

    url = master_url.rstrip("/") + "/api/sync/push"
    try:
        r = requests.post(url, headers=_headers(token),
                          data=json.dumps(payload, ensure_ascii=False).encode(),
                          timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json().get("merged", {})
    except requests.ConnectionError as e:
        raise ConnectionError(f"Cannot reach master: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Push failed: {e}") from e


def sync_bidirectional(master_url: str, token: str, db_path: str,
                       tables: Optional[list[str]] = None) -> dict:
    """
    Pull then push — full bidirectional sync.
    Returns summary dict.
    """
    pulled = sync_pull(master_url, token, db_path, tables)
    pushed = sync_push(master_url, token, db_path, tables)
    return {"pulled": pulled, "pushed": pushed, "synced_at": time.time()}


def sync_bidirectional_safe(master_url: str, token: str, db_path: str) -> str:
    """
    Same as sync_bidirectional but catches all errors and returns human-readable string.
    Safe to call from daemon startup/shutdown.
    """
    try:
        result = sync_bidirectional(master_url, token, db_path)
        pulled_total = sum(result["pulled"].values())
        pushed_total = sum(result["pushed"].values())
        return f"Sync OK — pulled {pulled_total} rows, pushed {pushed_total} rows"
    except ConnectionError as e:
        return f"Sync skipped (master unreachable): {e}"
    except Exception as e:
        return f"Sync error: {e}"
