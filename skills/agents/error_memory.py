"""Error memory — in-memory store for coding failure patterns within a session.

Scoped to a single CodingSession; cleared when the session ends.
Backend Developer reads this before writing code to avoid known bad patterns.
Test Engineer writes here when tests fail.
"""
import hashlib
import time
from typing import List, Dict


def _hash(pattern: str) -> str:
    return hashlib.sha256(pattern.strip().lower().encode()).hexdigest()[:16]


class ErrorMemory:
    """In-memory error store for one coding session."""

    def __init__(self) -> None:
        self._store: List[Dict] = []
        self._seen_hashes: set = set()

    def record_error(self, description: str, file_path: str = "", error_msg: str = "") -> int:
        """Record a new failure pattern. Deduplicates by pattern hash. Returns index."""
        h = _hash(description)
        if h in self._seen_hashes:
            return -1
        self._seen_hashes.add(h)
        entry = {
            "id":          len(self._store),
            "pattern_hash": h,
            "description": description,
            "file_path":   file_path,
            "error_msg":   error_msg,
            "timestamp":   time.time(),
            "resolved":    False,
        }
        self._store.append(entry)
        return entry["id"]

    def get_errors(self, limit: int = 10) -> List[Dict]:
        """Return recent unresolved error patterns (newest first)."""
        unresolved = [e for e in self._store if not e["resolved"]]
        return list(reversed(unresolved))[:limit]

    def mark_resolved(self, error_id: int) -> None:
        for e in self._store:
            if e["id"] == error_id:
                e["resolved"] = True
                return

    def clear(self) -> None:
        self._store.clear()
        self._seen_hashes.clear()

    def __len__(self) -> int:
        return len(self._store)

    @staticmethod
    def format_for_prompt(errors: List[Dict]) -> str:
        """Format error list as a readable prompt section for Backend Developer."""
        if not errors:
            return ""
        lines = ["[ERROR MEMORY] — Avoid these patterns:\n"]
        for e in errors:
            lines.append(f"• Pattern: {e['description']}")
            if e.get("file_path"):
                lines.append(f"  File: {e['file_path']}")
            if e.get("error_msg"):
                lines.append(f"  Error: {e['error_msg'][:120]}")
            lines.append("")
        return "\n".join(lines)


# ── Module-level helpers (backwards compat, use ErrorMemory class directly) ───

def format_for_prompt(errors: List[Dict]) -> str:
    return ErrorMemory.format_for_prompt(errors)
