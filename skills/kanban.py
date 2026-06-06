"""Kanban skill — SQLite-backed task management."""
import sqlite3
from datetime import datetime
from pathlib import Path

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a new Kanban task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string", "default": ""},
                    "column": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "done", "auto"],
                        "default": "todo",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task_plan",
            "description": "Create multiple Kanban tasks from a newline-separated implementation checklist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Parent plan title"},
                    "steps": {"type": "string", "description": "One task per line"},
                    "column": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "done", "auto"],
                        "default": "todo",
                    },
                },
                "required": ["title", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List Kanban tasks, optionally filtered by column.",
            "parameters": {
                "type": "object",
                "properties": {
                    "column": {"type": "string", "default": ""},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_task",
            "description": "Move a task to a different Kanban column.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "column": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "done", "auto"],
                    },
                },
                "required": ["task_id", "column"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update the title or description of a task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "title": {"type": "string", "default": ""},
                    "description": {"type": "string", "default": ""},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Delete a Kanban task by ID.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "integer"}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_kanban_task",
            "description": "Execute a Kanban task in the background using an autonomous sub-agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "The ID of the task to run"},
                    "capabilities": {"type": "string", "default": "", "description": "Comma-separated capabilities required (e.g. 'files,code')"},
                },
                "required": ["task_id"],
            },
        },
    },
]

_db_path: str = ""


def init_db(db_path: str):
    global _db_path
    _db_path = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kanban_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                column TEXT DEFAULT 'todo',
                created_at TEXT,
                updated_at TEXT,
                agent_id TEXT DEFAULT NULL
            )
        """)
        # Schema migration: check if agent_id column exists
        cursor = conn.execute("PRAGMA table_info(kanban_tasks)")
        columns = [row[1] for row in cursor.fetchall()]
        if "agent_id" not in columns:
            conn.execute("ALTER TABLE kanban_tasks ADD COLUMN agent_id TEXT DEFAULT NULL")


def _conn():
    return sqlite3.connect(_db_path)


def create_task(title: str, description: str = "", column: str = "todo") -> str:
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO kanban_tasks (title, description, column, created_at, updated_at) VALUES (?,?,?,?,?)",
            (title, description, column, now, now),
        )
        return f"Task created (id={cur.lastrowid}): [{column}] {title}"


def create_task_plan(title: str, steps: str, column: str = "todo") -> str:
    now = datetime.utcnow().isoformat()
    cleaned_steps = [s.strip(" -\t") for s in steps.splitlines() if s.strip(" -\t")]
    if not cleaned_steps:
        return "ERROR: No plan steps provided."
    created: list[tuple[int, str]] = []
    with _conn() as conn:
        for idx, step in enumerate(cleaned_steps, start=1):
            cur = conn.execute(
                "INSERT INTO kanban_tasks (title, description, column, created_at, updated_at) VALUES (?,?,?,?,?)",
                (f"{title}: {step}", f"Plan: {title}\nStep {idx}/{len(cleaned_steps)}", column, now, now),
            )
            created.append((cur.lastrowid, step))
    lines = [f"Task plan created: {title} ({len(created)} tasks)"]
    lines.extend(f"- id={task_id}: {step}" for task_id, step in created)
    return "\n".join(lines)


def list_tasks(column: str = "") -> str:
    with _conn() as conn:
        if column:
            rows = conn.execute(
                "SELECT id, column, title, description FROM kanban_tasks WHERE column=? ORDER BY id",
                (column,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, column, title, description FROM kanban_tasks ORDER BY column, id"
            ).fetchall()
    if not rows:
        return "No tasks found."
    lines = [f"{'ID':>4}  {'COLUMN':<12}  {'TITLE':<40}  DESCRIPTION"]
    for r in rows:
        lines.append(f"{r[0]:>4}  {r[1]:<12}  {r[2]:<40}  {r[3][:50]}")
    return "\n".join(lines)


def move_task(task_id: int, column: str) -> str:
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE kanban_tasks SET column=?, updated_at=? WHERE id=?",
            (column, now, task_id),
        )
    if cur.rowcount == 0:
        return f"Task {task_id} not found."
    return f"Task {task_id} moved to [{column}]"


def update_task(task_id: int, title: str = "", description: str = "") -> str:
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        changed = 0
        if title:
            changed += conn.execute("UPDATE kanban_tasks SET title=?, updated_at=? WHERE id=?", (title, now, task_id)).rowcount
        if description:
            changed += conn.execute("UPDATE kanban_tasks SET description=?, updated_at=? WHERE id=?", (description, now, task_id)).rowcount
    if changed == 0:
        return f"Task {task_id} not found or no update fields provided."
    return f"Task {task_id} updated."


def delete_task(task_id: int) -> str:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM kanban_tasks WHERE id=?", (task_id,))
    if cur.rowcount == 0:
        return f"Task {task_id} not found."
    return f"Task {task_id} deleted."


def run_kanban_task(task_id: int, capabilities: str = "") -> str:
    """Execute a Kanban task in the background using an autonomous sub-agent."""
    import re
    from skills.agents import spawn_subagent

    # 1. Fetch task
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, title, description, agent_id FROM kanban_tasks WHERE id = ?", (task_id,)).fetchone()

    if not row:
        return f"ERROR: Task {task_id} not found."

    if row["agent_id"]:
        return f"ERROR: Task {task_id} is already running under agent {row['agent_id']}."

    goal = f"Kanban Task: {row['title']}\nDescription:\n{row['description']}"

    # 2. Spawn subagent in background
    launched = spawn_subagent(goal, capabilities=capabilities, wait=False)
    agent_match = re.search(r"Sub-agent\s+([a-f0-9]{8})", launched)
    agent_id = agent_match.group(1) if agent_match else ""

    if agent_id:
        # Update the kanban_tasks table
        with _conn() as conn:
            conn.execute("UPDATE kanban_tasks SET agent_id = ?, column = 'in_progress' WHERE id = ?", (agent_id, task_id))
            conn.commit()
        # Also update the subagent registry proxy to store `kanban_task_id`
        from skills.agents._registry import _subagents, _registry_lock
        with _registry_lock:
            if agent_id in _subagents:
                _subagents[agent_id]["kanban_task_id"] = task_id
        return f"Started Kanban task {task_id} under sub-agent {agent_id}."

    return f"ERROR: Failed to start sub-agent: {launched}"


HANDLERS = {
    "create_task": create_task,
    "create_task_plan": create_task_plan,
    "list_tasks": list_tasks,
    "move_task": move_task,
    "update_task": update_task,
    "delete_task": delete_task,
    "run_kanban_task": run_kanban_task,
}
