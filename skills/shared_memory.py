"""Shared Memory — cross-session, cross-agent persistent knowledge store.

All agents (parent + sub-agents, any session) share the same SQLite table
in koza.db. Sub-agents automatically load relevant memories into their
context when spawned.
"""
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
            CREATE TABLE IF NOT EXISTS shared_memory (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                key        TEXT NOT NULL UNIQUE,
                value      TEXT NOT NULL,
                tags       TEXT NOT NULL DEFAULT '',
                source     TEXT NOT NULL DEFAULT 'user',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shm_key  ON shared_memory(key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shm_tags ON shared_memory(tags)")


@contextmanager
def _conn():
    conn = sqlite3.connect(_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ─── Core operations ─────────────────────────────────────────────────────────

def memory_store(key: str, value: str, tags: str = "", source: str = "agent") -> str:
    """Store or update a fact/memory by key. Accessible to all agents and sessions."""
    if not _db_path:
        return "Shared memory DB not initialized."
    now = time.time()
    with _conn() as conn:
        existing = conn.execute(
            "SELECT id FROM shared_memory WHERE key = ?", (key,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE shared_memory SET value=?, tags=?, source=?, updated_at=? WHERE key=?",
                (value, tags, source, now, key),
            )
            return f"✅ Memory updated: '{key}'"
        else:
            conn.execute(
                "INSERT INTO shared_memory (key, value, tags, source, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (key, value, tags, source, now, now),
            )
            return f"✅ Memory stored: '{key}'"


def memory_recall(key: str) -> str:
    """Recall a specific memory by exact key."""
    if not _db_path:
        return "Shared memory DB not initialized."
    with _conn() as conn:
        row = conn.execute(
            "SELECT key, value, tags, source, updated_at FROM shared_memory WHERE key = ?",
            (key,)
        ).fetchone()
    if not row:
        return f"No memory found for key: '{key}'"
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["updated_at"]))
    return f"🧠 [{row['key']}] (tags: {row['tags'] or 'none'}, by: {row['source']}, updated: {ts})\n{row['value']}"


def memory_search(query: str, limit: int = 10) -> str:
    """Search shared memory by keyword across keys, values, and tags."""
    if not _db_path:
        return "Shared memory DB not initialized."
    q = f"%{query.lower()}%"
    with _conn() as conn:
        rows = conn.execute(
            """SELECT key, value, tags, source, updated_at FROM shared_memory
               WHERE lower(key) LIKE ? OR lower(value) LIKE ? OR lower(tags) LIKE ?
               ORDER BY updated_at DESC LIMIT ?""",
            (q, q, q, limit),
        ).fetchall()
    if not rows:
        return f"No memories found matching '{query}'."
    lines = []
    for r in rows:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["updated_at"]))
        snippet = r["value"][:120].replace("\n", " ")
        lines.append(f"🧠 [{r['key']}] ({r['tags'] or 'no tags'}) [{ts}]\n   {snippet}")
    return f"Found {len(rows)} memor{'y' if len(rows)==1 else 'ies'} for '{query}':\n\n" + "\n\n".join(lines)


def memory_list(tags: str = "", limit: int = 30) -> str:
    """List all shared memories, optionally filtered by tag."""
    if not _db_path:
        return "Shared memory DB not initialized."
    with _conn() as conn:
        if tags:
            rows = conn.execute(
                "SELECT key, tags, source, updated_at FROM shared_memory WHERE tags LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (f"%{tags}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, tags, source, updated_at FROM shared_memory ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    if not rows:
        return "No shared memories stored yet."
    lines = []
    for r in rows:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["updated_at"]))
        lines.append(f"  [{ts}] {r['key']}  (tags: {r['tags'] or '-'}, by: {r['source']})")
    header = f"Shared memory ({len(rows)} entries{f', tag={tags}' if tags else ''}):"
    return header + "\n" + "\n".join(lines)


def memory_delete(key: str) -> str:
    """Delete a memory entry by key."""
    if not _db_path:
        return "Shared memory DB not initialized."
    with _conn() as conn:
        n = conn.execute("DELETE FROM shared_memory WHERE key = ?", (key,)).rowcount
    return f"✅ Deleted '{key}'" if n else f"Key '{key}' not found."


def get_relevant_context(query: str, limit: int = 5) -> str:
    """Return a compact memory context string for injecting into sub-agent prompts."""
    if not _db_path:
        return ""
    q = f"%{query.lower()}%"
    with _conn() as conn:
        rows = conn.execute(
            """SELECT key, value FROM shared_memory
               WHERE lower(key) LIKE ? OR lower(value) LIKE ? OR lower(tags) LIKE ?
               ORDER BY updated_at DESC LIMIT ?""",
            (q, q, q, limit),
        ).fetchall()
    if not rows:
        # Fall back to most recent entries
        with _conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM shared_memory ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    if not rows:
        return ""
    lines = [f"- [{r['key']}]: {r['value'][:200]}" for r in rows]
    return "## Shared Memory (relevant facts):\n" + "\n".join(lines)


def get_credential_context() -> str:
    """Return ALL stored credentials — always injected into system prompt regardless of query."""
    if not _db_path:
        return ""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT key, value FROM shared_memory WHERE tags LIKE '%credential%' ORDER BY updated_at DESC",
        ).fetchall()
    if not rows:
        return ""
    lines = [f"- [{r['key']}]: {r['value']}" for r in rows]
    return "## Credential Vault (API keys & tokens you have been given):\n" + "\n".join(lines)


# ─── Credential vault helpers ─────────────────────────────────────────────────

def credential_set(service: str, token: str, notes: str = "") -> str:
    """Store or update a credential/token in the vault."""
    key = f"credential.{service.lower().replace(' ', '_')}"
    value = token if not notes else f"{token}  # {notes}"
    return memory_store(key, value, tags="credential", source="user")


def credential_get(service: str) -> str:
    """Retrieve a stored credential/token by service name."""
    key = f"credential.{service.lower().replace(' ', '_')}"
    result = memory_recall(key)
    if "No memory found" in result:
        # Fuzzy fallback: search for the service name in credentials
        return memory_search(service, limit=3)
    return result


def credential_list() -> str:
    """List all stored credentials (service names only, not values)."""
    if not _db_path:
        return "Shared memory DB not initialized."
    with _conn() as conn:
        rows = conn.execute(
            "SELECT key, updated_at FROM shared_memory WHERE tags LIKE '%credential%' ORDER BY updated_at DESC"
        ).fetchall()
    if not rows:
        return "No credentials stored yet."
    lines = []
    for r in rows:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["updated_at"]))
        lines.append(f"  🔑 {r['key']}  (saved: {ts})")
    return f"Stored credentials ({len(rows)}):\n" + "\n".join(lines)


# ─── Tool definitions ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "memory_store",
        "description": (
            "Store a fact, preference, or piece of knowledge in shared memory. "
            "Persists across sessions and is accessible to all sub-agents. "
            "Use a descriptive key like 'user.email', 'project.goal', 'api.endpoint'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key":   {"type": "string", "description": "Unique key for this memory (e.g. 'user.name', 'task.deadline')"},
                "value": {"type": "string", "description": "Content to remember"},
                "tags":  {"type": "string", "description": "Comma-separated tags for grouping (e.g. 'user,profile')", "default": ""},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "memory_recall",
        "description": "Recall a specific memory by its exact key.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The memory key to look up"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "memory_search",
        "description": "Search shared memory by keyword across all keys, values, and tags. Use this to find what is known about a topic.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword or phrase"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_list",
        "description": "List all entries in shared memory, optionally filtered by tag.",
        "parameters": {
            "type": "object",
            "properties": {
                "tags":  {"type": "string", "default": "", "description": "Filter by tag (optional)"},
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "memory_delete",
        "description": "Delete a shared memory entry by key.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "credential_set",
        "description": (
            "Store or update an API key, token, password, or any credential in the secure vault. "
            "Call this immediately whenever the user provides any token, key, or credential — "
            "even mid-conversation. The vault persists forever across all sessions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name (e.g. 'openai', 'telegram_bot', 'github', 'spotify')"},
                "token":   {"type": "string", "description": "The actual token/key/password value"},
                "notes":   {"type": "string", "description": "Optional notes (e.g. 'read-only', 'bot token')", "default": ""},
            },
            "required": ["service", "token"],
        },
    },
    {
        "name": "credential_get",
        "description": (
            "Retrieve a stored API key, token, or credential by service name. "
            "ALWAYS call this BEFORE asking the user for any credential — "
            "they may have provided it before."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name to look up (e.g. 'openai', 'telegram_bot')"},
            },
            "required": ["service"],
        },
    },
    {
        "name": "credential_list",
        "description": "List all stored credentials (service names only, values hidden). Use to see what credentials are already saved.",
        "parameters": {"type": "object", "properties": {}},
    },
]

HANDLERS: dict = {
    "memory_store":    lambda key, value, tags="": memory_store(key, value, tags),
    "memory_recall":   lambda key: memory_recall(key),
    "memory_search":   lambda query, limit=10: memory_search(query, int(limit)),
    "memory_list":     lambda tags="", limit=30: memory_list(tags, int(limit)),
    "memory_delete":   lambda key: memory_delete(key),
    "credential_set":  lambda service, token, notes="": credential_set(service, token, notes),
    "credential_get":  lambda service: credential_get(service),
    "credential_list": lambda: credential_list(),
}
