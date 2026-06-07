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
        "browser_task": "Using browser",
        "run_command": "Running command", "run_python": "Running Python",
        "run_node": "Running Node.js", "read_file": "Reading file",
        "write_file": "Writing file", "list_dir": "Listing directory",
        "send_message": "Sending message", "telegram_send": "Sending Telegram",
        "discord_send": "Sending Discord",
        "memory_store": "Saving to memory", "memory_recall": "Recalling memory",
        "github_search_code": "Searching GitHub",
        "crypto_price": "Fetching crypto price", "stock_price": "Fetching stock",
        "get_time": "Checking time", "get_weather": "Checking weather",
        # Additional tools
        "search_web": "Searching the web", "browse": "Browsing URL",
        "read_url": "Reading URL", "open_url": "Opening URL",
        "create_file": "Creating file", "delete_file": "Deleting file",
        "move_file": "Moving file", "copy_file": "Copying file",
        "append_file": "Appending to file", "patch_file": "Patching file",
        "search_files": "Searching files", "find_files": "Finding files",
        "run_bash": "Running bash", "execute": "Executing command",
        "run_script": "Running script", "run_code": "Running code",
        "kanban_add": "Adding task", "kanban_update": "Updating task",
        "kanban_list": "Listing tasks", "kanban_delete": "Deleting task",
        "cron_add": "Scheduling job", "cron_list": "Listing cron jobs",
        "save_session": "Saving session", "recall_sessions": "Searching sessions",
        "list_sessions": "Listing sessions",
        "credential_get": "Fetching credential", "credential_set": "Saving credential",
        "spawn_subagent": "Spawning sub-agent", "get_subagent_status": "Checking sub-agent",
        "translate": "Translating text", "summarize": "Summarizing",
        "diff": "Comparing files", "run_swarm": "Running parallel swarm",
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
        mode: str = "",
        provider_auth: str = "",
    ) -> None:
        self.layout: ChatLayout = layout
        self._text_started: bool = False
        self._full_response: str = ""
        self._line_buf: str = ""
        self._model_name: str = model_name
        self._token_limit: int = token_limit
        self._session_start: float = session_start or time.time()
        self._total_tokens: int = 0
        self._mode: str = mode
        self._provider_auth: str = provider_auth
        # Coding mode persona state
        self._current_persona: Optional[str] = None
        # Coding mode status indicator
        self._coding_mode_active: bool = False
        # Background task count for status bar
        self._bg_task_count: int = 0
        # Current response box border color
        self._current_box_color: str = "teal"
        # Compact tool box state. Tool output is intentionally separated from
        # response boxes so streaming text can resume cleanly after tool calls.
        self._tool_box_open: bool = False
        self._tool_box_color: str = "cyan"
        self._tool_box_started: float = 0.0
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
            mode=self._mode,
            provider_auth=self._provider_auth,
        )

    def add_tokens(self, count: int) -> None:
        """Increment the total token counter."""
        self._total_tokens += count

    def handle_event(self, event: dict) -> None:
        """Process a single stream event and update output."""
        etype = event.get("type")

        if etype == "thinking":
            self.layout.set_status(self._format_status(
                _C("◐ Reasoning…", "cyan")
            ))
            self._spinner.start("Thinking…")

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
            self.layout.set_status(self._format_status(
                _C(f"⚙ {label}…", "cyan")
            ))
            self._spinner.start(f"{label}…")
            self._close_response_if_open()
            self._close_persona_box()
            self._open_tool_box(name, label, arg_str)
            # Store tool name for completion on tool_done
            self._pending_tool = name
            self._pending_tool_arg = arg_str[:50] if arg_str else ""

        elif etype == "tool_done":
            name = event["name"]
            elapsed = event.get("elapsed", 0)
            self._spinner.stop()
            result_preview = self._summarize_tool_result(event.get("result"))
            if not self._tool_box_open:
                label = self._TOOL_LABELS.get(name, f"Running {name}")
                self._open_tool_box(name, label, getattr(self, "_pending_tool_arg", ""))
            self._append_tool_line(
                _C("✓ ", "green") + _C(name, "white")
                + _C(f" completed in {elapsed:.2f}s", "green")
            )
            if result_preview:
                self._append_tool_line(_C(result_preview, "grey"))
            self._close_tool_box(f"{elapsed:.2f}s")
            self._pending_tool = None
            self._pending_tool_arg = ""
            self._spinner.stop()
            self.layout.set_status(self._format_status(
                _C("◐ Reasoning…", "cyan")
            ))
            self._spinner.start("Thinking…")

        elif etype == "text":
            token = event.get("token", "")
            if self._tool_box_open:
                self._close_tool_box()
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
            self._close_tool_box("interrupted")
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
            self._spinner.stop()
            self._close_response_if_open()
            if not self._tool_box_open:
                self._open_tool_box(name or "tool", f"Permission: {name or 'tool'}", "")
            self._append_tool_line(_C(f"✗ {name} denied", "red"))
            self._close_tool_box("denied")

        elif etype == "error":
            message = event.get("message", "Unknown error")
            self._spinner.stop()
            self._close_tool_box("error")
            self._flush_line_buf()
            if self._text_started:
                # Error inside an open response box — show error and close
                self.layout.append_output(
                    "\n" + _C("  │ ", self._current_box_color)
                    + _C(f"Error: {message}", "red") + "\n"
                )
                self._close_response_box("error")
            else:
                # Error before any text — open a minimal error box
                self.layout.append_output(
                    "\n" + _C("  ╭─ ", "red")
                    + _C("Error ", "red", "bold")
                    + _C("─" * 40, "red") + "\n"
                    + _C("  │ ", "red")
                    + _C(message, "red") + "\n"
                    + _C("  ╰─", "red")
                    + _C("─" * 42, "red") + "\n\n"
                )
            self._reset()

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

    def _close_response_if_open(self, suffix: str = "") -> None:
        """Close an open response box before rendering another block."""
        if self._text_started:
            self._flush_line_buf()
            self._close_response_box(suffix)
            self._text_started = False
            self._current_box_color = "teal"

    def _open_response_box(self, label: str, response_type: str = "normal") -> None:
        """Open a response box with border color based on response type."""
        import shutil as _shutil
        color = _RESPONSE_COLORS.get(response_type, "teal")
        self._current_box_color = color
        tw = max(36, _shutil.get_terminal_size((80, 24)).columns - 12)
        emoji = "🦎" if label == "Koza" else "🤖"
        self.layout.append_output(
            "\n"
            + _C("  ╭─ ", color)
            + _timestamp() + " "
            + _C(f"{emoji} {label} ", color, "bold")
            + _C("─" * tw, color)
            + "\n"
            + _C("  │ ", color)
        )

    def _close_response_box(self, suffix: str = "") -> None:
        """Close the current response box using the stored box color."""
        color = self._current_box_color
        suffix_text = _C(f"  {suffix}", "grey") if suffix else ""
        self.layout.append_output(
            "\n" + _C("  ╰─", color)
            + suffix_text + "\n\n"
        )

    # ── Tool box helpers ──────────────────────────────────────────────────────

    def _open_tool_box(self, name: str, label: str, arg_str: str = "") -> None:
        """Open a compact box for one tool call."""
        import shutil as _shutil
        if self._tool_box_open:
            self._close_tool_box()
        self._tool_box_open = True
        self._tool_box_started = time.time()
        # Use different emoji based on tool type
        emoji = "🔧"
        if "search" in name or "fetch" in name or "browser" in name:
            emoji = "🌐"
        elif "file" in name or "write" in name or "read" in name:
            emoji = "📁"
        elif "command" in name or "run" in name or "python" in name:
            emoji = "⚡"
        elif "memory" in name or "recall" in name or "session" in name:
            emoji = "🧠"
        elif "send" in name or "message" in name or "telegram" in name:
            emoji = "📨"
        elif "skill" in name or "plugin" in name:
            emoji = "🧩"
        elif "swarm" in name:
            emoji = "🐝"
        self.layout.append_output(
            "\n"
            + _C("  ╭─ ", self._tool_box_color)
            + _timestamp() + " "
            + _C(f"{emoji} {label}", self._tool_box_color, "bold")
            + "\n"
        )
        if arg_str:
            self._append_tool_line(_C(arg_str[:140], "grey"))

    def _append_tool_line(self, text: str) -> None:
        """Append one line inside the current tool box."""
        self.layout.append_output(_C("  │ ", self._tool_box_color) + text + "\n")

    def _close_tool_box(self, suffix: str = "") -> None:
        """Close the current tool box, if one is open."""
        if not self._tool_box_open:
            return
        if not suffix and self._tool_box_started:
            suffix = f"{time.time() - self._tool_box_started:.2f}s"
        suffix_text = _C(f"  {suffix}", "grey") if suffix else ""
        self.layout.append_output(
            _C("  ╰─", self._tool_box_color)
            + suffix_text + "\n\n"
        )
        self._tool_box_open = False
        self._tool_box_started = 0.0

    def _summarize_tool_result(self, result: object) -> str:
        """Return a short, non-secret-ish preview for a tool result."""
        if result is None:
            return ""
        text = str(result).strip().replace("\r", "")
        if not text:
            return ""
        first = next((line.strip() for line in text.split("\n") if line.strip()), "")
        if not first:
            return ""
        lowered = first.lower()
        if any(word in lowered for word in ("token", "secret", "password", "api_key", "apikey")):
            return "result hidden"
        return first[:140] + ("..." if len(first) > 140 else "")

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
            + _C("  ┌─ ", "blue", "bold") + ts + " "
            + _C("👤 You ", "blue", "bold")
            + _C("─" * max(10, 34 - min(len(message), 30)), "blue")
            + "\n"
            + _C("  │ ", "blue") + _C(message, "white") + "\n"
            + _C("  └─", "blue")
            + _C("─" * 44, "blue") + "\n"
        )

    def finalize(self, elapsed: float) -> None:
        """Close the response box with timing info."""
        # Stop spinner to ensure it's cleaned up
        self._spinner.stop()
        self._close_tool_box()
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
        self._tool_box_open = False
        self._tool_box_started = 0.0
