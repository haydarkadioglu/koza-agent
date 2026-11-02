"""User Profile skill — lets Koza take notes about the user and the user set personal rules.

Notes: Koza-authored observations about the user (e.g. "prefers dark mode").
Rules: User-authored directives that always apply (e.g. "always respond in Turkish").

Both are persisted in shared_memory with specific tags so they survive restarts.
get_user_context() is called by the Agent at init-time to inject them into the
system prompt automatically.
"""
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from skills import shared_memory

_RULE_PREFIX = "user.rule."
_NOTE_PREFIX = "user.note."
_KEY_PROBE_LIMIT = 100


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(1, value)


@dataclass(frozen=True)
class ProfileLimits:
    """Bounds for the user-profile block injected into every turn."""
    max_rules: int = 20
    max_notes: int = 20
    max_chars: int = 2000
    max_entry_chars: int = 280

    @classmethod
    def from_config(cls, cfg: Any) -> "ProfileLimits":
        """Read ``cfg["memory"]["user_profile"]``; bad or missing values use defaults."""
        default = cls()
        try:
            section = cfg.get("memory", {}).get("user_profile", {})
            if not isinstance(section, Mapping):
                return default
            return cls(**{
                name: _positive_int(section.get(name), getattr(default, name))
                for name in ("max_rules", "max_notes", "max_chars", "max_entry_chars")
            })
        except (AttributeError, TypeError):
            return default


def _load_limits() -> ProfileLimits:
    try:
        from config import load_config
        return ProfileLimits.from_config(load_config())
    except Exception:  # noqa: BLE001 - a broken config must never break a turn
        return ProfileLimits()


def _unique_key(prefix: str) -> str:
    """Millisecond key; on collision append -2, -3, ... (bounded probe)."""
    base = f"{prefix}{int(time.time() * 1000)}"
    if not shared_memory._db_path:
        return base
    try:
        with shared_memory._conn() as conn:
            for n in range(1, _KEY_PROBE_LIMIT + 1):
                key = base if n == 1 else f"{base}-{n}"
                if not conn.execute(
                    "SELECT 1 FROM shared_memory WHERE key = ?", (key,)
                ).fetchone():
                    return key
    except sqlite3.Error:
        pass  # fall through to the plain key; memory_store reports DB errors
    return base


def user_rule_add(rule: str) -> str:
    """Add or update a personal rule that Koza will always follow."""
    if not rule.strip():
        return "Rule text cannot be empty."
    key = _unique_key(_RULE_PREFIX)
    return shared_memory.memory_store(key, rule.strip(), tags="user,rule", source="user")


def user_note_add(note: str) -> str:
    """Record an observation about the user (called proactively by Koza)."""
    if not note.strip():
        return "Note text cannot be empty."
    key = _unique_key(_NOTE_PREFIX)
    return shared_memory.memory_store(key, note.strip(), tags="user,note", source="agent")


def user_profile_list() -> str:
    """List all user rules and notes."""
    if not shared_memory._db_path:
        return "User profile DB not initialized."
    with shared_memory._conn() as conn:
        rows = conn.execute(
            """SELECT key, value, source, updated_at FROM shared_memory
               WHERE tags LIKE '%user%'
               ORDER BY updated_at DESC, key DESC""",
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
    return shared_memory.memory_delete(key)


def _normalize(text: str) -> str:
    return " ".join(str(text or "").split())


def _dedupe(rows: list) -> list[str]:
    """Whitespace-squeezed values, newest first, identical (casefolded) text collapsed."""
    seen: set[str] = set()
    values: list[str] = []
    for r in rows:
        value = _normalize(r["value"])
        folded = value.casefold()
        if not value or folded in seen:
            continue
        seen.add(folded)
        values.append(value)
    return values


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def get_user_context(db_path: str = "", limits: ProfileLimits | None = None) -> str:
    """Return a bounded string of user rules + notes for injection into the system prompt.

    Newest entries win; limits come from ``memory.user_profile`` in config
    unless ``limits`` is given. Returns "" if there is nothing to inject.
    """
    if db_path and not shared_memory._db_path:
        shared_memory.init_db(db_path)
    if not shared_memory._db_path:
        return ""
    try:
        if limits is None:
            limits = _load_limits()
        with shared_memory._conn() as conn:
            rows = conn.execute(
                """SELECT key, value, updated_at FROM shared_memory
                   WHERE tags LIKE '%user%'
                   ORDER BY updated_at DESC, key DESC""",
            ).fetchall()
        if not rows:
            return ""
        sections = [
            ("## User Rules (always follow these):", "rule", limits.max_rules,
             _dedupe([r for r in rows if r["key"].startswith(_RULE_PREFIX)])),
            ("## Notes About This User:", "note", limits.max_notes,
             _dedupe([r for r in rows if r["key"].startswith(_NOTE_PREFIX)])),
        ]
        parts: list[str] = []
        used = 0
        for header, noun, cap, values in sections:
            if not values:
                continue
            # Build the section locally first; budget is committed only if it is
            # emitted, so an abandoned section cannot inflate `used`.
            section_cost = len(header) + 1
            if used + section_cost > limits.max_chars:
                continue
            kept: list[str] = []
            for value in values[:cap]:
                line = f"- {_truncate(value, limits.max_entry_chars)}"
                if used + section_cost + len(line) + 1 > limits.max_chars:
                    break
                kept.append(line)
                section_cost += len(line) + 1
            omitted = len(values) - len(kept)
            # The omitted marker is part of the budget too: drop the oldest kept
            # entries until it fits, so the block can never exceed max_chars.
            marker = ""
            while True:
                candidate = (
                    f"- (… {omitted} older {noun}{'' if omitted == 1 else 's'} omitted)"
                    if omitted else ""
                )
                if not candidate or used + section_cost + len(candidate) + 1 <= limits.max_chars:
                    marker = candidate
                    break
                if not kept:
                    marker = ""  # not even the marker fits: skip the section
                    break
                section_cost -= len(kept.pop()) + 1
                omitted += 1
            if not kept and not marker:
                continue
            used += section_cost + (len(marker) + 1 if marker else 0)
            parts.append(header)
            parts.extend(kept)
            if marker:
                parts.append(marker)
        return "\n".join(parts)
    except Exception:  # noqa: BLE001 - profile errors must never break a turn
        return ""


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
