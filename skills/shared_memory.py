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


# ─── Credential vault — stored in ~/.Koza/.env ───────────────────────────────
# Tokens/keys are NEVER injected into the system prompt; the agent calls
# credential_get() on demand so secrets don't leak into every LLM turn.

import re as _re
from pathlib import Path as _Path


def _env_path() -> _Path:
    return _Path.home() / ".Koza" / ".env"


def _service_to_key(service: str) -> str:
    """'openai api key' → 'OPENAI_API_KEY'"""
    return _re.sub(r"[^a-zA-Z0-9]+", "_", service.strip()).upper().strip("_")


def _read_env() -> dict[str, tuple[str, str]]:
    """Return {ENV_KEY: (value, notes)} parsed from ~/.Koza/.env"""
    p = _env_path()
    if not p.exists():
        return {}
    result: dict[str, tuple[str, str]] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, rest = stripped.partition("=")
        key = key.strip()
        if "  #" in rest:
            value, _, notes = rest.partition("  #")
            result[key] = (value.strip(), notes.strip())
        else:
            result[key] = (rest.strip(), "")
    return result


def _write_env(data: dict[str, tuple[str, str]]) -> None:
    """Write {ENV_KEY: (value, notes)} to ~/.Koza/.env"""
    p = _env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key in sorted(data):
        value, notes = data[key]
        lines.append(f"{key}={value}  # {notes}" if notes else f"{key}={value}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def credential_set(service: str, token: str, notes: str = "") -> str:
    """Save or update a credential in ~/.Koza/.env"""
    env_key = _service_to_key(service)
    data = _read_env()
    data[env_key] = (token, notes)
    _write_env(data)
    return f"✅ Saved {env_key} to ~/.Koza/.env"


def credential_get(service: str) -> str:
    """Look up a credential from ~/.Koza/.env by service name."""
    env_key = _service_to_key(service)
    data = _read_env()
    # Exact match
    if env_key in data:
        value, notes = data[env_key]
        return f"{env_key}={value}" + (f"  # {notes}" if notes else "")
    # Fuzzy: check if service substring appears in any key
    lower = service.lower().replace(" ", "_")
    matches = [(k, v, n) for k, (v, n) in data.items() if lower in k.lower()]
    if matches:
        return "\n".join(
            f"{k}={v}" + (f"  # {n}" if n else "") for k, v, n in matches
        )
    return f"No credential found for '{service}' in ~/.Koza/.env"


def credential_list() -> str:
    """List all credential keys stored in ~/.Koza/.env (names only, not values)."""
    data = _read_env()
    if not data:
        return f"No credentials stored in {_env_path()} yet."
    lines = [f"  🔑 {k}" + (f"  # {n}" if n else "") for k, (_, n) in sorted(data.items())]
    return f"Stored credentials in ~/.Koza/.env ({len(data)}):\n" + "\n".join(lines)


def get_credential_context() -> str:
    """Return credential list summary (key names only, no values) — safe for logging."""
    data = _read_env()
    if not data:
        return ""
    keys = ", ".join(sorted(data.keys()))
    return f"## Credentials in ~/.Koza/.env (use credential_get to retrieve values):\n{keys}"


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
