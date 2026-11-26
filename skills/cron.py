"""Cron skill — thin orchestrator. DB in cron_db.py, scheduler in cron_scheduler.py."""
import logging
import threading
from datetime import UTC, datetime, timedelta

from .cron_db import get_conn, get_job, init_db
from .cron_scheduler import (
    remove_from_system,
    schedule_job,
    sync_to_system,
    unschedule_job,
    validate_cron_expr,
)

logger = logging.getLogger(__name__)

# Re-export init_db so callers (core.py) can do cron.init_db(path)
__all__ = [
    "HANDLERS",
    "TOOL_DEFINITIONS",
    "create_cron",
    "create_once_cron",
    "delete_cron",
    "init_db",
    "list_crons",
    "pause_cron",
    "resume_cron",
    "run_cron_now",
    "update_cron",
]

DELIVERY_TARGETS = ("telegram", "none")


def _bad_delivery(deliver_to: str) -> str:
    return (f"Invalid deliver_to {deliver_to!r}. "
            f"Allowed values: {', '.join(DELIVERY_TARGETS)}.")


def create_cron(name: str, command: str, cron_expr: str, sync_system: bool = True,
                deliver_to: str = "telegram") -> str:
    if deliver_to not in DELIVERY_TARGETS:
        return _bad_delivery(deliver_to)
    now = datetime.now(UTC).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO cron_jobs (name, command, cron_expr, sync_system, deliver_to, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (name, command, cron_expr, int(sync_system), deliver_to, now),
        )
        job_id = cur.lastrowid

    try:
        schedule_job(command, name, cron_expr, job_id, deliver_to=deliver_to)
    except Exception as e:  # noqa: BLE001 - reported to the model, never raised
        return f"Job saved (id={job_id}) but APScheduler error: {e}"

    if sync_system:
        sync_to_system(name, command, cron_expr, job_id)

    return f"Cron job created (id={job_id}): '{name}' [{cron_expr}] -> {command}"


def _parse_run_at(run_at: str = "", delay_minutes: int = 0) -> datetime:
    if run_at:
        return datetime.fromisoformat(run_at).astimezone()
    delay = max(1, int(delay_minutes or 1))
    return datetime.now().astimezone() + timedelta(minutes=delay)


def create_once_cron(name: str, command: str, run_at: str = "",
                     delay_minutes: int = 10) -> str:
    """Schedule a one-time agent or shell job. Stored as @once:<iso>."""
    when = _parse_run_at(run_at, delay_minutes)
    cron_expr = f"@once:{when.isoformat()}"
    now = datetime.now(UTC).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO cron_jobs (name, command, cron_expr, sync_system, created_at) VALUES (?,?,?,?,?)",
            (name, command, cron_expr, 0, now),
        )
        job_id = cur.lastrowid

    try:
        schedule_job(command, name, cron_expr, job_id)
    except Exception as e:  # noqa: BLE001 - reported to the model, never raised
        return f"One-shot job saved (id={job_id}) but APScheduler error: {e}"

    return f"One-shot job created (id={job_id}): '{name}' at {when.isoformat()} -> {command}"


def list_crons() -> str:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, cron_expr, command, sync_system, paused, deliver_to"
            " FROM cron_jobs ORDER BY id"
        ).fetchall()
    if not rows:
        return "No cron jobs scheduled."
    header = (f"{'ID':>4}  {'NAME':<25}  {'SCHEDULE':<25}  {'STATE':<6}  {'SYS':>4}  "
              f"{'NOTIFY':<6}  COMMAND")
    lines = [header]
    for job_id, name, schedule, command, sync_system, paused, deliver_to in rows:
        sys_flag = "✓" if sync_system else "✗"
        state = "paused" if paused else "active"
        notify = "off" if deliver_to == "none" else "on"
        if schedule.startswith("@once:"):
            schedule = "once " + schedule[len("@once:"):]
        lines.append(f"{job_id:>4}  {name:<25}  {schedule[:25]:<25}  {state:<6}  {sys_flag:>4}  "
                     f"{notify:<6}  {command[:60]}")
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


# ── Control operations: pause / resume / update / run now ───────────────────

def _not_found(job_id: int) -> str:
    return f"Job {job_id} not found."


def pause_cron(job_id: int) -> str:
    job = get_job(job_id)
    if not job:
        return _not_found(job_id)
    with get_conn() as conn:
        conn.execute("UPDATE cron_jobs SET paused=1 WHERE id=?", (job_id,))
    # Also re-applied when already paused so the scheduler and OS state always match the DB.
    unschedule_job(job_id)
    remove_from_system(job_id, job["name"])
    if job["paused"]:
        return f"Job {job_id} ('{job['name']}') is already paused."
    return f"Job {job_id} ('{job['name']}') paused. Use resume to restart it."


def resume_cron(job_id: int) -> str:
    job = get_job(job_id)
    if not job:
        return _not_found(job_id)
    if not job["paused"]:
        return f"Job {job_id} ('{job['name']}') is not paused."
    with get_conn() as conn:
        conn.execute("UPDATE cron_jobs SET paused=0 WHERE id=?", (job_id,))

    try:
        schedule_job(job["command"], job["name"], job["cron_expr"], job_id,
                     deliver_to=job["deliver_to"])
    except Exception as e:  # noqa: BLE001 - reported to the model, never raised
        return f"Job {job_id} ('{job['name']}') resumed but APScheduler error: {e}"

    if job["sync_system"]:
        sync_to_system(job["name"], job["command"], job["cron_expr"], job_id)
    return f"Job {job_id} ('{job['name']}') resumed [{job['cron_expr']}]."


def update_cron(job_id: int, name: str | None = None, command: str | None = None,
                cron_expr: str | None = None, sync_system: bool | None = None,
                deliver_to: str | None = None) -> str:
    requested = {
        "name": name, "command": command, "cron_expr": cron_expr,
        "sync_system": None if sync_system is None else int(bool(sync_system)),
        "deliver_to": deliver_to,
    }
    requested = {k: v for k, v in requested.items() if v is not None}
    if not requested:
        return "No updates provided."

    job = get_job(job_id)
    if not job:
        return _not_found(job_id)
    if deliver_to is not None and deliver_to not in DELIVERY_TARGETS:
        return f"Job {job_id} not updated: {_bad_delivery(deliver_to)}"
    if cron_expr is not None:
        try:
            validate_cron_expr(cron_expr)
        except ValueError as e:
            return f"Job {job_id} ('{job['name']}') not updated: {e}"

    changed = {k: v for k, v in requested.items() if job[k] != v}
    if not changed:
        return f"Job {job_id} ('{job['name']}') unchanged: values already match."

    with get_conn() as conn:
        assignments = ", ".join(f"{column}=?" for column in changed)
        conn.execute(f"UPDATE cron_jobs SET {assignments} WHERE id=?",
                     (*changed.values(), job_id))
    new = {**job, **changed}

    summary = f"Job {job_id} ('{new['name']}') updated: {', '.join(changed)}."
    unschedule_job(job_id)
    if not new["paused"]:
        try:
            schedule_job(new["command"], new["name"], new["cron_expr"], job_id,
                         deliver_to=new["deliver_to"])
        except Exception as e:  # noqa: BLE001 - reported to the model, never raised
            summary += f" APScheduler error: {e}"

    # The Windows task name embeds the job name, so a rename must re-sync too.
    if changed.keys() & {"name", "command", "cron_expr", "sync_system"}:
        remove_from_system(job_id, job["name"])
        if new["sync_system"] and not new["paused"]:
            sync_to_system(new["name"], new["command"], new["cron_expr"], job_id)

    if new["paused"]:
        summary += " Job is paused; changes apply when it is resumed."
    return summary


def run_cron_now(job_id: int, runner=None, wait_event: threading.Event | None = None) -> str:
    """Start a job once in the background without touching its schedule.

    ``runner`` defaults to cron_scheduler.run_job (looked up at call time);
    ``wait_event`` is set once the runner returns.
    """
    job = get_job(job_id)
    if not job:
        return _not_found(job_id)
    if job["paused"]:
        return f"Job {job_id} is paused; resume it before running."

    if runner is None:
        from . import cron_scheduler
        runner = cron_scheduler.run_job

    def _target() -> None:
        try:
            runner(job["command"], job["name"], job_id, False, job["deliver_to"])
        except Exception:
            logger.exception(f"Manual run of cron job {job_id} failed")
        finally:
            if wait_event is not None:
                wait_event.set()

    threading.Thread(target=_target, name=f"koza-cron-run-{job_id}", daemon=True).start()
    return f"Job {job_id} ('{job['name']}') started now: {job['command'][:60]}"


_CONTROL_ACTIONS = {
    "pause":   lambda job_id, _fields: pause_cron(job_id),
    "resume":  lambda job_id, _fields: resume_cron(job_id),
    "update":  lambda job_id, fields: update_cron(job_id, **fields),
    "run_now": lambda job_id, _fields: run_cron_now(job_id),
}
_UPDATE_FIELDS = ("name", "command", "cron_expr", "sync_system", "deliver_to")


def cron_control(action: str = "", job_id=None, **kwargs) -> str:
    handler = _CONTROL_ACTIONS.get(action)
    if handler is None:
        return f"Unknown cron action '{action}'. Use pause, resume, update or run_now."
    try:
        job_id = int(job_id)
    except (TypeError, ValueError):
        return f"Invalid job_id {job_id!r}: expected an integer from list_crons."
    fields = {k: kwargs[k] for k in _UPDATE_FIELDS if k in kwargs}
    return handler(job_id, fields)


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
                "deliver_to":  {"type": "string", "enum": ["telegram", "none"], "default": "telegram",
                                "description": "Where the result goes: telegram (default) or none"},
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
        "name": "create_once_cron",
        "description": (
            "Schedule a one-time task for later. Use this for follow-up checks, "
            "coding progress checks, or single reminders. The command can be '@agent: ...'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name":          {"type": "string", "description": "Human-readable job name"},
                "command":       {"type": "string", "description": "Shell command or @agent instruction to run once"},
                "run_at":        {"type": "string", "default": "", "description": "ISO datetime. If empty, delay_minutes is used."},
                "delay_minutes": {"type": "integer", "default": 10, "description": "Minutes from now when run_at is empty"},
            },
            "required": ["name", "command"],
        },
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
    {
        "name": "cron_control",
        "description": (
            "Pause, resume, update or run an existing cron job now. "
            "Use action='pause' to stop a job without deleting it, 'resume' to restart it, "
            "'update' to change its name/command/schedule/delivery, "
            "'run_now' to execute it once immediately without touching its schedule."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action":      {"type": "string", "enum": ["pause", "resume", "update", "run_now"]},
                "job_id":      {"type": "integer", "description": "Job ID from list_crons"},
                "name":        {"type": "string"},
                "command":     {"type": "string"},
                "cron_expr":   {"type": "string"},
                "sync_system": {"type": "boolean"},
                "deliver_to":  {"type": "string", "enum": ["telegram", "none"],
                                "description": "Where the result goes: telegram (default) or none"},
            },
            "required": ["action", "job_id"],
        },
    },
]

HANDLERS = {
    "create_cron": lambda name, command, cron_expr, sync_system=True, deliver_to="telegram":
                       create_cron(name, command, cron_expr, sync_system, deliver_to),
    "create_once_cron": lambda name, command, run_at="", delay_minutes=10:
                       create_once_cron(name, command, run_at, int(delay_minutes)),
    "list_crons":  lambda **_: list_crons(),
    "delete_cron": lambda job_id: delete_cron(int(job_id)),
    "cron_control": cron_control,
}
