"""Output pane spinner widget — animates a spinner character in the status bar."""
from __future__ import annotations

import itertools
import threading
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ._layout import ChatLayout

_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_INTERVAL = 0.4  # 400ms update interval (balanced: smooth animation without input corruption)


class OutputSpinner:
    """Spinner that animates in the ChatLayout status bar.

    Instead of writing into the output pane (which causes overlap issues
    with other appended content), this spinner updates the status bar text
    with an animated braille character + label. The output pane only gets
    static one-time lines for events.

    Thread-safe: all state mutations are protected by a lock.
    """

    def __init__(self, layout: "ChatLayout") -> None:
        self._layout = layout
        self._lock = threading.Lock()
        self._running: bool = False
        self._label: str = ""
        self._thread: Optional[threading.Thread] = None
        # Callback to format the full status bar text (set by StreamRenderer)
        self._format_status = None
        self._spinner_line_active: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, label: str = "Thinking…") -> None:
        """Start the spinner animation with the given label."""
        with self._lock:
            if self._running:
                # Already running — just update the label
                self._label = label
                return
            self._label = label
            self._running = True
            self._spinner_line_active = True

        # Launch the animation thread
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def update(self, label: str) -> None:
        """Change the spinner label while it's running."""
        with self._lock:
            self._label = label

    def stop(self) -> None:
        """Stop the spinner animation."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        # Wait for the animation thread to finish
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None

        with self._lock:
            self._spinner_line_active = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _animate(self) -> None:
        """Background thread: cycles through spinner chars, updating status bar."""
        for char in itertools.cycle(_CHARS):
            with self._lock:
                if not self._running:
                    break
                label = self._label

            # Update the status bar with the animated spinner character
            status_text = f"\033[36m{char}\033[0m \033[90m{label}\033[0m"
            if self._format_status:
                status_text = self._format_status(status_text)
            self._layout.set_status(status_text)
            time.sleep(_INTERVAL)
