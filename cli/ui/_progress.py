"""Animated progress bar widget using Unicode block characters.

Renders a sliding highlight animation in the status bar to indicate
long-running operations. Uses a daemon thread so the animation never
blocks user input or prevents clean process exit.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._layout import ChatLayout

_BAR_CHARS = "░▒▓█"
_WIDTH = 20


class ProgressBar:
    """Animated progress indicator using Unicode block characters.

    Usage::

        bar = ProgressBar(layout)
        bar.start("Working…")
        # ... long operation ...
        bar.stop()
    """

    def __init__(self, layout: "ChatLayout") -> None:
        self._layout = layout
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self, label: str = "Working…") -> None:
        """Begin the animation loop in a background daemon thread.

        If already running, this is a no-op.
        """
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(
            target=self._animate, args=(label,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the animation and join the background thread."""
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None

    @property
    def running(self) -> bool:
        """Return whether the progress bar is currently animating."""
        with self._lock:
            return self._running

    def _animate(self, label: str) -> None:
        """Animation loop — runs on a daemon thread.

        Renders a sliding 3-character highlight across a bar of ░ characters,
        updating the layout's status bar at ~10 fps.
        """
        pos = 0
        while True:
            with self._lock:
                if not self._running:
                    break
            bar = list("░" * _WIDTH)
            # Sliding highlight: 3 characters with increasing density
            for offset in range(3):
                idx = (pos + offset) % _WIDTH
                bar[idx] = _BAR_CHARS[min(offset + 1, 3)]
            rendered = "".join(bar)
            self._layout.set_status(f"\033[36m{rendered}\033[0m {label}")
            pos = (pos + 1) % _WIDTH
            time.sleep(0.1)
