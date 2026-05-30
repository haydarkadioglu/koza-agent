"""Shared sub-agent registry (module-level singleton)."""
import threading

_subagents: dict[str, dict] = {}
_registry_lock = threading.RLock()
