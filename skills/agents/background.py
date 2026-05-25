"""Background task infrastructure — data models, event queue, and task manager."""
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
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


class BackgroundTaskManager:
    """Manages background CodingSession execution."""

    @staticmethod
    def create_task(goal: str, cfg: dict, db_path: str) -> str:
        """Create and start a new background task. Returns task_id."""
        if not cfg.get("coding_mode", {}).get("enabled", False):
            raise RuntimeError(
                "Coding session is disabled. Use spawn_subagent() for background coding tasks."
            )

        from skills.agents.coding_mode import CodingSession

        task_id = uuid.uuid4().hex[:8]
        task = BackgroundTask(id=task_id, goal=goal)

        session = CodingSession(cfg, db_path)
        task.session = session

        thread = threading.Thread(
            target=BackgroundTaskManager._run_task,
            args=(task,),
            daemon=True,
            name=f"bg-task-{task_id}",
        )
        task.thread = thread

        with _tasks_lock:
            _background_tasks[task_id] = task

        thread.start()
        return task_id

    @staticmethod
    def _run_task(task: BackgroundTask) -> None:
        """Execute CodingSession in background thread, draining events."""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        try:
            for event in task.session.run(task.goal):
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

            task.status = TaskStatus.DONE
            task.finished_at = time.time()

        except Exception as e:
            task.status = TaskStatus.ERROR
            task.error_message = str(e)
            task.finished_at = time.time()

    @staticmethod
    def get_status(task_id: str) -> dict | None:
        """Return status report for a task."""
        with _tasks_lock:
            task = _background_tasks.get(task_id)
        if not task:
            return None

        elapsed = 0.0
        if task.started_at:
            end = task.finished_at or time.time()
            elapsed = end - task.started_at

        return {
            "id": task.id,
            "goal": task.goal,
            "status": task.status.value,
            "elapsed_seconds": round(elapsed, 1),
            "current_persona": task.current_persona,
            "completed_subtasks": task.completed_subtasks,
            "total_subtasks": task.total_subtasks,
        }

    @staticmethod
    def get_summary(task_id: str, n: int = 10) -> str | None:
        """Return condensed summary of last N events."""
        with _tasks_lock:
            task = _background_tasks.get(task_id)
        if not task:
            return None

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
        return "\n".join(lines) if lines else "(no events yet)"

    @staticmethod
    def list_tasks() -> list[dict]:
        """Return all tasks with id, goal, and status."""
        with _tasks_lock:
            return [
                {"id": t.id, "goal": t.goal, "status": t.status.value}
                for t in _background_tasks.values()
            ]

    @staticmethod
    def cancel_task(task_id: str) -> bool:
        """Cancel a running task. Returns True if cancellation was initiated."""
        with _tasks_lock:
            task = _background_tasks.get(task_id)
        if not task:
            return False
        if task.status != TaskStatus.RUNNING:
            return False

        task.session.interrupt()
        task.status = TaskStatus.CANCELLED
        task.finished_at = time.time()
        return True
