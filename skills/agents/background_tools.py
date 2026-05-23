"""Background task tool definitions and handlers for the LLM tool registry."""

from skills.agents.background import BackgroundTaskManager
from config import load_config


# ── Tool Schemas ──────────────────────────────────────────────────────────────

BACKGROUND_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "start_background_task",
            "description": "Start a coding task in the background. The task runs in a separate thread while you continue chatting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "The coding task description to execute in the background.",
                    }
                },
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_background_status",
            "description": "Get the current status and progress of a background task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The unique identifier of the background task.",
                    }
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_background_tasks",
            "description": "List all background tasks with their IDs, goals, and current status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_background_task",
            "description": "Cancel a running background task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The unique identifier of the background task to cancel.",
                    }
                },
                "required": ["task_id"],
            },
        },
    },
]


# ── Tool Handlers ─────────────────────────────────────────────────────────────


def handle_start_background_task(goal: str) -> str:
    cfg = load_config()
    db_path = cfg["db_path"]
    task_id = BackgroundTaskManager.create_task(goal, cfg, db_path)
    return f"Background task started: {task_id}\nGoal: {goal}"


def handle_get_background_status(task_id: str) -> str:
    status = BackgroundTaskManager.get_status(task_id)
    if not status:
        return f"No background task found with ID: {task_id}"
    summary = BackgroundTaskManager.get_summary(task_id)
    lines = [
        f"Task: {status['id']}",
        f"Goal: {status['goal']}",
        f"Status: {status['status']}",
        f"Elapsed: {status['elapsed_seconds']}s",
        f"Persona: {status['current_persona'] or 'N/A'}",
        f"Progress: {status['completed_subtasks']}/{status['total_subtasks']} subtasks",
    ]
    if summary:
        lines.append(f"\nRecent activity:\n{summary}")
    return "\n".join(lines)


def handle_list_background_tasks() -> str:
    tasks = BackgroundTaskManager.list_tasks()
    if not tasks:
        return "No background tasks."
    lines = []
    for t in tasks:
        lines.append(f"  [{t['status']}] {t['id']} — {t['goal'][:60]}")
    return "Background tasks:\n" + "\n".join(lines)


def handle_cancel_background_task(task_id: str) -> str:
    success = BackgroundTaskManager.cancel_task(task_id)
    if success:
        return f"Task {task_id} cancelled."
    return f"Cannot cancel task {task_id} (not found or not running)."


# ── Handler Registry ──────────────────────────────────────────────────────────

BACKGROUND_HANDLERS = {
    "start_background_task": handle_start_background_task,
    "get_background_status": handle_get_background_status,
    "list_background_tasks": handle_list_background_tasks,
    "cancel_background_task": handle_cancel_background_task,
}
