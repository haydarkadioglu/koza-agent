"""Session Memory — persistent session storage with FTS5-powered recall."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

_db_path: str = ""


def init_db(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_title ON sessions(title)")

        # FTS5 virtual table for fast full-text search across session content
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts
            USING fts5(title, summary, messages, content='sessions', content_rowid='id')
        """)
        # Triggers to keep FTS index in sync with main table
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS s_fts_ai AFTER INSERT ON sessions BEGIN
                INSERT INTO sessions_fts(rowid, title, summary, messages)
                VALUES (new.id, new.title, new.summary, new.messages);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS s_fts_ad AFTER DELETE ON sessions BEGIN
                INSERT INTO sessions_fts(sessions_fts, rowid, title, summary, messages)
                VALUES ('delete', old.id, old.title, old.summary, old.messages);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS s_fts_au AFTER UPDATE ON sessions BEGIN
                INSERT INTO sessions_fts(sessions_fts, rowid, title, summary, messages)
                VALUES ('delete', old.id, old.title, old.summary, old.messages);
                INSERT INTO sessions_fts(rowid, title, summary, messages)
                VALUES (new.id, new.title, new.summary, new.messages);
            END
        """)
        # Populate FTS index for any existing rows
        conn.execute("""
            INSERT OR IGNORE INTO sessions_fts(rowid, title, summary, messages)
            SELECT id, title, summary, messages FROM sessions
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(_db_path, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=30000")
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
    """Search past sessions by keyword using FTS5 full-text search."""
    if not _db_path:
        return "Session DB not initialized."
    with _conn() as conn:
        try:
            rows = conn.execute(
                """SELECT s.id, s.title, s.started, s.summary, s.messages
                   FROM sessions s
                   JOIN sessions_fts fts ON s.id = fts.rowid
                   WHERE sessions_fts MATCH ?
                   ORDER BY s.started DESC LIMIT ?""",
                (query, limit),
            ).fetchall()
        except Exception:
            # FTS query syntax error — fall back to LIKE
            q = f"%{query.lower()}%"
            rows = conn.execute(
                """SELECT id, title, started, summary, messages FROM sessions
                   WHERE lower(title) LIKE ? OR lower(summary) LIKE ? OR lower(messages) LIKE ?
                   ORDER BY started DESC LIMIT ?""",
                (q, q, q, limit),
            ).fetchall()

    if not rows:
        return f"No sessions found matching '{query}'."

    results = []
    for row in rows:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["started"]))
        snippets = []
        try:
            messages = json.loads(row["messages"])
            for msg in messages:
                content = msg.get("content", "") or ""
                if isinstance(content, str) and content and query.lower() in content.lower():
                    snippet = content[:200].replace("\n", " ")
                    snippets.append(f"  [{msg.get('role','?')}]: {snippet}...")
        except Exception:
            pass
        result = f"📁 Session #{row['id']} — {row['title']} [{ts}]"
        if row["summary"]:
            result += f"\n  Summary: {row['summary']}"
        if snippets:
            result += "\n" + "\n".join(snippets[:3])
        results.append(result)

    from_count = len(results)
    return f"Found {from_count} session(s) matching '{query}':\n\n" + "\n\n".join(results)


# ─── Tool: recall_recent_sessions ────────────────────────────────────────────

def recall_recent_sessions(hours: int = 24, limit: int = 5) -> str:
    """Search past sessions from the last N hours. Useful for 'what did we do recently?' queries."""
    if not _db_path:
        return "Session DB not initialized."
    cutoff = time.time() - (hours * 3600)
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, title, started, summary FROM sessions
               WHERE started >= ?
               ORDER BY started DESC LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
    if not rows:
        return f"No sessions found in the last {hours} hour(s)."
    lines = []
    for r in rows:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["started"]))
        summary = f" — {r['summary'][:80]}" if r["summary"] else ""
        lines.append(f"#{r['id']} [{ts}] {r['title']}{summary}")
    return f"Sessions from last {hours}h ({len(rows)}):\n" + "\n".join(lines)


# ─── Internal helpers ────────────────────────────────────────────────────────

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
    """Load a specific session's messages by ID."""
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
    """Return raw session rows for UI rendering."""
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


def delete_session(session_id: int) -> str:
    """Delete a saved session by ID."""
    if not _db_path:
        return "Session DB not initialized."
    with _conn() as conn:
        deleted = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,)).rowcount
    return f"Session #{session_id} deleted." if deleted else f"Session #{session_id} not found."


# ─── Registry ────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "recall_sessions",
        "description": "Search past conversation sessions by keyword using full-text search. Use this to recall what was discussed in previous sessions.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword or phrase to search for across all sessions"},
                "limit": {"type": "integer", "description": "Max results to return (default 5)", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "recall_recent_sessions",
        "description": "List sessions from the last N hours. Use this when the user asks 'what did we do recently?' or 'what did we work on earlier?'",
        "parameters": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "How many hours back to look (default 24)", "default": 24},
                "limit": {"type": "integer", "description": "Max sessions to return (default 5)", "default": 5},
            },
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
    "recall_sessions":         lambda query, limit=5: recall_sessions(query, int(limit)),
    "recall_recent_sessions":  lambda hours=24, limit=5: recall_recent_sessions(int(hours), int(limit)),
    "list_sessions":           lambda limit=20: list_sessions(int(limit)),
    "save_session":            lambda title, messages=None, summary="": save_session(title, messages or [], summary),
    "delete_session":          lambda session_id: delete_session(int(session_id)),
}
