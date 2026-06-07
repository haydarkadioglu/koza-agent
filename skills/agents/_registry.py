"""Shared sub-agent registry (module-level singleton)."""
import json
import sqlite3
import threading
import time
from pathlib import Path

# Thread-safe cancel events in memory (since we can't serialize Event to SQLite)
_cancel_events: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()
_registry_lock = threading.RLock()


class AgentEntryProxy(dict):
    """A proxy dictionary that writes any mutations back to SQLite."""

    def __init__(self, agent_id, initial_dict, proxy_parent):
        super().__init__(initial_dict)
        self.agent_id = agent_id
        self.proxy_parent = proxy_parent

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if key == "_cancel":
            with _cancel_lock:
                _cancel_events[self.agent_id] = value
            return

        # Serialize fields if needed
        db_val = value
        if key in ("messages", "capabilities"):
            db_val = json.dumps(value, ensure_ascii=False)

        # Update SQLite
        with self.proxy_parent._conn() as conn:
            conn.execute(
                f"UPDATE subagents SET {key} = ? WHERE id = ?",
                (db_val, self.agent_id),
            )
            conn.commit()


class SQLiteRegistryProxy:
    """Emulates a dict for _subagents but reads/writes from/to SQLite."""

    def __init__(self):
        self._db_path = ""
        # Try to load default from config immediately
        try:
            from config import load_config
            cfg = load_config()
            self.init_db(cfg.get("db_path"))
        except Exception:
            pass

    def init_db(self, db_path: str):
        if not db_path:
            return
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subagents (
                    id TEXT PRIMARY KEY,
                    goal TEXT,
                    status TEXT,
                    result TEXT DEFAULT '',
                    messages TEXT DEFAULT '[]',
                    started REAL,
                    capabilities TEXT DEFAULT '',
                    workdir TEXT DEFAULT '',
                    kanban_task_id INTEGER
                )
            """)
            # Ensure agent_id exists in kanban_tasks if kanban_tasks exists
            try:
                cursor = conn.execute("PRAGMA table_info(kanban_tasks)")
                columns = [row[1] for row in cursor.fetchall()]
                if columns and "agent_id" not in columns:
                    conn.execute("ALTER TABLE kanban_tasks ADD COLUMN agent_id TEXT")
            except Exception:
                pass
            conn.commit()

    def _conn(self):
        db = self._db_path
        if not db:
            from pathlib import Path
            db = str(Path.home() / ".Koza" / "koza.db")
        conn = sqlite3.connect(db, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_dict(self, row):
        d = dict(row)
        # Deserialize JSON fields
        try:
            d["messages"] = json.loads(d["messages"]) if d.get("messages") else []
        except Exception:
            d["messages"] = []
        try:
            d["capabilities"] = json.loads(d["capabilities"]) if d.get("capabilities") else []
        except Exception:
            d["capabilities"] = []

        # Inject cancellation event from memory
        with _cancel_lock:
            d["_cancel"] = _cancel_events.get(d["id"])

        return AgentEntryProxy(d["id"], d, self)

    def __getitem__(self, key: str):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, goal, status, result, messages, started, capabilities, workdir, kanban_task_id FROM subagents WHERE id = ?",
                (key,),
            ).fetchone()
        if not row:
            raise KeyError(key)
        return self._row_to_dict(row)

    def get(self, key: str, default=None):
        try:
            return self[key]
        except Exception:
            return default

    def __setitem__(self, key: str, value: dict):
        goal = value.get("goal", "")
        status = value.get("status", "pending")
        result = value.get("result", "")
        messages = json.dumps(value.get("messages", []), ensure_ascii=False)
        started = value.get("started", time.time())
        capabilities = json.dumps(value.get("capabilities", []), ensure_ascii=False)
        workdir = value.get("workdir", "")
        kanban_task_id = value.get("kanban_task_id")

        if "_cancel" in value:
            with _cancel_lock:
                _cancel_events[key] = value["_cancel"]

        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO subagents 
                   (id, goal, status, result, messages, started, capabilities, workdir, kanban_task_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, goal, status, result, messages, started, capabilities, workdir, kanban_task_id),
            )
            conn.commit()

    def __contains__(self, key: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM subagents WHERE id = ?", (key,)).fetchone()
        return row is not None

    def pop(self, key: str, default=None):
        val = self.get(key)
        if val is not None:
            with self._conn() as conn:
                conn.execute("DELETE FROM subagents WHERE id = ?", (key,))
                conn.commit()
            with _cancel_lock:
                _cancel_events.pop(key, None)
            return val
        if default is not None:
            return default
        raise KeyError(key)

    def __delitem__(self, key: str):
        self.pop(key)

    def clear(self):
        with self._conn() as conn:
            conn.execute("DELETE FROM subagents")
            conn.commit()
        with _cancel_lock:
            _cancel_events.clear()

    def __eq__(self, other):
        if isinstance(other, SQLiteRegistryProxy):
            if len(self) != len(other):
                return False
            for k in self.keys():
                if k not in other or self[k] != other[k]:
                    return False
            return True
        elif isinstance(other, dict):
            if len(self) != len(other):
                return False
            for k in self.keys():
                if k not in other or self[k] != other[k]:
                    return False
            return True
        return NotImplemented

    def keys(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT id FROM subagents").fetchall()
        return [r[0] for r in rows]

    def values(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM subagents").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def items(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM subagents").fetchall()
        return [(r["id"], self._row_to_dict(r)) for r in rows]

    def __len__(self):
        with self._conn() as conn:
            row = conn.execute("SELECT count(*) FROM subagents").fetchone()
        return row[0] if row else 0

    def __iter__(self):
        return iter(self.keys())


# Expose singleton instance
_subagents = SQLiteRegistryProxy()
