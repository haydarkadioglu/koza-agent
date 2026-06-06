"""Background task infrastructure — data models, event queue, and task manager."""
import sqlite3
import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class EventQueue:
    """Thread-safe event collection for a single BackgroundTask."""

    def __init__(self, max_size: int = 1000):
        self._events: deque[dict] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def append(self, event: dict) -> None:
        with self._lock:
            self._events.append(event)

    def get_last_n(self, n: int = 10) -> list[dict]:
        with self._lock:
            items = list(self._events)
            return items[-n:] if len(items) > n else items

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


@dataclass
class BackgroundTask:
    id: str
    goal: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    summary: str = ""
    written_files: list[str] = field(default_factory=list)
    error_message: str = ""
    current_persona: str = ""
    completed_subtasks: int = 0
    total_subtasks: int = 0
    event_queue: EventQueue = field(default_factory=EventQueue)
    session: Any = None  # CodingSession instance
    thread: threading.Thread | None = None


# ── Module-level registry — accessible from CLI and Telegram contexts ─────────

_background_tasks: dict[str, BackgroundTask] = {}
_tasks_lock = threading.Lock()
_db_path: str = ""


def init_db(db_path: str):
    global _db_path
    _db_path = db_path
    if not db_path:
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS background_tasks (
                id TEXT PRIMARY KEY,
                goal TEXT,
                status TEXT,
                created_at REAL,
                started_at REAL,
                finished_at REAL,
                summary TEXT DEFAULT '',
                written_files TEXT DEFAULT '[]',
                error_message TEXT DEFAULT '',
                current_persona TEXT DEFAULT '',
                completed_subtasks INTEGER DEFAULT 0,
                total_subtasks INTEGER DEFAULT 0
            )
        """)
        conn.commit()


def _conn():
    db = _db_path
    if not db:
        try:
            from config import load_config
            cfg = load_config()
            db = cfg.get("db_path", "")
        except Exception:
            pass
    if not db:
        from pathlib import Path
        db = str(Path.home() / ".Koza" / "koza.db")
    conn = sqlite3.connect(db, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _check_task_cancelled_in_db(task_id: str) -> bool:
    try:
        with _conn() as conn:
            row = conn.execute("SELECT status FROM background_tasks WHERE id = ?", (task_id,)).fetchone()
            if row and row["status"] in ("cancelled", TaskStatus.CANCELLED.value):
                return True
    except Exception:
        pass
    return False


class BackgroundTaskManager:
    """Manages background CodingSession execution."""

    @staticmethod
    def create_task(goal: str, cfg: dict, db_path: str) -> str:
        """Create and start a new background task. Returns task_id."""
        init_db(db_path)
        try:
            from skills.agents.coding_mode import CodingSession
            session = CodingSession(cfg, db_path)
            task_id = str(uuid.uuid4())[:8]
            task = BackgroundTask(id=task_id, goal=goal, session=session)
            
            # Insert task into SQLite
            with _conn() as conn:
                conn.execute(
                    """INSERT INTO background_tasks 
                       (id, goal, status, created_at, started_at, finished_at)
                       VALUES (?, ?, ?, ?, NULL, NULL)""",
                    (task_id, goal, TaskStatus.PENDING.value, time.time()),
                )
                conn.commit()

            with _tasks_lock:
                _background_tasks[task_id] = task
            t = threading.Thread(
                target=BackgroundTaskManager._run_task,
                args=(task,),
                daemon=True,
            )
            t.start()
            return task_id
        except ImportError:
            # Fallback to spawn_subagent if CodingSession unavailable
            from skills.agents import spawn_subagent
            result = spawn_subagent(goal, wait=False)
            parts = result.split()
            return parts[1] if len(parts) > 1 else "unknown"

    @staticmethod
    def _run_task(task: BackgroundTask) -> None:
        """Execute CodingSession in background thread, draining events."""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        # Update SQLite status to RUNNING
        try:
            with _conn() as conn:
                conn.execute(
                    "UPDATE background_tasks SET status = ?, started_at = ? WHERE id = ?",
                    (TaskStatus.RUNNING.value, task.started_at, task.id),
                )
                conn.commit()
        except Exception:
            pass

        try:
            for event in task.session.run(task.goal):
                # Process-safe cancellation check
                if _check_task_cancelled_in_db(task.id):
                    task.status = TaskStatus.CANCELLED
                    task.session.interrupt()
                    break

                task.event_queue.append(event)
                # Track progress from events
                if event.get("type") == "status":
                    task.current_persona = event.get("persona", "")
                elif event.get("type") == "plan":
                    plan = event.get("plan", {})
                    task.total_subtasks = len(plan.get("tasks", []))
                elif event.get("type") == "done":
                    task.summary = event.get("summary", "")
                elif event.get("type") in ("persona_tool",) and event.get("phase") == "done":
                    task.completed_subtasks += 1

                # Track written files from session context
                task.written_files = task.session.context.written_files[:]

                # Update SQLite with intermediate progress
                try:
                    with _conn() as conn:
                        conn.execute(
                            """UPDATE background_tasks SET 
                               current_persona = ?, total_subtasks = ?, completed_subtasks = ?, 
                               written_files = ?, summary = ?
                               WHERE id = ?""",
                            (task.current_persona, task.total_subtasks, task.completed_subtasks,
                             json.dumps(task.written_files), task.summary, task.id),
                        )
                        conn.commit()
                except Exception:
                    pass

            if task.status != TaskStatus.CANCELLED:
                task.status = TaskStatus.DONE
            task.finished_at = time.time()

        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error_message = str(e)
            task.finished_at = time.time()

        # Update SQLite with final status
        try:
            with _conn() as conn:
                conn.execute(
                    """UPDATE background_tasks SET 
                       status = ?, finished_at = ?, summary = ?, error_message = ?, written_files = ?
                       WHERE id = ?""",
                    (task.status.value, task.finished_at, task.summary, task.error_message,
                     json.dumps(task.written_files), task.id),
                )
                conn.commit()
        except Exception:
            pass

    @staticmethod
    def get_status(task_id: str) -> dict | None:
        """Return status report for a task (checks memory, database, then subagent registries)."""
        # 1. Check in-memory _background_tasks first
        with _tasks_lock:
            task = _background_tasks.get(task_id)
        if task:
            elapsed = 0.0
            started = task.started_at
            finished = task.finished_at
            if started:
                end = finished or time.time()
                elapsed = end - started
            return {
                "id": task.id,
                "goal": task.goal,
                "status": task.status.value if isinstance(task.status, Enum) else task.status,
                "elapsed_seconds": round(elapsed, 1),
                "current_persona": task.current_persona or "",
                "completed_subtasks": task.completed_subtasks,
                "total_subtasks": task.total_subtasks,
            }

        # 2. Check SQLite database
        try:
            with _conn() as conn:
                row = conn.execute(
                    "SELECT id, goal, status, started_at, finished_at, current_persona, completed_subtasks, total_subtasks FROM background_tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
            if row:
                elapsed = 0.0
                started = row["started_at"]
                finished = row["finished_at"]
                if started:
                    end = finished or time.time()
                    elapsed = end - started
                return {
                    "id": row["id"],
                    "goal": row["goal"],
                    "status": row["status"],
                    "elapsed_seconds": round(elapsed, 1),
                    "current_persona": row["current_persona"] or "",
                    "completed_subtasks": row["completed_subtasks"],
                    "total_subtasks": row["total_subtasks"],
                }
        except Exception:
            pass

        # 3. Check subagents
        from ._registry import _subagents
        ag = _subagents.get(task_id)
        if ag:
            elapsed = round(time.time() - ag.get("started", time.time()), 1)
            return {
                "id": task_id,
                "goal": ag.get("goal", ""),
                "status": ag.get("status", "pending"),
                "elapsed_seconds": elapsed,
                "current_persona": "",
                "completed_subtasks": 0,
                "total_subtasks": 0,
            }
        return None

    @staticmethod
    def get_summary(task_id: str, n: int = 10) -> str | None:
        """Return condensed summary of last N events."""
        with _tasks_lock:
            task = _background_tasks.get(task_id)
        if task:
            if task.status == TaskStatus.DONE and task.summary:
                return task.summary
            events = task.event_queue.get_last_n(n)
            lines = []
            for ev in events:
                etype = ev.get("type", "")
                if etype == "status":
                    lines.append(f"[{ev.get('persona', '')}] {ev.get('message', '')}")
                elif etype == "persona_tool":
                    phase = ev.get("phase", "")
                    lines.append(f"  Tool: {ev.get('tool', '')} ({phase})")
                elif etype == "done":
                    lines.append(f"✓ Done: {ev.get('summary', '')[:100]}")
                elif etype == "error_recorded":
                    lines.append(f"⚠ Error: {ev.get('error', {}).get('description', '')[:80]}")
            if lines:
                return "\n".join(lines)

        try:
            with _conn() as conn:
                row = conn.execute(
                    "SELECT status, summary, error_message FROM background_tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
            if row:
                if row["status"] == "error":
                    return f"Error: {row['error_message']}"
                return row["summary"] or f"Status: {row['status']}"
        except Exception:
            pass

        # Fallback: spawn_subagent sub-agent result
        from ._registry import _subagents
        ag = _subagents.get(task_id)
        if ag:
            return ag.get("result", "") or "(no output yet)"
        return None

    @staticmethod
    def list_tasks() -> list[dict]:
        """Return all tasks with id, goal, and status."""
        results = []
        # 1. Read from SQLite
        try:
            with _conn() as conn:
                rows = conn.execute("SELECT id, goal, status FROM background_tasks ORDER BY id").fetchall()
                for r in rows:
                    results.append({"id": r["id"], "goal": r["goal"], "status": r["status"]})
        except Exception:
            pass

        # 2. Add from in-memory _background_tasks
        with _tasks_lock:
            for tid, task in _background_tasks.items():
                if not any(r["id"] == tid for r in results):
                    status_val = task.status.value if isinstance(task.status, Enum) else task.status
                    results.append({"id": task.id, "goal": task.goal, "status": status_val})

        # 3. Add from _subagents
        from ._registry import _subagents
        bg_ids = {entry["id"] for entry in results}
        for ag_id in _subagents.keys():
            if ag_id not in bg_ids:
                ag = _subagents.get(ag_id)
                if ag:
                    results.append({"id": ag_id, "goal": ag.get("goal", ""), "status": ag.get("status", "pending")})
        return results

    @staticmethod
    def cancel_task(task_id: str) -> bool:
        """Cancel a running task. Returns True if cancellation was initiated."""
        cancelled = False
        with _tasks_lock:
            task = _background_tasks.get(task_id)
        if task:
            if task.status == TaskStatus.RUNNING:
                task.session.interrupt()
                task.status = TaskStatus.CANCELLED
                task.finished_at = time.time()
                cancelled = True

        try:
            with _conn() as conn:
                conn.execute(
                    "UPDATE background_tasks SET status = ?, finished_at = ? WHERE id = ?",
                    (TaskStatus.CANCELLED.value, time.time(), task_id),
                )
                conn.commit()
                cancelled = True
        except Exception:
            pass

        if cancelled:
            return True

        # Fallback: spawn_subagent sub-agent
        from ._registry import _subagents
        ag = _subagents.get(task_id)
        if ag and ag.get("status") == "running":
            ag["status"] = "cancelled"
            return True
        return False
