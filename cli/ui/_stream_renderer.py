"""Stream renderer — converts agent stream events into rich formatted output."""
from __future__ import annotations

import time
from typing import Optional, TYPE_CHECKING

from ._colors import _C
from ._render import _render_md
from ._spinner_widget import OutputSpinner

if TYPE_CHECKING:
    from ._layout import ChatLayout


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
        # Spinner widget for animated status in status bar
        self._spinner: OutputSpinner = OutputSpinner(layout)
        self._spinner._format_status = self._format_status

    def set_coding_mode(self, active: bool) -> None:
        """Toggle coding mode indicator in the status bar."""
        self._coding_mode_active = active

    def _format_status(self, state_text: str) -> str:
        """Compose full status text with state indicator and persistent info."""
        elapsed = int(time.time() - self._session_start)
        h, m = divmod(elapsed // 60, 60)
        s_time = f"{h}h {m:02d}m" if h else f"{m}m"
        if self._total_tokens >= 1000:
            tok_str = f"{self._total_tokens // 1000}K/{self._token_limit // 1000}K"
        else:
            tok_str = f"{self._total_tokens}/{self._token_limit // 1000}K"
        base = f"{state_text}  │  {self._model_name}  │  {tok_str}  │  {s_time}"
        if self._coding_mode_active:
            return f"🎯 Coding Mode  │  {base}"
        return base

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
            visible = {k: v for k, v in args.items() if k not in self._HIDDEN_ARGS}
            arg_str = ", ".join(
                f"{k}={repr(v)[:40]}" for k, v in list(visible.items())[:2]
            )
            label = self._TOOL_LABELS.get(name, f"Running {name}")
            self._spinner.stop()
            self._spinner.start(f"{label}…")
            self.layout.set_status(self._format_status(
                _C(f"⚙ {label}…", "cyan")
            ))
            line = _C(f"  ⚙  {name}", "cyan")
            if arg_str:
                line += _C(f"  ({arg_str[:60]})", "grey")
            self.layout.append_output(line + "\n")

        elif etype == "tool_done":
            name = event["name"]
            elapsed = event.get("elapsed", 0)
            result = str(event.get("result", ""))
            lines = [l for l in result.splitlines() if l.strip()]
            summary = (
                (lines[0][:80] + ("…" if len(lines[0]) > 80 else ""))
                if lines else "(no output)"
            )
            extra = _C(f"  +{len(lines)-1} lines", "grey") if len(lines) > 1 else ""
            self._spinner.stop()
            self.layout.append_output(
                _C(f"  ✓  {name}", "green")
                + _C(f"  {elapsed:.2f}s", "grey")
                + _C(f"  → {summary}", "white")
                + extra + "\n"
            )
            self._spinner.start("Thinking…")
            self.layout.set_status(self._format_status(
                _C("◐ Reasoning…", "cyan")
            ))

        elif etype == "text":
            token = event.get("token", "")
            if not self._text_started:
                self._text_started = True
                self._spinner.stop()
                self.layout.append_output(
                    "\n"
                    + _C("  ╭─ ", "teal")
                    + _C("Koza ", "teal", "bold")
                    + _C("─" * 40, "teal")
                    + "\n"
                    + _C("  │ ", "teal")
                )
            self._full_response += token
            self._total_tokens += max(1, len(token) // 4)

            # Update status with token count while streaming
            self.layout.set_status(self._format_status(
                _C(f"● Streaming… {self._total_tokens} tok", "green")
            ))

            # Buffer tokens and render complete lines with markdown
            self._line_buf += token
            while "\n" in self._line_buf:
                complete, self._line_buf = self._line_buf.split("\n", 1)
                rendered = _render_md(complete) if complete.strip() else ""
                self.layout.append_output(
                    rendered + "\n" + _C("  │ ", "teal")
                )

        elif etype == "interrupted":
            self._spinner.stop()
            self._flush_line_buf()
            if self._text_started:
                self.layout.append_output(
                    "\n" + _C("  ╰─", "teal")
                    + _C("  (interrupted)", "grey") + "\n"
                )
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
                self.layout.append_output(
                    _C(f"  ⚙ {tool}", "cyan") + "\n"
                    + _C("  │ ", "magenta")
                )
                self.layout.set_status(self._format_status(
                    _C(f"⚙ {tool}…", "cyan")
                ))
            elif phase == "done":
                self.layout.append_output(
                    _C(f"  ✓ {tool}", "green")
                    + _C(f"  {elapsed:.2f}s", "grey") + "\n"
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
        self.layout.append_output(
            "\n"
            + _C("  ┌─ ", "cyan") + _C("You ", "cyan", "bold") + _C("─" * 40, "cyan") + "\n"
            + _C("  │ ", "cyan") + message + "\n"
            + _C("  └─", "cyan") + _C("─" * 44, "cyan") + "\n"
        )

    def finalize(self, elapsed: float) -> None:
        """Close the response box with timing info."""
        # Stop spinner to ensure it's cleaned up
        self._spinner.stop()
        # Close any open persona box first
        self._close_persona_box()
        if self._text_started:
            self._flush_line_buf()
            self.layout.append_output(
                "\n" + _C("  ╰─", "teal")
                + _C(f"  {elapsed:.1f}s", "grey") + "\n\n"
            )
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
