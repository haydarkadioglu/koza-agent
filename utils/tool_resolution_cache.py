"""Bounded memo for one turn's tool resolution.

The conversation loop re-resolves the tool list every round, and most rounds
change nothing. Entries are evicted in insertion order and lists are copied on
the way in and out, so a caller can never corrupt a stored selection.

``context`` carries whatever else the resolved list depends on; it must be
hashable and defaults to None.
"""
from __future__ import annotations


class ToolResolutionCache:
    def __init__(self, max_entries: int = 4) -> None:
        self._max_entries = max_entries
        self._entries: dict[tuple, list[dict]] = {}

    @staticmethod
    def _key(generation: int, groups, input_text: str,
             previous_names: tuple[str, ...], context) -> tuple:
        return (generation, frozenset(groups or ()), input_text, previous_names, context)

    def get(self, generation: int, groups, input_text: str,
            previous_names: tuple[str, ...], *, context=None) -> list[dict] | None:
        """Return a copy of the memoized tool list, or None on a miss."""
        tools = self._entries.get(self._key(generation, groups, input_text, previous_names, context))
        return None if tools is None else list(tools)

    def put(self, generation: int, groups, input_text: str,
            previous_names: tuple[str, ...], tools: list[dict], *, context=None) -> None:
        """Remember a copy of `tools`, evicting the oldest entries past the bound."""
        self._entries[self._key(generation, groups, input_text, previous_names, context)] = list(tools)
        while len(self._entries) > self._max_entries:
            self._entries.pop(next(iter(self._entries)))

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
