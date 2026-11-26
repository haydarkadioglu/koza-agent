"""Cron DB layer — SQLite init and connection helper."""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_db_path: str = ""

_JOB_COLUMNS = ("id", "name", "command", "cron_expr", "sync_system", "paused",
                "deliver_to", "created_at")

# Columns added after the original schema: name -> DDL used by ALTER TABLE.
_MIGRATED_COLUMNS = {
    "paused":     "paused INTEGER NOT NULL DEFAULT 0",
    "deliver_to": "deliver_to TEXT NOT NULL DEFAULT 'telegram'",
}


def _reload_jobs_into_scheduler() -> None:
    """Load active cron jobs from DB into APScheduler (called on startup).

    Paused jobs stay in the DB but are not scheduled.
    """
    if not _db_path:
        return
    try:
        from skills.cron_scheduler import schedule_job
        with sqlite3.connect(_db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, command, cron_expr, deliver_to FROM cron_jobs WHERE paused=0"
            ).fetchall()
        for job_id, name, command, cron_expr, deliver_to in rows:
            try:
                schedule_job(command, name, cron_expr, job_id, deliver_to=deliver_to)
            except Exception as e:  # noqa: BLE001 - one bad row must not block the others
                logger.warning(f"Could not reload cron job {job_id} ('{name}'): {e}")
    except Exception as e:  # noqa: BLE001 - startup must survive a broken cron DB
        logger.warning(f"Cron job reload failed: {e}")


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(cron_jobs)")}
    for column, ddl in _MIGRATED_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE cron_jobs ADD COLUMN {ddl}")


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
        _migrate(conn)
    _reload_jobs_into_scheduler()


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(_db_path)


def get_job(job_id: int) -> dict | None:
    """Return a cron job as a dict, or None when the id is unknown."""
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {', '.join(_JOB_COLUMNS)} FROM cron_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    return dict(zip(_JOB_COLUMNS, row, strict=True)) if row else None
