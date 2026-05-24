"""Chat layout using prompt_toolkit's split-pane terminal UI."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import TextArea


_MAX_OUTPUT_LINES = 10_000

# Minimum interval (seconds) between UI invalidation calls during streaming
_INVALIDATE_MIN_INTERVAL = 0.1  # 100ms


class ChatLayout:
    """Terminal UI layout: scrollable output pane + status bar + framed input bar."""

    def __init__(self, on_submit: Callable[[str], None]) -> None:
        self.on_submit: Callable[[str], None] = on_submit

        # Output content as plain text with ANSI codes
        self._output_text: str = ""

        # Status bar content (may contain ANSI codes)
        self.status_text: str = ""

        # Dynamic prompt indicator
        self._prompt_busy: bool = False

        # Throttled invalidation state: limits UI redraws to at most once
        # per _INVALIDATE_MIN_INTERVAL seconds during high-frequency streaming.
        self._invalidate_lock = threading.Lock()
        self._last_invalidate_time: float = 0.0
        self._invalidate_timer: Optional[threading.Timer] = None
        self._pending_invalidate: bool = False

        # Multi-line input widget with dynamic height (1–5 lines)
        # dont_extend_height=True prevents prompt_toolkit from recalculating
        # the input area height during layout invalidation (e.g. when output
        # pane content changes), which would otherwise reset the Buffer cursor
        # position and cause typed text to disappear while the agent is streaming.
        self.input_area: TextArea = TextArea(
            multiline=True,
            prompt=self._get_prompt_text,
            accept_handler=self._on_accept,
            height=Dimension(min=1, max=5),
            dont_extend_height=True,
        )
        # Attach custom key bindings to the TextArea's BufferControl
        self.input_area.control.key_bindings = self._create_input_bindings()

        # Application reference (set later when Application is created)
        self._app: Optional["Application"] = None  # noqa: F821

    def _create_input_bindings(self) -> KeyBindings:
        """Create key bindings for the input area.

        Enter submits the input (calls validate_and_handle which triggers
        the accept_handler). Escape+Enter (Meta+Enter) inserts a newline
        for multi-line composition.
        """
        from prompt_toolkit.filters import is_done

        kb = KeyBindings()

        @kb.add("enter", eager=True, filter=~is_done)
        def _submit(event):
            """Submit on Enter — override multiline's default newline.
            Works even after paste (bracketed paste mode)."""
            buf = event.current_buffer
            # If completion menu is open, dismiss it first
            if buf.complete_state:
                buf.complete_state = None
                return
            buf.validate_and_handle()

        @kb.add("escape", "enter")
        def _newline(event):
            """Insert newline on Escape+Enter (Meta+Enter / Shift+Enter)."""
            event.current_buffer.insert_text("\n")

        return kb

    def _get_prompt_text(self):
        """Return dynamic prompt text with color based on busy state."""
        if self._prompt_busy:
            return ANSI("\033[33m◌\033[0m › ")
        return ANSI("\033[32m●\033[0m › ")

    def set_prompt_indicator(self, busy: bool) -> None:
        """Update the input prompt indicator based on agent state. Thread-safe."""
        self._prompt_busy = busy
        if self._app and self._app.is_running:
            loop = self._app.loop
            if loop is not None:
                loop.call_soon_threadsafe(self._app.invalidate)
            else:
                self._app.invalidate()

    def _on_accept(self, buff: Buffer) -> bool:
        """Handle Enter press in the input area."""
        text = buff.text
        self.on_submit(text)
        buff.reset(Document(""))
        return False

    def create_layout(self) -> Layout:
        """Build the HSplit layout with output + status + framed input.

        Layout:
        ┌─────────────────────────────────────┐
        │  (scrollable output with ANSI)      │
        │  ...                                │
        ├─────────────────────────────────────┤
        │  ● Idle │ model │ tokens │ time     │  ← status bar
        ├─────────────────────────────────────┤
        │  ┌──────────────────────────────┐   │
        │  │ ● › user input here          │   │  ← framed input
        │  └──────────────────────────────┘   │
        └─────────────────────────────────────┘
        """
        # Top: scrollable output window with ANSI color support
        # _auto_scroll flag: True = follow new content, False = user scrolled up
        self._auto_scroll = True

        output_window = Window(
            content=FormattedTextControl(
                lambda: ANSI(self._output_text) if self._output_text else "",
                get_cursor_position=lambda: Point(
                    x=0, y=self._output_text.count("\n")
                ) if self._auto_scroll else None,
            ),
            wrap_lines=True,
            allow_scroll_beyond_bottom=True,
        )

        # Middle: status bar
        status_bar = Window(
            content=FormattedTextControl(
                lambda: ANSI(self.status_text) if self.status_text else "",
            ),
            height=Dimension.exact(1),
        )

        # Bottom: input area with Unicode box-drawing border frame
        framed_input = HSplit([
            Window(content=FormattedTextControl(
                lambda: ANSI("\033[90m┌" + "─" * 60 + "┐\033[0m")
            ), height=Dimension.exact(1)),
            self.input_area,
            Window(content=FormattedTextControl(
                lambda: ANSI("\033[90m└" + "─" * 60 + "┘\033[0m")
            ), height=Dimension.exact(1)),
        ])

        container = HSplit(
            [
                output_window,       # scrollable output (takes remaining space)
                status_bar,          # status bar (1 line) — acts as separator
                framed_input,        # input (1 line)
            ]
        )

        return Layout(container, focused_element=self.input_area)

    def append_output(self, text: str) -> None:
        """Thread-safe append to the output pane with throttled invalidation.

        Text is buffered immediately (no data loss), but UI invalidation is
        throttled to at most once per _INVALIDATE_MIN_INTERVAL seconds. This
        prevents excessive redraws at high token rates (50+ tokens/sec) which
        can corrupt the input buffer cursor position.
        """
        def _update() -> None:
            self._output_text += text
            self._auto_scroll = True  # Follow new content
            # Trim oldest lines when buffer exceeds the maximum
            lines = self._output_text.split('\n')
            if len(lines) > _MAX_OUTPUT_LINES:
                self._output_text = '\n'.join(lines[-_MAX_OUTPUT_LINES:])

        if self._app and self._app.is_running:
            loop = self._app.loop
            if loop is not None:
                # Always update the text buffer immediately (thread-safe via event loop)
                loop.call_soon_threadsafe(_update)
                # Throttle invalidation: only trigger a redraw if enough time has passed
                self._schedule_throttled_invalidate()
            else:
                _update()
        else:
            _update()

    def _schedule_throttled_invalidate(self) -> None:
        """Schedule an invalidate call, throttled to _INVALIDATE_MIN_INTERVAL.

        If called within the interval since the last invalidate, a timer is set
        to fire at the end of the interval. Multiple calls within the same
        interval coalesce into a single deferred invalidate.
        """
        with self._invalidate_lock:
            now = time.monotonic()
            elapsed = now - self._last_invalidate_time

            if elapsed >= _INVALIDATE_MIN_INTERVAL:
                # Enough time has passed — invalidate immediately
                self._last_invalidate_time = now
                self._pending_invalidate = False
                if self._invalidate_timer is not None:
                    self._invalidate_timer.cancel()
                    self._invalidate_timer = None
                self._do_invalidate()
            else:
                # Too soon — schedule a deferred invalidate if not already pending
                self._pending_invalidate = True
                if self._invalidate_timer is None:
                    delay = _INVALIDATE_MIN_INTERVAL - elapsed
                    self._invalidate_timer = threading.Timer(
                        delay, self._flush_invalidate
                    )
                    self._invalidate_timer.daemon = True
                    self._invalidate_timer.start()

    def _flush_invalidate(self) -> None:
        """Timer callback: perform the deferred invalidate."""
        with self._invalidate_lock:
            self._invalidate_timer = None
            if self._pending_invalidate:
                self._pending_invalidate = False
                self._last_invalidate_time = time.monotonic()
        self._do_invalidate()

    def _do_invalidate(self) -> None:
        """Actually trigger the UI invalidate via the event loop."""
        if self._app and self._app.is_running:
            loop = self._app.loop
            if loop is not None:
                loop.call_soon_threadsafe(self._app.invalidate)

    def clear_output(self) -> None:
        """Clear the output pane. Thread-safe."""
        self._output_text = ""
        if self._app and self._app.is_running:
            loop = self._app.loop
            if loop is not None:
                loop.call_soon_threadsafe(self._app.invalidate)
            else:
                self._app.invalidate()

    def set_status(self, text: str) -> None:
        """Update the status bar text. Supports ANSI codes. Thread-safe."""
        self.status_text = text
        if self._app and self._app.is_running:
            loop = self._app.loop
            if loop is not None:
                loop.call_soon_threadsafe(self._app.invalidate)
            else:
                self._app.invalidate()
