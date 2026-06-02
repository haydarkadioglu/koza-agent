"""Working Memory — short-term, always-active ring buffer.

Holds the last N events (tool calls, key results, user actions).
Automatically injected into every system prompt as compact context.
Oldest entries are automatically dropped when the buffer is full.

Contrast with shared_memory (permanent, retrieved only on demand).
"""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

_db_path: str = ""
MAX_ENTRIES = 20  # ring buffer size


def init_db(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS working_memory (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL DEFAULT 'action',
                summary    TEXT NOT NULL,
                detail     TEXT NOT NULL DEFAULT '',
                ts         REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wm_ts ON working_memory(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wm_event_type ON working_memory(event_type)")


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


# ─── Internal: auto-trim to ring buffer size ─────────────────────────────────

def _trim() -> None:
    with _conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
        if count > MAX_ENTRIES:
            # Delete oldest entries beyond MAX_ENTRIES
            conn.execute("""
                DELETE FROM working_memory WHERE id IN (
                    SELECT id FROM working_memory ORDER BY ts ASC LIMIT ?
                )
            """, (count - MAX_ENTRIES,))


# ─── Core operations ─────────────────────────────────────────────────────────

def wm_add(summary: str, detail: str = "", event_type: str = "action") -> str:
    """Add an event to working memory (internal, called automatically)."""
    if not _db_path:
        return "Working memory not initialized."
    with _conn() as conn:
        conn.execute(
            "INSERT INTO working_memory (event_type, summary, detail, ts) VALUES (?,?,?,?)",
            (event_type, summary[:200], detail[:500], time.time()),
        )
    _trim()
    return "Working memory event added."


def wm_get_context(limit: int = MAX_ENTRIES) -> str:
    """Return compact working memory string for system prompt injection."""
    if not _db_path:
        return ""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT event_type, summary, ts FROM working_memory ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
    if not rows:
        return ""
    lines = []
    for r in reversed(rows):  # chronological order
        ts = time.strftime("%H:%M", time.localtime(r["ts"]))
        icon = {"action": "⚡", "tool": "🔧", "user": "👤", "result": "📤", "error": "❌"}.get(r["event_type"], "•")
        lines.append(f"  {icon} [{ts}] {r['summary']}")
    return "## Working Memory (recent activity):\n" + "\n".join(lines)


def wm_list(limit: int = MAX_ENTRIES) -> str:
    """List working memory entries (tool-callable)."""
    if not _db_path:
        return "Working memory not initialized."
    with _conn() as conn:
        rows = conn.execute(
            "SELECT event_type, summary, detail, ts FROM working_memory ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
    if not rows:
        return "Working memory is empty."
    lines = []
    for r in rows:
        ts = time.strftime("%H:%M:%S", time.localtime(r["ts"]))
        detail = f"\n    {r['detail']}" if r["detail"] else ""
        lines.append(f"[{ts}] ({r['event_type']}) {r['summary']}{detail}")
    return f"Working memory ({len(rows)} recent events):\n" + "\n".join(lines)


def wm_get(limit: int = MAX_ENTRIES) -> str:
    """Alias for wm_list, kept aligned with prompts/docs."""
    return wm_list(limit)


def wm_clear() -> str:
    """Clear all working memory entries."""
    if not _db_path:
        return "Working memory not initialized."
    with _conn() as conn:
        n = conn.execute("DELETE FROM working_memory").rowcount
    return f"Working memory cleared ({n} entries removed)."


# ─── Tool definitions ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "wm_add",
        "description": "Add a short event to working memory for the current session.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Short event summary"},
                "detail": {"type": "string", "default": "", "description": "Optional detail"},
                "event_type": {"type": "string", "default": "action", "description": "Event type, e.g. user/tool/action/error"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "wm_get",
        "description": "Show recent working memory entries. Alias for wm_list.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "How many recent events to show"},
            },
        },
    },
    {
        "name": "wm_list",
        "description": (
            "Show recent working memory — the last actions, tool calls, and results from this session. "
            "Use this to recall what just happened or what was recently done."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "How many recent events to show"},
            },
        },
    },
    {
        "name": "wm_clear",
        "description": "Clear the working memory (short-term recent activity buffer).",
        "parameters": {"type": "object", "properties": {}},
    },
]

HANDLERS: dict = {
    "wm_add":   lambda summary, detail="", event_type="action": wm_add(summary, detail, event_type),
    "wm_get":   lambda limit=20: wm_get(int(limit)),
    "wm_list":  lambda limit=20: wm_list(int(limit)),
    "wm_clear": lambda **_: wm_clear(),
}
