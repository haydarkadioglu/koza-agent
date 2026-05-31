"""
Sync Server — runs on master host, exposes HTTP REST API for data synchronization.

Endpoints:
  GET  /api/sync/status          → host info + last sync time + registered clients
  GET  /api/sync/pull            → JSON dump of syncable tables (since=<ts> for delta)
  POST /api/sync/push            → merge received JSON rows into local DB
  POST /api/sync/register        → client registration (host_name, client_id)

Auth: X-Koza-Token header (shared secret, set in config multi_host.sync_token)
"""
import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional


# ── Tables that are synced ────────────────────────────────────────────────────

SYNCABLE_TABLES = {
    "shared_memory": {
        "pk":      "key",
        "ts_col":  "updated_at",
        "columns": ["key", "value", "tags", "source", "created_at", "updated_at"],
        "upsert":  """INSERT INTO shared_memory (key, value, tags, source, created_at, updated_at)
                      VALUES (:key, :value, :tags, :source, :created_at, :updated_at)
                      ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value, tags=excluded.tags, source=excluded.source,
                        updated_at=excluded.updated_at
                      WHERE excluded.updated_at >= shared_memory.updated_at""",
    },
    "sessions": {
        "pk":      "id",
        "ts_col":  "started",
        "columns": ["id", "title", "started", "ended", "messages", "summary"],
        "upsert":  """INSERT OR REPLACE INTO sessions (id, title, started, ended, messages, summary)
                      VALUES (:id, :title, :started, :ended, :messages, :summary)""",
    },
    "kanban_tasks": {
        "pk":      "id",
        "ts_col":  "updated_at",
        "columns": ["id", "title", "description", "column", "created_at", "updated_at"],
        "upsert":  """INSERT INTO kanban_tasks (id, title, description, "column", created_at, updated_at)
                      VALUES (:id, :title, :description, :column, :created_at, :updated_at)
                      ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title, description=excluded.description,
                        "column"=excluded."column", updated_at=excluded.updated_at
                      WHERE excluded.updated_at >= kanban_tasks.updated_at""",
    },
    "working_memory": {
        "pk":      "id",
        "ts_col":  "ts",
        "columns": ["id", "event_type", "summary", "detail", "ts"],
        "upsert":  """INSERT OR IGNORE INTO working_memory (id, event_type, summary, detail, ts)
                      VALUES (:id, :event_type, :summary, :detail, :ts)""",
    },
}

_server_instance: Optional[HTTPServer] = None
_server_thread:   Optional[threading.Thread] = None
_db_path:  str = ""
_token:    str = ""
_host_name: str = ""
_started_at: float = 0.0


# ── Client registry (in-memory, mirrored to DB) ───────────────────────────────

def _ensure_clients_table(db_path: str) -> None:
    """Create sync_clients, sync_log, and sync_tasks tables if they don't exist."""
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_clients (
                id        TEXT PRIMARY KEY,
                host_name TEXT,
                ip_addr   TEXT,
                last_seen REAL,
                first_seen REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                direction    TEXT,
                host_name    TEXT,
                rows_synced  INTEGER DEFAULT 0,
                status       TEXT DEFAULT 'ok',
                error        TEXT DEFAULT '',
                ts           REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_tasks (
                id            TEXT PRIMARY KEY,
                target_host   TEXT,
                task_text     TEXT,
                status        TEXT DEFAULT 'pending',
                created_at    REAL,
                claimed_at    REAL,
                completed_at  REAL,
                result        TEXT DEFAULT '',
                error         TEXT DEFAULT ''
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _register_client(client_id: str, host_name: str, ip_addr: str, db_path: str) -> None:
    """Upsert a client record into sync_clients."""
    now = time.time()
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("""
            INSERT INTO sync_clients (id, host_name, ip_addr, last_seen, first_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                host_name=excluded.host_name,
                ip_addr=excluded.ip_addr,
                last_seen=excluded.last_seen
        """, (client_id, host_name, ip_addr, now, now))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _append_sync_log(direction: str, host_name: str, rows: int,
                     status: str, error: str, db_path: str) -> None:
    """Write a sync_log entry."""
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("""
            INSERT INTO sync_log (direction, host_name, rows_synced, status, error, ts)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (direction, host_name, rows, status, error, time.time()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_registered_clients(db_path: str) -> list[dict]:
    """Return all registered clients as list of dicts."""
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, host_name, ip_addr, last_seen, first_seen FROM sync_clients ORDER BY last_seen DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_sync_log(db_path: str, limit: int = 10) -> list[dict]:
    """Return recent sync log entries."""
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM sync_log ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ── Remote task helpers ───────────────────────────────────────────────────────

def create_task(target_host: str, task_text: str, db_path: str) -> str:
    """Insert a new remote task. Returns the task ID."""
    import uuid as _uuid
    task_id = str(_uuid.uuid4())
    now = time.time()
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("""
            INSERT INTO sync_tasks (id, target_host, task_text, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
        """, (task_id, target_host, task_text, now))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return task_id


def get_pending_tasks(host_name: str, db_path: str) -> list[dict]:
    """Return pending tasks for a given host (or wildcard '*')."""
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM sync_tasks
            WHERE status = 'pending'
              AND (target_host = ? OR target_host = '*')
            ORDER BY created_at ASC
        """, (host_name,)).fetchall()
        # Mark as claimed
        for r in rows:
            conn.execute(
                "UPDATE sync_tasks SET status='running', claimed_at=? WHERE id=?",
                (time.time(), r["id"])
            )
        conn.commit()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def update_task_result(task_id: str, result: str, error: str, db_path: str) -> None:
    """Store the result of a completed task."""
    status = "error" if error else "done"
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("""
            UPDATE sync_tasks
            SET status=?, result=?, error=?, completed_at=?
            WHERE id=?
        """, (status, result, error, time.time(), task_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_task_results(db_path: str, limit: int = 20) -> list[dict]:
    """Return recent tasks with their results."""
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, target_host, task_text, status, created_at, completed_at, result, error
            FROM sync_tasks ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _dump_table(table: str, db_path: str, since: float = 0.0) -> list[dict]:
    """Read rows from a syncable table as list of dicts.
    If since > 0, only return rows updated after that timestamp.
    """
    info = SYNCABLE_TABLES.get(table)
    if not info:
        return []
    cols = ", ".join(f'"{c}"' for c in info["columns"])
    ts_col = info["ts_col"]
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            if since > 0:
                rows = conn.execute(
                    f'SELECT {cols} FROM {table} WHERE "{ts_col}" > ?', (since,)
                ).fetchall()
            else:
                rows = conn.execute(f"SELECT {cols} FROM {table}").fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []  # table may not exist yet
        finally:
            conn.close()
    except Exception:
        return []


def _upsert_rows(table: str, rows: list[dict], db_path: str) -> int:
    """Merge incoming rows into local table. Returns count of rows processed."""
    info = SYNCABLE_TABLES.get(table)
    if not info or not rows:
        return 0
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            for row in rows:
                # Only pass known columns to avoid injection
                filtered = {c: row.get(c) for c in info["columns"]}
                conn.execute(info["upsert"], filtered)
            conn.commit()
            return len(rows)
        except Exception:
            conn.rollback()
            return 0
        finally:
            conn.close()
    except Exception:
        return 0


def _extract_syncable_config(cfg: dict) -> dict:
    """
    Extract only the credential/token fields that should be synced to clients.
    Deliberately excludes local-machine paths and device-specific settings.
    """
    synced: dict = {}

    # ── LLM provider API keys ─────────────────────────────────────────────────
    providers = cfg.get("providers", {})
    synced_providers: dict = {}
    for pname, pvals in providers.items():
        entry: dict = {}
        if pvals.get("api_key"):
            entry["api_key"] = pvals["api_key"]
        if pvals.get("token"):
            entry["token"] = pvals["token"]
        if pvals.get("base_url"):
            entry["base_url"] = pvals["base_url"]
        if pvals.get("auth"):
            entry["auth"] = pvals["auth"]
        if entry:
            synced_providers[pname] = entry
    if synced_providers:
        synced["providers"] = synced_providers

    # ── Active provider / model ───────────────────────────────────────────────
    for key in ("provider", "model", "fallback_provider", "fallback_model", "media_provider"):
        if cfg.get(key):
            synced[key] = cfg[key]

    # ── Messaging tokens ──────────────────────────────────────────────────────
    messaging = cfg.get("messaging", {})
    synced_messaging: dict = {}
    for channel, vals in messaging.items():
        if isinstance(vals, dict) and any(vals.values()):
            synced_messaging[channel] = {k: v for k, v in vals.items() if v}
    if synced_messaging:
        synced["messaging"] = synced_messaging

    # telegram_token flat key
    if cfg.get("telegram_token"):
        synced["telegram_token"] = cfg["telegram_token"]

    # ── Social tokens ─────────────────────────────────────────────────────────
    social = cfg.get("social", {})
    synced_social = {k: v for k, v in social.items() if v}
    if synced_social:
        synced["social"] = synced_social

    return synced


class _SyncHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the sync REST API."""

    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def _auth(self) -> bool:
        return self.headers.get("X-Koza-Token", "") == _token

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parse_qs(self) -> dict:
        """Parse query string from self.path into a dict."""
        qs: dict = {}
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    qs[k] = v
        return qs

    def do_GET(self):
        if not self._auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        path = self.path.split("?")[0]

        if path == "/api/sync/status":
            clients = get_registered_clients(_db_path)
            recent_log = get_sync_log(_db_path, limit=5)
            self._send_json(200, {
                "status":      "ok",
                "host_name":   _host_name,
                "db_path":     _db_path,
                "uptime_s":    round(time.time() - _started_at, 1),
                "tables":      list(SYNCABLE_TABLES.keys()),
                "server_time": time.time(),
                "clients":     clients,
                "recent_log":  recent_log,
            })
            return

        if path == "/api/sync/pull":
            qs = self._parse_qs()
            tables_param = qs.get("tables", "")
            since = float(qs.get("since", "0") or "0")
            requested = (
                [t.strip() for t in tables_param.split(",") if t.strip()]
                if tables_param else list(SYNCABLE_TABLES.keys())
            )
            payload: dict[str, list] = {}
            total_rows = 0
            for tbl in requested:
                if tbl in SYNCABLE_TABLES:
                    rows = _dump_table(tbl, _db_path, since=since)
                    payload[tbl] = rows
                    total_rows += len(rows)
            client_ip = self.client_address[0]
            _append_sync_log("pull", client_ip, total_rows, "ok", "", _db_path)
            self._send_json(200, {"data": payload, "pulled_at": time.time()})
            return

        if path == "/api/sync/config":
            # Return syncable credentials from master's config
            try:
                from config import load_config
                cfg = load_config()
            except Exception as e:
                self._send_json(500, {"error": f"config load failed: {e}"})
                return
            self._send_json(200, {
                "config":    _extract_syncable_config(cfg),
                "pulled_at": time.time(),
            })
            return

        if path == "/api/sync/tasks/pending":
            # Client polls for pending tasks assigned to its host
            qs = self._parse_qs()
            host_name = qs.get("host_name", "")
            tasks = get_pending_tasks(host_name, _db_path)
            self._send_json(200, {"tasks": tasks})
            return

        if path == "/api/sync/tasks":
            # Return all tasks (for master to inspect results)
            tasks = get_task_results(_db_path)
            self._send_json(200, {"tasks": tasks})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        path = self.path.split("?")[0]

        if path == "/api/sync/register":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                payload = json.loads(body.decode())
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid json"})
                return
            client_id = payload.get("client_id", "")
            host_name = payload.get("host_name", "unknown")
            client_ip = self.client_address[0]
            if client_id:
                _register_client(client_id, host_name, client_ip, _db_path)
            self._send_json(200, {
                "registered": True,
                "host_name":  _host_name,
                "server_time": time.time(),
            })
            return

        if path == "/api/sync/push":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                payload = json.loads(body.decode())
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid json"})
                return

            data    = payload.get("data", {})
            counts  = {}
            total   = 0
            for table, rows in data.items():
                if table in SYNCABLE_TABLES and isinstance(rows, list):
                    counts[table] = _upsert_rows(table, rows, _db_path)
                    total += counts[table]
            client_ip = self.client_address[0]
            _append_sync_log("push", client_ip, total, "ok", "", _db_path)
            self._send_json(200, {"merged": counts, "pushed_at": time.time()})
            return

        if path == "/api/sync/task":
            # Master creates a task for a client: {target_host, task_text}
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                payload = json.loads(body.decode())
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid json"})
                return
            target = payload.get("target_host", "*")
            task_text = payload.get("task_text", "")
            if not task_text:
                self._send_json(400, {"error": "task_text required"})
                return
            task_id = create_task(target, task_text, _db_path)
            self._send_json(200, {"task_id": task_id, "target_host": target})
            return

        if path.startswith("/api/sync/task/") and path.endswith("/result"):
            # Client posts result: /api/sync/task/<id>/result
            task_id = path.split("/")[4]
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                payload = json.loads(body.decode())
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid json"})
                return
            update_task_result(task_id, payload.get("result", ""), payload.get("error", ""), _db_path)
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"error": "not found"})


def start_sync_server(db_path: str, token: str, port: int = 7420, host_name: str = "") -> bool:
    """Start the sync HTTP server in a daemon thread. Returns True on success."""
    global _server_instance, _server_thread, _db_path, _token, _host_name, _started_at

    if _server_instance is not None:
        return True  # already running

    _db_path   = db_path
    _token     = token
    _host_name = host_name or "koza-master"
    _started_at = time.time()

    _ensure_clients_table(db_path)

    try:
        _server_instance = HTTPServer(("0.0.0.0", port), _SyncHandler)
    except OSError as e:
        return False

    _server_thread = threading.Thread(target=_server_instance.serve_forever, daemon=True)
    _server_thread.start()
    return True


def is_running() -> bool:
    """Return True if the sync server is currently running."""
    return _server_instance is not None


def stop_sync_server():
    """Stop the sync server."""
    global _server_instance
    if _server_instance:
        _server_instance.shutdown()
        _server_instance = None
