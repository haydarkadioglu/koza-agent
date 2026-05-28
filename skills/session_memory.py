"""Session Memory — persistent session storage with semantic recall."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

_db_path: str = ""


def init_db(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                title     TEXT NOT NULL DEFAULT 'Untitled',
                started   REAL NOT NULL,
                ended     REAL,
                messages  TEXT NOT NULL DEFAULT '[]',
                summary   TEXT NOT NULL DEFAULT ''
            )
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ─── Tool: save_session ──────────────────────────────────────────────────────

def save_session(title: str, messages: list, summary: str = "") -> str:
    """Save current conversation to persistent storage."""
    if not _db_path:
        return "Session DB not initialized."
    now = time.time()
    messages_json = json.dumps(messages, ensure_ascii=False)
    with _conn() as conn:
        cursor = conn.execute(
            "INSERT INTO sessions (title, started, ended, messages, summary) VALUES (?, ?, ?, ?, ?)",
            (title, now, now, messages_json, summary),
        )
        session_id = cursor.lastrowid
    return f"Session #{session_id} saved: '{title}'"


# ─── Tool: recall_sessions ───────────────────────────────────────────────────

def recall_sessions(query: str, limit: int = 5) -> str:
    """Search past sessions by keyword. Returns relevant conversation snippets."""
    if not _db_path:
        return "Session DB not initialized."
    query_lower = query.lower()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, started, summary, messages FROM sessions ORDER BY started DESC LIMIT 100"
        ).fetchall()

    results = []
    for row in rows:
        title_match = query_lower in row["title"].lower()
        summary_match = query_lower in row["summary"].lower()
        # Search inside messages
        msg_match = False
        snippets = []
        try:
            messages = json.loads(row["messages"])
            for msg in messages:
                content = msg.get("content", "") or ""
                if isinstance(content, str) and query_lower in content.lower():
                    msg_match = True
                    snippet = content[:200].replace("\n", " ")
                    snippets.append(f"  [{msg.get('role','?')}]: {snippet}...")
        except Exception:
            pass

        if title_match or summary_match or msg_match:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["started"]))
            result = f"📁 Session #{row['id']} — {row['title']} [{ts}]"
            if row["summary"]:
                result += f"\n  Summary: {row['summary']}"
            result += "\n" + "\n".join(snippets[:3])
            results.append(result)
            if len(results) >= limit:
                break

    if not results:
        return f"No sessions found matching '{query}'."
    return f"Found {len(results)} session(s) matching '{query}':\n\n" + "\n\n".join(results)


# ─── Tool: list_sessions ─────────────────────────────────────────────────────

def load_last_session() -> list | None:
    """Load the most recent session's messages. Returns None if no sessions exist."""
    if not _db_path:
        return None
    with _conn() as conn:
        row = conn.execute(
            "SELECT messages FROM sessions ORDER BY started DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    try:
        messages = json.loads(row["messages"])
        return messages if messages else None
    except Exception:
        return None


def load_session(session_id: int) -> list | None:
    """Load a specific session's messages by ID. Returns None if not found."""
    if not _db_path:
        return None
    with _conn() as conn:
        row = conn.execute(
            "SELECT messages FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["messages"]) or None
    except Exception:
        return None


def get_session_rows(limit: int = 10) -> list[dict]:
    """Return raw session rows (id, title, started, summary) for UI rendering."""
    if not _db_path:
        return []
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, started, summary FROM sessions ORDER BY started DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def list_sessions(limit: int = 20) -> str:
    """List recent sessions."""
    if not _db_path:
        return "Session DB not initialized."
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, started, summary FROM sessions ORDER BY started DESC LIMIT ?",
            (limit,)
        ).fetchall()
    if not rows:
        return "No saved sessions."
    lines = []
    for r in rows:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["started"]))
        summary = f" — {r['summary'][:60]}" if r["summary"] else ""
        lines.append(f"#{r['id']} [{ts}] {r['title']}{summary}")
    return "Recent sessions:\n" + "\n".join(lines)


# ─── Tool: delete_session ────────────────────────────────────────────────────

def delete_session(session_id: int) -> str:
    """Delete a saved session by ID."""
    if not _db_path:
        return "Session DB not initialized."
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return f"Session #{session_id} deleted."


# ─── Registry ────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "recall_sessions",
        "description": "Search past conversation sessions by keyword. Use this to recall what was discussed in previous sessions.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword or phrase to search for"},
                "limit": {"type": "integer", "description": "Max results to return (default 5)", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_sessions",
        "description": "List recent saved sessions with titles and timestamps.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many sessions to list (default 20)", "default": 20},
            },
        },
    },
    {
        "name": "save_session",
        "description": "Save the current conversation as a named session for future recall.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short descriptive title for this session"},
                "summary": {"type": "string", "description": "Optional brief summary of what was accomplished"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "delete_session",
        "description": "Delete a saved session by its numeric ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "integer", "description": "Session ID to delete"},
            },
            "required": ["session_id"],
        },
    },
]

HANDLERS: dict = {
    "recall_sessions": lambda query, limit=5: recall_sessions(query, int(limit)),
    "list_sessions":   lambda limit=20: list_sessions(int(limit)),
    "save_session":    lambda title, messages=None, summary="": save_session(title, messages or [], summary),
    "delete_session":  lambda session_id: delete_session(int(session_id)),
}
