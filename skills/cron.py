"""Cron skill — thin orchestrator. DB in cron_db.py, scheduler in cron_scheduler.py."""
from datetime import datetime

from .cron_db import init_db, get_conn
from .cron_scheduler import schedule_job, unschedule_job, sync_to_system, remove_from_system

# Re-export init_db so callers (core.py) can do cron.init_db(path)
__all__ = ["init_db", "create_cron", "list_crons", "delete_cron", "TOOL_DEFINITIONS", "HANDLERS"]


def create_cron(name: str, command: str, cron_expr: str, sync_system: bool = True) -> str:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO cron_jobs (name, command, cron_expr, sync_system, created_at) VALUES (?,?,?,?,?)",
            (name, command, cron_expr, int(sync_system), now),
        )
        job_id = cur.lastrowid

    try:
        schedule_job(command, name, cron_expr, job_id)
    except Exception as e:
        return f"Job saved (id={job_id}) but APScheduler error: {e}"

    if sync_system:
        sync_to_system(name, command, cron_expr, job_id)

    return f"Cron job created (id={job_id}): '{name}' [{cron_expr}] → {command}"


def list_crons() -> str:
    with get_conn() as conn:
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
    with get_conn() as conn:
        row = conn.execute("SELECT name, command FROM cron_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return f"Job {job_id} not found."
        conn.execute("DELETE FROM cron_jobs WHERE id=?", (job_id,))

    unschedule_job(job_id)
    remove_from_system(job_id, row[0])
    return f"Cron job {job_id} ('{row[0]}') deleted."


# ── Tool definitions (flat format) ───────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "create_cron",
        "description": (
            "Schedule a recurring task. The agent will remember and execute it automatically. "
            "Use cron expression OR natural time like 'every day at 09:00'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name":        {"type": "string",  "description": "Human-readable job name"},
                "command":     {"type": "string",  "description": "Shell command or agent instruction to run"},
                "cron_expr":   {"type": "string",  "description": "Cron expression, e.g. '0 9 * * *'"},
                "sync_system": {"type": "boolean", "default": True,
                                "description": "Sync to OS scheduler (crontab/schtasks)"},
            },
            "required": ["name", "command", "cron_expr"],
        },
    },
    {
        "name": "list_crons",
        "description": "List all scheduled cron jobs.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_cron",
        "description": "Delete a scheduled cron job by ID.",
        "parameters": {
            "type": "object",
            "properties": {"job_id": {"type": "integer", "description": "Job ID from list_crons"}},
            "required": ["job_id"],
        },
    },
]

HANDLERS = {
    "create_cron": lambda name, command, cron_expr, sync_system=True:
                       create_cron(name, command, cron_expr, sync_system),
    "list_crons":  lambda **_: list_crons(),
    "delete_cron": lambda job_id: delete_cron(int(job_id)),
}
