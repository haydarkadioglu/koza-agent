"""Cron DB layer — SQLite init and connection helper."""
import sqlite3
from pathlib import Path

_db_path: str = ""


def _reload_jobs_into_scheduler() -> None:
    """Load all existing cron jobs from DB into APScheduler (called on startup)."""
    if not _db_path:
        return
    try:
        from skills.cron_scheduler import schedule_job
        with sqlite3.connect(_db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, command, cron_expr FROM cron_jobs"
            ).fetchall()
        for job_id, name, command, cron_expr in rows:
            try:
                schedule_job(command, name, cron_expr, job_id)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Could not reload cron job {job_id} ('{name}'): {e}"
                )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Cron job reload failed: {e}")


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
    _reload_jobs_into_scheduler()


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(_db_path)
