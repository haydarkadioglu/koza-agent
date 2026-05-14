"""Cron skill — schedule tasks with APScheduler + system cron/Task Scheduler sync."""
import platform
import sqlite3
import subprocess
import tempfile
import os
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_cron",
            "description": (
                "Schedule a recurring task. The agent will remember and execute it automatically. "
                "Use cron expression OR natural time like 'every day at 09:00'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Human-readable job name"},
                    "command": {"type": "string", "description": "Shell command or agent instruction to run"},
                    "cron_expr": {
                        "type": "string",
                        "description": "Cron expression (e.g. '0 9 * * *' = every day at 09:00)",
                    },
                    "sync_system": {
                        "type": "boolean",
                        "default": True,
                        "description": "Sync to OS scheduler (crontab on Linux, schtasks on Windows)",
                    },
                },
                "required": ["name", "command", "cron_expr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_crons",
            "description": "List all scheduled cron jobs.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_cron",
            "description": "Delete a scheduled cron job by ID.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "integer"}},
                "required": ["job_id"],
            },
        },
    },
]

_db_path: str = ""
_scheduler: BackgroundScheduler | None = None


def init_db(db_path: str):
    global _db_path
    _db_path = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                command TEXT NOT NULL,
                cron_expr TEXT NOT NULL,
                sync_system INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)


def _conn():
    return sqlite3.connect(_db_path)


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    return _scheduler


def _run_job(command: str, job_name: str):
    """Execute a cron job command."""
    print(f"\n[CRON] Running job '{job_name}': {command}")
    try:
        if platform.system() == "Windows":
            subprocess.run(["pwsh", "-NoProfile", "-Command", command], timeout=300)
        else:
            subprocess.run(["bash", "-c", command], timeout=300)
    except Exception as e:
        print(f"[CRON] Job '{job_name}' failed: {e}")


def _sync_to_system(name: str, command: str, cron_expr: str, job_id: int):
    """Sync to OS native scheduler."""
    system = platform.system()
    if system == "Linux" or system == "Darwin":
        _sync_linux_cron(name, command, cron_expr, job_id)
    elif system == "Windows":
        _sync_windows_task(name, command, cron_expr, job_id)


def _sync_linux_cron(name: str, command: str, cron_expr: str, job_id: int):
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
        marker = f"# hermes-cron-{job_id}"
        lines = [l for l in existing.splitlines() if marker not in l]
        lines.append(f"{cron_expr} {command}  {marker}")
        new_crontab = "\n".join(lines) + "\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cron", delete=False) as f:
            f.write(new_crontab)
            tmp = f.name
        subprocess.run(["crontab", tmp])
        os.unlink(tmp)
    except Exception as e:
        print(f"[CRON] Linux crontab sync failed: {e}")


def _parse_cron_to_windows(cron_expr: str) -> tuple[str, str]:
    """Parse basic cron to schtasks format. Returns (schedule_type, time_str)."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return "DAILY", "09:00"
    minute, hour, dom, month, dow = parts
    if dom == "*" and month == "*" and dow == "*":
        return "DAILY", f"{hour.zfill(2)}:{minute.zfill(2)}"
    return "DAILY", "09:00"


def _sync_windows_task(name: str, command: str, cron_expr: str, job_id: int):
    try:
        task_name = f"Hermes_{job_id}_{name.replace(' ','_')}"
        schedule_type, start_time = _parse_cron_to_windows(cron_expr)
        subprocess.run([
            "schtasks", "/create", "/f",
            "/tn", task_name,
            "/tr", f"pwsh -NoProfile -Command \"{command}\"",
            "/sc", schedule_type,
            "/st", start_time,
        ], capture_output=True)
    except Exception as e:
        print(f"[CRON] Windows Task Scheduler sync failed: {e}")


def _remove_from_system(job_id: int, name: str, command: str):
    system = platform.system()
    if system in ("Linux", "Darwin"):
        try:
            result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            existing = result.stdout if result.returncode == 0 else ""
            marker = f"# hermes-cron-{job_id}"
            lines = [l for l in existing.splitlines() if marker not in l]
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cron", delete=False) as f:
                f.write("\n".join(lines) + "\n")
                tmp = f.name
            subprocess.run(["crontab", tmp])
            os.unlink(tmp)
        except Exception:
            pass
    elif system == "Windows":
        task_name = f"Hermes_{job_id}_{name.replace(' ','_')}"
        subprocess.run(["schtasks", "/delete", "/f", "/tn", task_name], capture_output=True)


def create_cron(name: str, command: str, cron_expr: str, sync_system: bool = True) -> str:
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO cron_jobs (name, command, cron_expr, sync_system, created_at) VALUES (?,?,?,?,?)",
            (name, command, cron_expr, int(sync_system), now),
        )
        job_id = cur.lastrowid

    # Register with APScheduler
    try:
        parts = cron_expr.strip().split()
        if len(parts) == 5:
            minute, hour, dom, month, dow = parts
            scheduler = get_scheduler()
            scheduler.add_job(
                _run_job,
                CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow),
                args=[command, name],
                id=f"hermes_{job_id}",
                replace_existing=True,
            )
    except Exception as e:
        return f"Job saved (id={job_id}) but APScheduler error: {e}"

    if sync_system:
        _sync_to_system(name, command, cron_expr, job_id)

    return f"Cron job created (id={job_id}): '{name}' [{cron_expr}] → {command}"


def list_crons() -> str:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, name, cron_expr, command, sync_system FROM cron_jobs ORDER BY id"
        ).fetchall()
    if not rows:
        return "No cron jobs scheduled."
    lines = [f"{'ID':>4}  {'NAME':<25}  {'CRON':<15}  {'SYS':>4}  COMMAND"]
    for r in rows:
        sys_flag = "✓" if r[4] else "✗"
        lines.append(f"{r[0]:>4}  {r[1]:<25}  {r[2]:<15}  {sys_flag:>4}  {r[3][:60]}")
    return "\n".join(lines)


def delete_cron(job_id: int) -> str:
    with _conn() as conn:
        row = conn.execute("SELECT name, command FROM cron_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return f"Job {job_id} not found."
        conn.execute("DELETE FROM cron_jobs WHERE id=?", (job_id,))

    # Remove from APScheduler
    try:
        sched = get_scheduler()
        sched.remove_job(f"hermes_{job_id}")
    except Exception:
        pass

    _remove_from_system(job_id, row[0], row[1])
    return f"Cron job {job_id} ('{row[0]}') deleted."


HANDLERS = {"create_cron": create_cron, "list_crons": list_crons, "delete_cron": delete_cron}
