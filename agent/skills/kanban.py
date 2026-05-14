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
                updated_at TEXT
            )
        """)


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
        conn.execute(
            "UPDATE kanban_tasks SET column=?, updated_at=? WHERE id=?",
            (column, now, task_id),
        )
    return f"Task {task_id} moved to [{column}]"


def update_task(task_id: int, title: str = "", description: str = "") -> str:
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        if title:
            conn.execute("UPDATE kanban_tasks SET title=?, updated_at=? WHERE id=?", (title, now, task_id))
        if description:
            conn.execute("UPDATE kanban_tasks SET description=?, updated_at=? WHERE id=?", (description, now, task_id))
    return f"Task {task_id} updated."


def delete_task(task_id: int) -> str:
    with _conn() as conn:
        conn.execute("DELETE FROM kanban_tasks WHERE id=?", (task_id,))
    return f"Task {task_id} deleted."


HANDLERS = {
    "create_task": create_task,
    "list_tasks": list_tasks,
    "move_task": move_task,
    "update_task": update_task,
    "delete_task": delete_task,
}
