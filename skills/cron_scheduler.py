"""Cron scheduler — APScheduler + OS native sync (crontab / schtasks)."""
import os
import platform
import subprocess
import tempfile

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    return _scheduler


def run_job(command: str, job_name: str) -> None:
    print(f"\n[CRON] Running job '{job_name}': {command}")
    try:
        if platform.system() == "Windows":
            subprocess.run(["pwsh", "-NoProfile", "-Command", command], timeout=300)
        else:
            subprocess.run(["bash", "-c", command], timeout=300)
    except Exception as e:
        print(f"[CRON] Job '{job_name}' failed: {e}")


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
            result   = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            existing = result.stdout if result.returncode == 0 else ""
            marker   = f"# hermes-cron-{job_id}"
            lines    = [l for l in existing.splitlines() if marker not in l]
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cron", delete=False) as f:
                f.write("\n".join(lines) + "\n")
                tmp = f.name
            subprocess.run(["crontab", tmp])
            os.unlink(tmp)
        except Exception:
            pass
    elif system == "Windows":
        task_name = f"Hermes_{job_id}_{name.replace(' ', '_')}"
        subprocess.run(["schtasks", "/delete", "/f", "/tn", task_name], capture_output=True)


def _sync_linux_cron(name: str, command: str, cron_expr: str, job_id: int) -> None:
    try:
        result   = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
        marker   = f"# hermes-cron-{job_id}"
        lines    = [l for l in existing.splitlines() if marker not in l]
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
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return "DAILY", "09:00"
    minute, hour, dom, month, dow = parts
    if dom == "*" and month == "*" and dow == "*":
        return "DAILY", f"{hour.zfill(2)}:{minute.zfill(2)}"
    return "DAILY", "09:00"


def _sync_windows_task(name: str, command: str, cron_expr: str, job_id: int) -> None:
    try:
        task_name     = f"Hermes_{job_id}_{name.replace(' ', '_')}"
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


def schedule_job(command: str, name: str, cron_expr: str, job_id: int) -> None:
    """Add a job to APScheduler."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expr!r}")
    minute, hour, dom, month, dow = parts
    scheduler = get_scheduler()
    scheduler.add_job(
        run_job,
        CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow),
        args=[command, name],
        id=f"hermes_{job_id}",
        replace_existing=True,
    )


def unschedule_job(job_id: int) -> None:
    try:
        get_scheduler().remove_job(f"hermes_{job_id}")
    except Exception:
        pass
