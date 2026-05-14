"""Cron DB layer — SQLite init and connection helper."""
import sqlite3
from pathlib import Path

_db_path: str = ""


def init_db(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                command     TEXT NOT NULL,
                cron_expr   TEXT NOT NULL,
                sync_system INTEGER DEFAULT 1,
                created_at  TEXT
            )
        """)


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(_db_path)
