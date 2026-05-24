"""Chat layout using prompt_toolkit's split-pane terminal UI."""
from __future__ import annotations

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

        # Multi-line input widget with dynamic height (1–5 lines)
        self.input_area: TextArea = TextArea(
            multiline=True,
            prompt=self._get_prompt_text,
            accept_handler=self._on_accept,
            height=Dimension(min=1, max=5),
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
        """Update the input prompt indicator based on agent state."""
        self._prompt_busy = busy
        if self._app and self._app.is_running:
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
        """Thread-safe append to the output pane. Supports ANSI escape codes."""
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
                loop.call_soon_threadsafe(_update)
                loop.call_soon_threadsafe(self._app.invalidate)
            else:
                _update()
        else:
            _update()

    def clear_output(self) -> None:
        """Clear the output pane."""
        self._output_text = ""
        if self._app and self._app.is_running:
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
