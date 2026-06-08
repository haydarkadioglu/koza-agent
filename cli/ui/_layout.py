"""Chat layout using prompt_toolkit's split-pane terminal UI."""
from __future__ import annotations

import shutil
import threading
import time
from typing import Callable, Optional

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.completion import WordCompleter

_SLASH_CMDS = [
    "/help", "/sessions", "/save", "/title", "/clear", "/retry", "/undo",
    "/provider", "/model", "/kanban", "/memory", "/tools",
    "/plugins", "/skills", "/compress", "/reset",
    "/mode coding", "/mode off", "/swarm", "/self-improve",
]


_MAX_OUTPUT_LINES = 10_000

# Minimum interval (seconds) between UI invalidation calls during streaming
_INVALIDATE_MIN_INTERVAL = 0.1  # 100ms

def _sanitize_ansi(text: str) -> str:
    if not text:
        return ""
    # Replace single-byte CSI character \x9b with visual angle quote ›
    # to prevent prompt_toolkit from crashing on misdecoded CP1252/CP1254 characters on Windows.
    return text.replace("\x9b", "›")


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

        # Lock protecting _output_text mutations from multiple threads.
        # We do NOT dispatch text updates to the event loop — instead we
        # mutate _output_text under this lock and let the next invalidate
        # pick up the new content when the FormattedTextControl lambda runs.
        self._text_lock = threading.Lock()

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
            history=InMemoryHistory(),
            focusable=True,
            completer=WordCompleter(_SLASH_CMDS, ignore_case=True),
            complete_while_typing=True,
        )
        # Attach custom key bindings to the TextArea's BufferControl
        self.input_area.control.key_bindings = self._create_input_bindings()

        # Application reference (set later when Application is created)
        self._app: Optional["Application"] = None  # noqa: F821

    def _create_input_bindings(self) -> KeyBindings:
        """Create key bindings for the input area.

        Enter submits the input. Shift+Enter / Escape+Enter inserts a newline.
        Up/Down navigate input history when the buffer has a single line.
        """
        from prompt_toolkit.filters import is_done

        kb = KeyBindings()

        @kb.add("enter", eager=True, filter=~is_done)
        def _submit(event):
            """Submit on Enter — override multiline's default newline."""
            buf = event.current_buffer
            if buf.complete_state:
                buf.complete_state = None
                return
            buf.validate_and_handle()

        @kb.add("escape", "enter")
        @kb.add("c-j")   # Shift+Enter on many terminals
        def _newline(event):
            """Insert newline on Shift+Enter / Escape+Enter."""
            event.current_buffer.insert_text("\n")

        @kb.add("up", eager=True)
        def _history_prev(event):
            """Navigate to previous history entry when on first line."""
            buf = event.current_buffer
            # Only navigate history if cursor is on the first line
            if buf.document.cursor_position_row == 0:
                buf.history_backward(count=1)
            else:
                buf.cursor_up(count=1)

        @kb.add("down", eager=True)
        def _history_next(event):
            """Navigate to next history entry when on last line."""
            buf = event.current_buffer
            row = buf.document.cursor_position_row
            line_count = len(buf.document.lines)
            if row == line_count - 1:
                buf.history_forward(count=1)
            else:
                buf.cursor_down(count=1)

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
        # Render-frame snapshot — set by content lambda, read by cursor lambda.
        # Both run on the event-loop (render) thread in the same frame so this
        # is safe without a lock; the snapshot prevents the cursor y-position
        # from referencing lines that don't exist in the already-rendered content.
        self._render_snapshot: str = ""

        def _output_content():
            with self._text_lock:
                self._render_snapshot = self._output_text
            if not self._render_snapshot:
                return ""
            try:
                return ANSI(_sanitize_ansi(self._render_snapshot))
            except Exception:
                return self._render_snapshot.replace("\x1b", "").replace("\x9b", "")

        def _cursor_pos():
            if not self._auto_scroll:
                return None
            n = self._render_snapshot.count("\n")
            return Point(x=0, y=n)

        output_window = Window(
            content=FormattedTextControl(
                _output_content,
                get_cursor_position=_cursor_pos,
            ),
            wrap_lines=True,
            allow_scroll_beyond_bottom=True,
        )

        # Middle: status bar
        def _status_content():
            if not self.status_text:
                return ""
            try:
                return ANSI(_sanitize_ansi(self.status_text))
            except Exception:
                return self.status_text.replace("\x1b", "").replace("\x9b", "")

        status_bar = Window(
            content=FormattedTextControl(_status_content),
            height=Dimension.exact(1),
        )

        # Bottom: input area with Unicode box-drawing border frame (responsive width)
        def _border_top():
            w = max(40, shutil.get_terminal_size((80, 24)).columns - 4)
            return ANSI(f"\033[90m┌{'─' * w}┐\033[0m")

        def _border_bot():
            w = max(40, shutil.get_terminal_size((80, 24)).columns - 4)
            return ANSI(f"\033[90m└{'─' * w}┘\033[0m")

        framed_input = HSplit([
            Window(content=FormattedTextControl(_border_top), height=Dimension.exact(1)),
            self.input_area,
            Window(content=FormattedTextControl(_border_bot), height=Dimension.exact(1)),
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

        Text is buffered immediately under a lock (no data loss), but UI
        invalidation is throttled to at most once per _INVALIDATE_MIN_INTERVAL
        seconds. This prevents excessive redraws at high token rates (50+
        tokens/sec) which can corrupt the input buffer cursor position.

        IMPORTANT: We do NOT dispatch the text mutation to the event loop.
        Dispatching via call_soon_threadsafe causes the event loop to process
        the mutation inline, which changes FormattedTextControl content and
        triggers prompt_toolkit's internal layout recalculation — resetting
        the input Buffer cursor. Instead, we mutate _output_text under a lock
        and schedule a throttled invalidate. The next render cycle picks up
        the new content safely (FormattedTextControl lambdas are called from
        the render thread which is the event loop thread).
        """
        with self._text_lock:
            self._output_text += text
            self._auto_scroll = True  # Follow new content
            # Trim oldest lines when buffer exceeds the maximum
            lines = self._output_text.split('\n')
            if len(lines) > _MAX_OUTPUT_LINES:
                self._output_text = '\n'.join(lines[-_MAX_OUTPUT_LINES:])

        if self._app and self._app.is_running:
            self._schedule_throttled_invalidate()

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
        with self._text_lock:
            self._output_text = ""
        if self._app and self._app.is_running:
            loop = self._app.loop
            if loop is not None:
                loop.call_soon_threadsafe(self._app.invalidate)
            else:
                self._app.invalidate()

    def set_status(self, text: str) -> None:
        """Update the status bar text. Supports ANSI codes. Thread-safe.

        Uses the same throttled invalidation as append_output to prevent
        excessive redraws from the spinner (every 200ms) and per-token
        status updates from corrupting the input buffer.
        """
        self.status_text = text
        if self._app and self._app.is_running:
            self._schedule_throttled_invalidate()
