"""Cron scheduler — APScheduler + OS native sync (crontab / schtasks)."""
import logging
import os
import platform
import subprocess
import tempfile
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    return _scheduler


def run_job(command: str, job_name: str, job_id: int | None = None,
            delete_after_run: bool = False, deliver_to: str = "telegram") -> None:
    """Execute a cron job and notify on completion (unless deliver_to is 'none')."""
    print(f"\n[CRON] Running job '{job_name}': {command}")
    try:
        if command.startswith("@agent:"):
            # Agent instruction — create a temporary agent and run the task
            _run_agent_job(command[7:].strip(), job_name)
        else:
            # Shell command
            if platform.system() == "Windows":
                subprocess.run(["pwsh", "-NoProfile", "-Command", command], timeout=300, check=False)
            else:
                subprocess.run(["bash", "-c", command], timeout=300, check=False)

        # Notify success
        _notify_completion(job_name, success=True, deliver_to=deliver_to)

    except Exception as e:  # noqa: BLE001 - a failing job must never kill the scheduler thread
        print(f"[CRON] Job '{job_name}' failed: {e}")
        _notify_completion(job_name, success=False, error=str(e), deliver_to=deliver_to)
    finally:
        if delete_after_run and job_id is not None:
            try:
                from skills.cron_db import get_conn
                with get_conn() as conn:
                    conn.execute("DELETE FROM cron_jobs WHERE id=?", (job_id,))
            except Exception as e:  # noqa: BLE001 - cleanup is best-effort
                logger.warning(f"One-shot cron cleanup failed for {job_id}: {e}")


def _notify_completion(job_name: str, success: bool, error: str | None = None,
                       deliver_to: str = "telegram") -> None:
    """Send cron completion notification via ProactiveNotifier."""
    if deliver_to == "none":
        logger.debug(f"Cron job '{job_name}' finished; delivery is off")
        return
    try:
        from bots.telegram_notifier import ProactiveNotifier
        notifier = ProactiveNotifier.get_instance()
        notifier.notify_cron_completion(job_name, success, error)
    except Exception as e:  # noqa: BLE001 - notification is best-effort
        logger.warning(f"Cron notification failed: {e}")


def _run_agent_job(instruction: str, job_name: str) -> None:
    """Run an agent instruction as a cron job — executes tools and sends results."""
    try:
        from config import load_config
        from core import Agent
        from providers.factory import get_provider

        cfg = load_config()
        agent = Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg)
        agent.permission_callback = lambda name, args: True  # auto-allow in cron

        # Run the agent and collect the response
        response_parts = []
        for event in agent.stream_chat(instruction):
            if isinstance(event, dict) and event.get("type") == "text":
                response_parts.append(event.get("token", ""))

        response = "".join(response_parts).strip()
        if response:
            print(f"[CRON] Job '{job_name}' completed: {response[:200]}")
        else:
            print(f"[CRON] Job '{job_name}' completed (no text output)")
    except Exception as e:  # noqa: BLE001 - an agent job must never kill the scheduler thread
        print(f"[CRON] Agent job '{job_name}' failed: {e}")


# ── OS sync helpers ───────────────────────────────────────────────────────────

def sync_to_system(name: str, command: str, cron_expr: str, job_id: int) -> None:
    system = platform.system()
    if system in ("Linux", "Darwin"):
        _sync_linux_cron(name, command, cron_expr, job_id)
    elif system == "Windows":
        _sync_windows_task(name, command, cron_expr, job_id)


def remove_from_system(job_id: int, name: str, _command: str = "") -> None:
    system = platform.system()
    if system in ("Linux", "Darwin"):
        try:
            result   = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
            existing = result.stdout if result.returncode == 0 else ""
            marker   = f"# koza-cron-{job_id}"
            lines    = [l for l in existing.splitlines() if marker not in l]
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cron", delete=False) as f:
                f.write("\n".join(lines) + "\n")
                tmp = f.name
            subprocess.run(["crontab", tmp], check=False)
            os.unlink(tmp)
        except Exception as e:  # noqa: BLE001 - OS sync is best-effort
            logger.debug(f"crontab removal failed for job {job_id}: {e}")
    elif system == "Windows":
        task_name = f"Koza_{job_id}_{name.replace(' ', '_')}"
        subprocess.run(["schtasks", "/delete", "/f", "/tn", task_name],
                       capture_output=True, check=False)


def _sync_linux_cron(name: str, command: str, cron_expr: str, job_id: int) -> None:
    try:
        result   = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
        existing = result.stdout if result.returncode == 0 else ""
        marker   = f"# koza-cron-{job_id}"
        lines    = [l for l in existing.splitlines() if marker not in l]
        lines.append(f"{cron_expr} {command}  {marker}")
        new_crontab = "\n".join(lines) + "\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cron", delete=False) as f:
            f.write(new_crontab)
            tmp = f.name
        subprocess.run(["crontab", tmp], check=False)
        os.unlink(tmp)
    except Exception as e:  # noqa: BLE001 - OS sync is best-effort
        print(f"[CRON] Linux crontab sync failed: {e}")


def _parse_cron_to_windows(cron_expr: str) -> tuple[str, str]:
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return "DAILY", "09:00"
    minute, hour, dom, month, dow = parts
    if dom == "*" and month == "*" and dow == "*":
        return "DAILY", f"{hour.zfill(2)}:{minute.zfill(2)}"
    return "DAILY", "09:00"


def _sync_windows_task(name: str, command: str, cron_expr: str, job_id: int) -> None:
    try:
        task_name     = f"Koza_{job_id}_{name.replace(' ', '_')}"
        schedule_type, start_time = _parse_cron_to_windows(cron_expr)
        subprocess.run([
            "schtasks", "/create", "/f",
            "/tn", task_name,
            "/tr", f"pwsh -NoProfile -Command \"{command}\"",
            "/sc", schedule_type,
            "/st", start_time,
        ], capture_output=True, check=False)
    except Exception as e:  # noqa: BLE001 - OS sync is best-effort
        print(f"[CRON] Windows Task Scheduler sync failed: {e}")


def _parse_once(expr: str) -> datetime:
    run_at = datetime.fromisoformat(expr[len("@once:"):].strip())
    if run_at.tzinfo is None:
        run_at = run_at.astimezone()
    return run_at


def _cron_trigger(expr: str) -> CronTrigger:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"expected 5 fields, got {len(parts)}")
    minute, hour, dom, month, dow = parts
    return CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow)


def validate_cron_expr(cron_expr: str) -> None:
    """Raise ValueError for any expression schedule_job would reject."""
    expr = (cron_expr or "").strip()
    try:
        if expr.startswith("@once:"):
            _parse_once(expr)
        else:
            _cron_trigger(expr)
    except ValueError as e:
        raise ValueError(f"Invalid cron expression {cron_expr!r}: {e}") from e


def schedule_job(command: str, name: str, cron_expr: str, job_id: int,
                 deliver_to: str = "telegram") -> None:
    """Add a job to APScheduler."""
    validate_cron_expr(cron_expr)
    expr = cron_expr.strip()
    scheduler = get_scheduler()
    if expr.startswith("@once:"):
        scheduler.add_job(
            run_job,
            DateTrigger(run_date=_parse_once(expr)),
            args=[command, name, job_id, True, deliver_to],
            id=f"Koza_{job_id}",
            replace_existing=True,
        )
        return

    scheduler.add_job(
        run_job,
        _cron_trigger(expr),
        args=[command, name, job_id, False, deliver_to],
        id=f"Koza_{job_id}",
        replace_existing=True,
    )


def unschedule_job(job_id: int) -> None:
    try:
        get_scheduler().remove_job(f"Koza_{job_id}")
    except Exception as e:  # noqa: BLE001 - the job may simply not be scheduled
        logger.debug(f"unschedule_job({job_id}): {e}")
