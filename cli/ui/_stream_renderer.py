"""Stream renderer — converts agent stream events into rich formatted output."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from ._colors import _C
from ._render import _render_md
from ._spinner_widget import OutputSpinner
from ._status import format_status as _format_status_fn

if TYPE_CHECKING:
    from ._layout import ChatLayout


def _timestamp() -> str:
    """Return current time as grey HH:MM string."""
    return _C(datetime.now().strftime("%H:%M"), "grey")


_RESPONSE_COLORS = {
    "normal": "teal",
    "error": "red",
    "success": "green",
    "warning": "yellow",
}


class StreamRenderer:
    """Converts agent stream events into rich ANSI-formatted output text."""

    # Tool names → friendly labels
    _TOOL_LABELS = {
        "web_search": "Searching the web", "fetch_url": "Fetching URL",
        "run_command": "Running command", "run_python": "Running Python",
        "run_node": "Running Node.js", "read_file": "Reading file",
        "write_file": "Writing file", "list_dir": "Listing directory",
        "send_message": "Sending message", "telegram_send": "Sending Telegram",
        "discord_send": "Sending Discord",
        "memory_store": "Saving to memory", "memory_recall": "Recalling memory",
        "github_search_code": "Searching GitHub",
        "crypto_price": "Fetching crypto price", "stock_price": "Fetching stock",
        "get_time": "Checking time", "get_weather": "Checking weather",
    }

    # Args that are too bulky to show in preview
    _HIDDEN_ARGS = {"code", "script", "content", "text", "body"}

    # Persona → emoji mapping for coding mode
    _PERSONA_EMOJI = {
        "Team Lead": "🎯",
        "Backend": "🔧",
        "Frontend": "🎨",
        "Test Engineer": "🧪",
    }

    def __init__(
        self,
        layout: ChatLayout,
        model_name: str = "",
        token_limit: int = 32_000,
        session_start: float = 0.0,
    ) -> None:
        self.layout: ChatLayout = layout
        self._text_started: bool = False
        self._full_response: str = ""
        self._line_buf: str = ""
        self._model_name: str = model_name
        self._token_limit: int = token_limit
        self._session_start: float = session_start or time.time()
        self._total_tokens: int = 0
        # Coding mode persona state
        self._current_persona: Optional[str] = None
        # Coding mode status indicator
        self._coding_mode_active: bool = False
        # Background task count for status bar
        self._bg_task_count: int = 0
        # Current response box border color
        self._current_box_color: str = "teal"
        # Spinner widget for animated status in status bar
        self._spinner: OutputSpinner = OutputSpinner(layout)
        self._spinner._format_status = self._format_status

    def set_coding_mode(self, active: bool) -> None:
        """Toggle coding mode indicator in the status bar."""
        self._coding_mode_active = active

    def set_bg_task_count(self, count: int) -> None:
        """Update the background task count displayed in the status bar."""
        self._bg_task_count = count

    def _format_status(self, state_text: str) -> str:
        """Compose full status text with state indicator and persistent info."""
        return _format_status_fn(
            state_text=state_text,
            model_name=self._model_name,
            total_tokens=self._total_tokens,
            token_limit=self._token_limit,
            session_start=self._session_start,
            bg_task_count=self._bg_task_count,
            coding_mode=self._coding_mode_active,
        )

    def add_tokens(self, count: int) -> None:
        """Increment the total token counter."""
        self._total_tokens += count

    def handle_event(self, event: dict) -> None:
        """Process a single stream event and update output."""
        etype = event.get("type")

        if etype == "thinking":
            self._spinner.start("Thinking…")
            self.layout.set_status(self._format_status(
                _C("◐ Reasoning…", "cyan")
            ))

        elif etype == "tool_start":
            name = event["name"]
            args = event.get("args", {})
            visible_parts = []
            for k, v in list(args.items())[:4]:
                if k in self._HIDDEN_ARGS:
                    visible_parts.append(self._summarize_hidden_arg(k, str(v)))
                else:
                    visible_parts.append(f"{k}={repr(v)[:40]}")
            arg_str = ", ".join(visible_parts)
            label = self._TOOL_LABELS.get(name, f"Running {name}")
            self._spinner.stop()
            self._spinner.start(f"{label}…")
            self.layout.set_status(self._format_status(
                _C(f"⚙ {label}…", "cyan")
            ))
            # Store tool name for inline completion on tool_done
            self._pending_tool = name
            self._pending_tool_arg = arg_str[:50] if arg_str else ""

        elif etype == "tool_done":
            name = event["name"]
            elapsed = event.get("elapsed", 0)
            self._spinner.stop()
            # Single-line: ⚙ tool_name (args) → ✓ 0.05s
            line = _C(f"  ⚙ {name}", "cyan")
            if getattr(self, '_pending_tool_arg', ''):
                line += _C(f" ({self._pending_tool_arg})", "grey")
            line += _C(f" → ✓ {elapsed:.2f}s", "green")
            self.layout.append_output(line + "\n")
            self._pending_tool = None
            self._pending_tool_arg = ""
            self._spinner.start("Thinking…")
            self.layout.set_status(self._format_status(
                _C("◐ Reasoning…", "cyan")
            ))

        elif etype == "text":
            token = event.get("token", "")
            if not self._text_started:
                self._text_started = True
                self._spinner.stop()
                response_type = event.get("response_type", "normal")
                self._open_response_box("Koza", response_type)
            self._full_response += token
            self._total_tokens += max(1, len(token) // 4)

            # Update status with token count — but only every ~20 tokens
            # to avoid excessive set_status calls that trigger invalidation.
            if self._total_tokens % 20 < 2:
                self.layout.set_status(self._format_status(
                    _C(f"● Streaming… {self._total_tokens} tok", "green")
                ))

            # Buffer tokens and render complete lines with markdown
            self._line_buf += token
            while "\n" in self._line_buf:
                complete, self._line_buf = self._line_buf.split("\n", 1)
                rendered = _render_md(complete) if complete.strip() else ""
                self.layout.append_output(
                    rendered + "\n" + _C("  │ ", self._current_box_color)
                )

        elif etype == "interrupted":
            self._spinner.stop()
            self._flush_line_buf()
            if self._text_started:
                self._close_response_box("(interrupted)")
            else:
                self.layout.append_output(
                    _C("  (interrupted)", "grey") + "\n"
                )
            self._reset()

        elif etype == "tool_denied":
            name = event.get("name", "")
            self.layout.append_output(
                _C(f"  ✗  {name} denied", "red") + "\n"
            )

        # ── Coding mode events ────────────────────────────────────────────

        elif etype == "persona_token":
            persona = event.get("persona", "")
            token = event.get("token", "")
            # Open a new persona box if persona changed
            if persona != self._current_persona:
                self._close_persona_box()
                self._open_persona_box(persona)
            self._full_response += token
            self._total_tokens += max(1, len(token) // 4)
            if self._total_tokens % 20 < 2:
                self.layout.set_status(self._format_status(
                    _C(f"● Streaming… {self._total_tokens} tok", "green")
                ))
            # Buffer tokens and render complete lines with persona prefix
            self._line_buf += token
            while "\n" in self._line_buf:
                complete, self._line_buf = self._line_buf.split("\n", 1)
                rendered = _render_md(complete) if complete.strip() else ""
                self.layout.append_output(
                    rendered + "\n" + _C("  │ ", "magenta")
                )

        elif etype == "persona_tool":
            persona = event.get("persona", "")
            tool = event.get("tool", "")
            phase = event.get("phase", "")
            elapsed = event.get("elapsed", 0)
            # Ensure we're in the right persona box
            if persona != self._current_persona:
                self._close_persona_box()
                self._open_persona_box(persona)
            if phase == "start":
                # Don't print anything — wait for done to show single line
                self.layout.set_status(self._format_status(
                    _C(f"⚙ {tool}…", "cyan")
                ))
            elif phase == "done":
                # Single line: ⚙ tool → ✓ 0.05s
                self.layout.append_output(
                    _C(f"  ⚙ {tool}", "cyan")
                    + _C(f" → ✓ {elapsed:.2f}s", "green") + "\n"
                    + _C("  │ ", "magenta")
                )
                self.layout.set_status(self._format_status(
                    _C("◐ Reasoning…", "cyan")
                ))

        elif etype == "persona_thinking":
            persona = event.get("persona", "")
            if persona != self._current_persona:
                self._close_persona_box()
                self._open_persona_box(persona)
            self.layout.set_status(self._format_status(
                _C("◐ Reasoning…", "cyan")
            ))

        elif etype == "status":
            persona = event.get("persona", "")
            message = event.get("message", "")
            self.layout.append_output(
                _C(f"  ℹ [{persona}] ", "cyan") + message + "\n"
            )

        elif etype == "plan":
            plan = event.get("plan", {})
            self.layout.append_output(
                "\n" + _C("  ╭─ ", "yellow")
                + _C("📋 Plan ", "yellow", "bold")
                + _C("─" * 36, "yellow") + "\n"
            )
            tasks = plan.get("tasks", [])
            if tasks:
                for task in tasks:
                    if isinstance(task, dict):
                        desc = task.get("description", task.get("name", str(task)))
                    else:
                        desc = str(task)
                    self.layout.append_output(
                        _C("  │ ", "yellow") + _C("• ", "yellow") + desc + "\n"
                    )
            elif isinstance(plan, dict):
                # Fallback: show plan keys
                for key, val in plan.items():
                    self.layout.append_output(
                        _C("  │ ", "yellow") + _C(f"{key}: ", "white", "bold")
                        + str(val)[:80] + "\n"
                    )
            self.layout.append_output(
                _C("  ╰─", "yellow") + _C("─" * 42, "yellow") + "\n\n"
            )

        elif etype == "done":
            self._close_persona_box()
            summary = event.get("summary", "")
            if summary:
                self.layout.append_output(
                    "\n" + _C("  ✓ ", "green")
                    + _C(summary, "white") + "\n\n"
                )

        elif etype == "error_recorded":
            error = event.get("error", {})
            msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            self.layout.append_output(
                _C(f"  ✗ Error: {msg}", "red") + "\n"
            )

    def _flush_line_buf(self) -> None:
        """Flush any remaining partial line in the buffer."""
        if self._line_buf:
            rendered = _render_md(self._line_buf) if self._line_buf.strip() else self._line_buf
            self.layout.append_output(rendered)
            self._line_buf = ""

    # ── Response box helpers ──────────────────────────────────────────────────

    def _open_response_box(self, label: str, response_type: str = "normal") -> None:
        """Open a response box with border color based on response type."""
        color = _RESPONSE_COLORS.get(response_type, "teal")
        self._current_box_color = color
        self.layout.append_output(
            "\n"
            + _C("  ╭─ ", color)
            + _timestamp() + " "
            + _C(f"{label} ", color, "bold")
            + _C("─" * 40, color)
            + "\n"
            + _C("  │ ", color)
        )

    def _close_response_box(self, suffix: str = "") -> None:
        """Close the current response box using the stored box color."""
        color = self._current_box_color
        self.layout.append_output(
            "\n" + _C("  ╰─", color)
            + _C(f"  {suffix}", "grey") + "\n\n"
        )

    # ── Tool argument helpers ─────────────────────────────────────────────────

    def _summarize_hidden_arg(self, key: str, value: str) -> str:
        """Produce a one-line summary for a hidden argument."""
        lines = value.split("\n")
        first_line = lines[0]
        if len(lines) > 1:
            summary = first_line[:60]
            return f'{key}="{summary}…" ({len(lines)} lines)'
        if len(first_line) > 60:
            return f'{key}="{first_line[:60]}…"'
        return f'{key}="{first_line}"'

    # ── Persona box helpers ───────────────────────────────────────────────────

    def _open_persona_box(self, persona: str) -> None:
        """Open a new persona box with the appropriate emoji and label."""
        self._current_persona = persona
        emoji = self._PERSONA_EMOJI.get(persona, "👤")
        self.layout.append_output(
            "\n"
            + _C("  ╭─ ", "magenta")
            + _C(f"{emoji} {persona} ", "magenta", "bold")
            + _C("─" * max(0, 36 - len(persona)), "magenta")
            + "\n"
            + _C("  │ ", "magenta")
        )

    def _close_persona_box(self) -> None:
        """Close the currently open persona box, if any."""
        if self._current_persona is not None:
            self._flush_line_buf()
            self.layout.append_output(
                "\n" + _C("  ╰─", "magenta")
                + _C("─" * 42, "magenta") + "\n"
            )
            self._current_persona = None

    def render_user_message(self, message: str) -> None:
        """Render user message in the output pane with framed style."""
        ts = _timestamp()
        self.layout.append_output(
            "\n"
            + _C("  ┌─ ", "blue") + ts + " " + _C("You ", "blue", "bold")
            + _C("─" * 36, "blue") + "\n"
            + _C("  │ ", "blue") + _C(message, "white") + "\n"
            + _C("  └─", "blue") + _C("─" * 44, "blue") + "\n"
        )

    def finalize(self, elapsed: float) -> None:
        """Close the response box with timing info."""
        # Stop spinner to ensure it's cleaned up
        self._spinner.stop()
        # Close any open persona box first
        self._close_persona_box()
        if self._text_started:
            self._flush_line_buf()
            self._close_response_box(f"{elapsed:.1f}s")
        self.layout.set_status(self._format_status(
            _C("● Idle", "green")
        ))
        self._reset()

    def _reset(self) -> None:
        """Reset internal state for the next response cycle."""
        self._text_started = False
        self._full_response = ""
        self._line_buf = ""
        self._current_persona = None
        self._current_box_color = "teal"
