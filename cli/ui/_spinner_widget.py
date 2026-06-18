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
        self._current_pct: float = 0.0
        self._target_pct: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, label: str = "Thinking…", target_pct: float = 10.0) -> None:
        """Start the spinner and progress animation with the given label and target pct."""
        with self._lock:
            if not self._running:
                initial_pct = 0.0
                if hasattr(self._layout, "agent") and self._layout.agent is not None:
                    initial_pct = getattr(self._layout.agent, "_session_progress", 0.0)
                self._current_pct = initial_pct
                self._running = True
                self._spinner_line_active = True
            self._label = label
            self._target_pct = target_pct
            self._update_status_bar()

        if self._thread is None or not self._thread.is_alive():
            # Launch the animation thread
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()

    def update(self, label: str, target_pct: Optional[float] = None) -> None:
        """Change the label and target percentage while it's running."""
        with self._lock:
            self._label = label
            if target_pct is not None:
                self._target_pct = target_pct
            self._update_status_bar()

    def set_target(self, target_pct: float, label: Optional[str] = None) -> None:
        """Set a new target percentage and optional label."""
        with self._lock:
            self._target_pct = target_pct
            if label is not None:
                self._label = label
            self._update_status_bar()

    def stop(self) -> None:
        """Stop the spinner animation."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            if hasattr(self._layout, "agent") and self._layout.agent is not None:
                self._layout.agent._session_progress = self._current_pct

        # Wait for the animation thread to finish
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None

        with self._lock:
            self._spinner_line_active = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_status_bar(self, char: str = "⠋") -> None:
        """Render status text combining the progress bar, percentage, spinner, and label."""
        pct_int = int(self._current_pct)
        width = 10
        filled_width = (pct_int * width) / 100.0
        full_blocks = int(filled_width)
        fraction = filled_width - full_blocks
        
        if fraction <= 0:
            frac_char = ""
        else:
            char_idx = int(fraction * 8)
            frac_char = " ▏▎▍▌▋▊▉█"[char_idx]
            
        empty_blocks = width - full_blocks - (1 if frac_char else 0)
        filled_part = "\033[36m" + "█" * full_blocks + frac_char + "\033[0m"
        empty_part = "\033[90m" + "░" * empty_blocks + "\033[0m"
        
        status_text = f"{filled_part}{empty_part} \033[36m{pct_int}%\033[0m \033[36m{char}\033[0m \033[90m{self._label}\033[0m"
        if self._format_status:
            status_text = self._format_status(status_text)
        self._layout.set_status(status_text)

    def _animate(self) -> None:
        """Background thread: smoothly interpolates progress percentage and updates status bar."""
        chars = itertools.cycle(_CHARS)
        while True:
            with self._lock:
                if not self._running:
                    break
                # Smooth interpolation towards target
                if self._current_pct < self._target_pct:
                    self._current_pct = min(self._target_pct, self._current_pct + 2.0)
                elif self._current_pct > self._target_pct:
                    self._current_pct = max(self._target_pct, self._current_pct - 2.0)
                char = next(chars)
                self._update_status_bar(char)
            time.sleep(0.05)

