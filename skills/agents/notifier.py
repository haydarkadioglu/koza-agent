"""Sub-agent completion notifier — singleton background watcher.

Any module (CLI, Telegram) can register a callback.
When a sub-agent's status transitions to 'done' or 'error',
all registered callbacks are invoked with the agent summary.

Usage:
    from skills.agents.notifier import SubAgentNotifier
    SubAgentNotifier.register(my_callback)   # callback(agent_id, status, goal, result)
    SubAgentNotifier.start()                 # idempotent — safe to call multiple times
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from ._registry import _subagents

_POLL_INTERVAL = 2.0  # seconds

Callback = Callable[[str, str, str, str], None]
# callback(agent_id: str, status: str, goal: str, result: str) -> None


class SubAgentNotifier:
    _started: bool = False
    _lock: threading.Lock = threading.Lock()
    _callbacks: list[Callback] = []
    _notified: set[str] = set()  # agent_ids already notified

    @classmethod
    def register(cls, cb: Callback) -> None:
        """Register a callback to be called on sub-agent completion."""
        with cls._lock:
            if cb not in cls._callbacks:
                cls._callbacks.append(cb)

    @classmethod
    def unregister(cls, cb: Callback) -> None:
        with cls._lock:
            cls._callbacks = [c for c in cls._callbacks if c is not cb]

    @classmethod
    def start(cls) -> None:
        """Start the watcher thread (idempotent)."""
        with cls._lock:
            if cls._started:
                return
            cls._started = True
            
            # Pre-populate notified list with all currently finished subagents
            # so we don't spam the user with historical completions on startup.
            for agent_id, ag in _subagents.items():
                if ag.get("status") in ("done", "error"):
                    cls._notified.add(agent_id)
                    
        t = threading.Thread(target=cls._watch, daemon=True, name="subagent-notifier")
        t.start()

    @classmethod
    def _watch(cls) -> None:
        while True:
            time.sleep(_POLL_INTERVAL)
            try:
                # snapshot to avoid dict-changed-during-iteration
                agents = dict(_subagents)
                for agent_id, ag in agents.items():
                    status = ag.get("status", "")
                    if status in ("done", "error") and agent_id not in cls._notified:
                        with cls._lock:
                            cls._notified.add(agent_id)
                            cbs = list(cls._callbacks)
                        goal = ag.get("goal", "")
                        result = ag.get("result", "")[:300]
                        for cb in cbs:
                            try:
                                cb(agent_id, status, goal, result)
                            except Exception:
                                pass
            except Exception:
                pass
