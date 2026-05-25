"""User Profile skill — lets Koza take notes about the user and the user set personal rules.

Notes: Koza-authored observations about the user (e.g. "prefers dark mode").
Rules: User-authored directives that always apply (e.g. "always respond in Turkish").

Both are persisted in shared_memory with specific tags so they survive restarts.
get_user_context() is called by the Agent at init-time to inject them into the
system prompt automatically.
"""
import time
from skills.shared_memory import memory_store, memory_delete, _db_path, _conn, init_db

_RULE_PREFIX = "user.rule."
_NOTE_PREFIX = "user.note."


def user_rule_add(rule: str) -> str:
    """Add or update a personal rule that Koza will always follow."""
    if not rule.strip():
        return "Rule text cannot be empty."
    key = f"{_RULE_PREFIX}{int(time.time())}"
    return memory_store(key, rule.strip(), tags="user,rule", source="user")


def user_note_add(note: str) -> str:
    """Record an observation about the user (called proactively by Koza)."""
    if not note.strip():
        return "Note text cannot be empty."
    key = f"{_NOTE_PREFIX}{int(time.time())}"
    return memory_store(key, note.strip(), tags="user,note", source="agent")


def user_profile_list() -> str:
    """List all user rules and notes."""
    if not _db_path:
        return "User profile DB not initialized."
    with _conn() as conn:
        rows = conn.execute(
            """SELECT key, value, source, updated_at FROM shared_memory
               WHERE tags LIKE '%user%'
               ORDER BY key""",
        ).fetchall()
    if not rows:
        return "No user profile data yet."
    rules = [r for r in rows if r["key"].startswith(_RULE_PREFIX)]
    notes = [r for r in rows if r["key"].startswith(_NOTE_PREFIX)]
    lines = []
    if rules:
        lines.append("📋 **Your Rules:**")
        for r in rules:
            ts = time.strftime("%Y-%m-%d", time.localtime(r["updated_at"]))
            lines.append(f"  [{r['key']}] {r['value']}  (added {ts})")
    if notes:
        lines.append("\n🧠 **Koza's Notes About You:**")
        for r in notes:
            ts = time.strftime("%Y-%m-%d", time.localtime(r["updated_at"]))
            lines.append(f"  [{r['key']}] {r['value']}  [{ts}]")
    return "\n".join(lines)


def user_profile_delete(key: str) -> str:
    """Delete a user rule or note by its key."""
    return memory_delete(key)


def get_user_context(db_path: str = "") -> str:
    """Return a compact string of user rules + notes for injection into system prompt.
    Returns empty string if no data exists (so nothing is added to prompt).
    """
    if db_path and not _db_path:
        init_db(db_path)
    if not _db_path:
        return ""
    try:
        with _conn() as conn:
            rows = conn.execute(
                """SELECT key, value FROM shared_memory
                   WHERE tags LIKE '%user%'
                   ORDER BY key""",
            ).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    rules = [r for r in rows if r["key"].startswith(_RULE_PREFIX)]
    notes = [r for r in rows if r["key"].startswith(_NOTE_PREFIX)]
    parts = []
    if rules:
        parts.append("## User Rules (always follow these):")
        parts.extend(f"- {r['value']}" for r in rules)
    if notes:
        parts.append("## Notes About This User:")
        parts.extend(f"- {r['value']}" for r in notes)
    return "\n".join(parts)


TOOL_DEFINITIONS = [
    {
        "name": "user_rule_add",
        "description": (
            "Add a personal rule that Koza will always follow. "
            "Call this when the user says things like 'from now on always do X', "
            "'always respond in Y language', 'never do Z', etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "rule": {"type": "string", "description": "The rule to remember and follow"},
            },
            "required": ["rule"],
        },
    },
    {
        "name": "user_note_add",
        "description": (
            "Proactively record an observation about the user's preferences, habits, or context. "
            "Use this when you notice consistent patterns, preferences, or important facts about the user "
            "(e.g. 'User prefers Python over JavaScript', 'User works in Istanbul timezone')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "Observation about the user"},
            },
            "required": ["note"],
        },
    },
    {
        "name": "user_profile_list",
        "description": "List all user rules and notes Koza has recorded about this user.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "user_profile_delete",
        "description": "Delete a user rule or note by its key (get keys from user_profile_list).",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key of the rule/note to delete"},
            },
            "required": ["key"],
        },
    },
]

HANDLERS: dict = {
    "user_rule_add":      lambda rule: user_rule_add(rule),
    "user_note_add":      lambda note: user_note_add(note),
    "user_profile_list":  lambda: user_profile_list(),
    "user_profile_delete": lambda key: user_profile_delete(key),
}
