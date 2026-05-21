"""
Sync Server — runs on master host, exposes HTTP REST API for data synchronization.

Endpoints:
  GET  /api/sync/status         → host info + last sync time
  GET  /api/sync/pull           → JSON dump of all syncable tables
  POST /api/sync/push           → merge received JSON rows into local DB

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


def _dump_table(table: str, db_path: str) -> list[dict]:
    """Read all rows from a syncable table as list of dicts."""
    info = SYNCABLE_TABLES.get(table)
    if not info:
        return []
    cols = ", ".join(f'"{c}"' for c in info["columns"])
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
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

    def do_GET(self):
        if not self._auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        if self.path == "/api/sync/status":
            self._send_json(200, {
                "status":     "ok",
                "host_name":  _host_name,
                "db_path":    _db_path,
                "uptime_s":   round(time.time() - _started_at, 1),
                "tables":     list(SYNCABLE_TABLES.keys()),
                "server_time": time.time(),
            })
            return

        if self.path.startswith("/api/sync/pull"):
            # Optional ?tables=shared_memory,sessions
            tables_param = ""
            if "?" in self.path:
                qs = self.path.split("?", 1)[1]
                for part in qs.split("&"):
                    if part.startswith("tables="):
                        tables_param = part[7:]
            requested = [t.strip() for t in tables_param.split(",") if t.strip()] if tables_param else list(SYNCABLE_TABLES.keys())
            payload: dict[str, list] = {}
            for tbl in requested:
                if tbl in SYNCABLE_TABLES:
                    payload[tbl] = _dump_table(tbl, _db_path)
            self._send_json(200, {"data": payload, "pulled_at": time.time()})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        if self.path == "/api/sync/push":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                payload = json.loads(body.decode())
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid json"})
                return

            data    = payload.get("data", {})
            counts  = {}
            for table, rows in data.items():
                if table in SYNCABLE_TABLES and isinstance(rows, list):
                    counts[table] = _upsert_rows(table, rows, _db_path)
            self._send_json(200, {"merged": counts, "pushed_at": time.time()})
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

    try:
        _server_instance = HTTPServer(("0.0.0.0", port), _SyncHandler)
    except OSError as e:
        return False

    _server_thread = threading.Thread(target=_server_instance.serve_forever, daemon=True)
    _server_thread.start()
    return True


def stop_sync_server():
    """Stop the sync server."""
    global _server_instance
    if _server_instance:
        _server_instance.shutdown()
        _server_instance = None
