"""Chat layout using prompt_toolkit's split-pane terminal UI."""
from __future__ import annotations

from typing import Callable, Optional

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI
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

        # Fixed-bottom input widget with single-line entry
        self.input_area: TextArea = TextArea(
            multiline=False,
            prompt=self._get_prompt_text,
            accept_handler=self._on_accept,
            height=Dimension.exact(1),
        )

        # Application reference (set later when Application is created)
        self._app: Optional["Application"] = None  # noqa: F821

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
        # get_cursor_position returns the last line so the Window auto-scrolls
        # to keep the newest content visible.
        output_window = Window(
            content=FormattedTextControl(
                lambda: ANSI(self._output_text) if self._output_text else "",
                get_cursor_position=lambda: Point(
                    x=0, y=self._output_text.count("\n")
                ),
            ),
            wrap_lines=True,
        )

        # Middle: status bar
        status_bar = Window(
            content=FormattedTextControl(
                lambda: ANSI(self.status_text) if self.status_text else "",
            ),
            height=Dimension.exact(1),
        )

        # Bottom: input area (no extra border — status bar above acts as separator)
        framed_input = HSplit([
            self.input_area,
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
        """Update the status bar text. Supports ANSI codes."""
        self.status_text = text
        if self._app and self._app.is_running:
            self._app.invalidate()
