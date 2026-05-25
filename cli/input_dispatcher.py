"""Input dispatcher — routes user input, handles interrupt-if-busy logic."""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .ui._layout import ChatLayout
    from .ui._stream_renderer import StreamRenderer
    from skills.agents.coding_mode import CodingSession


class InputDispatcher:
    """Routes user input: interrupts agent if busy, submits otherwise."""

    def __init__(self, agent, layout: ChatLayout, renderer: StreamRenderer, coding_enabled: bool = False) -> None:
        self.agent = agent
        self.layout: ChatLayout = layout
        self.renderer: StreamRenderer = renderer
        self._coding_enabled = coding_enabled
        self._processing: threading.Event = threading.Event()
        self._proc_thread: Optional[threading.Thread] = None
        self._coding_mode: bool = False
        self._coding_session: Optional[CodingSession] = None

    # ── Coding mode management ────────────────────────────────────────────────

    def enable_coding_mode(self) -> None:
        """Activate coding mode — subsequent messages use CodingSession."""
        if not self._coding_enabled:
            return  # silently ignore when feature gate is off
        from skills.agents.coding_mode import CodingSession
        cfg = self.agent.cfg if hasattr(self.agent, 'cfg') else {}
        db_path = self.agent.db_path if hasattr(self.agent, 'db_path') else ""
        self._coding_session = CodingSession(cfg, db_path)
        self._coding_mode = True
        self.renderer.set_coding_mode(True)

    def disable_coding_mode(self) -> None:
        """Deactivate coding mode — return to normal agent chat."""
        self._coding_mode = False
        self._coding_session = None
        self.renderer.set_coding_mode(False)

    def _start_background_task(self, user_input: str) -> None:
        """Delegate a task to run in background and notify on completion."""
        from .ui._colors import _C
        from skills.agents import spawn_subagent

        def _run_and_notify():
            try:
                result = spawn_subagent(user_input, wait=True)
                self.layout.append_output(
                    _C(f"\n  ✓  Background task completed:\n", "green")
                )
                # Show result summary (truncated)
                summary = result[:500] if result else "(no output)"
                self.layout.append_output(f"  {summary}\n\n")
            except Exception as exc:
                self.layout.append_output(
                    _C(f"\n  ✗  Background task failed: {exc}\n\n", "red")
                )

        t = threading.Thread(target=_run_and_notify, daemon=True)
        t.start()

    def submit(self, user_input: str) -> None:
        """Handle user submission — interrupt if busy, then process."""
        if not user_input:
            # Empty Enter: interrupt if busy, otherwise no-op
            if self._processing.is_set():
                if self._coding_mode and self._coding_session:
                    self._coding_session.interrupt()
                else:
                    self.agent.interrupt()
                # Immediate UX feedback — don't wait for agent to actually stop
                self._show_interrupting_status()
                # Start force-kill watchdog: if interrupt doesn't complete
                # within 5s, force-clear all state to prevent permanent hang.
                threading.Thread(
                    target=self._force_kill_watchdog,
                    daemon=True,
                ).start()
            return

        if self._processing.is_set():
            # Interrupt current operation
            if self._coding_mode and self._coding_session:
                self._coding_session.interrupt()
            else:
                self.agent.interrupt()
            # Immediate UX feedback — don't wait for agent to actually stop
            self._show_interrupting_status()
            if self._proc_thread and self._proc_thread.is_alive():
                self._proc_thread.join(timeout=5.0)
                if self._proc_thread.is_alive():
                    # Zombie thread — force-clear state to prevent permanent hang
                    logger.warning(
                        "Agent thread still alive after 5s timeout — "
                        "force-clearing processing state (zombie thread)"
                    )
                    self._processing.clear()
                    self.agent._busy = False

        # LLM-driven coding mode detection (replaces keyword matching)
        if not self._coding_mode and self._coding_enabled:
            try:
                decision = self.agent._router.classify(user_input)
                if decision.activate_coding_mode:
                    from .ui._colors import _C
                    self.enable_coding_mode()
                    self.layout.append_output(_C("  ℹ  Auto-activating coding mode…\n", "cyan"))
            except Exception:
                pass  # On router failure, skip auto-activation

        # Start new processing — wait for stream_lock to ensure previous
        # stream_chat has fully released before starting a new thread.
        if hasattr(self.agent, '_stream_lock'):
            acquired = self.agent._stream_lock.acquire(timeout=5.0)
            if acquired:
                self.agent._stream_lock.release()

        self._proc_thread = threading.Thread(
            target=self._run_agent,
            args=(user_input,),
            daemon=True,
        )
        self._proc_thread.start()

    def is_busy(self) -> bool:
        """Check if agent is currently processing."""
        return self._processing.is_set()

    def _show_interrupting_status(self) -> None:
        """Immediately update status bar to show interrupt was received."""
        from .ui._colors import _C

        self.layout.set_status(self.renderer._format_status(
            _C("⏸ Interrupting…", "yellow")
        ))
        self.renderer._spinner.stop()
        self.renderer._spinner.start("Interrupting…")

    def _force_kill_watchdog(self) -> None:
        """Wait up to 5s for interrupt to complete; force-clear state if it doesn't."""
        from .ui._colors import _C

        # Wait for processing to finish (interrupt should clear it)
        deadline = time.time() + 5.0
        while self._processing.is_set() and time.time() < deadline:
            time.sleep(0.1)

        if self._processing.is_set():
            # Interrupt didn't complete within 5s — force-clear all state
            logger.warning(
                "Interrupt did not complete within 5s — force-clearing all state"
            )
            self._processing.clear()
            self.agent._busy = False
            self.agent._cancel.clear()
            self.layout.set_prompt_indicator(busy=False)
            self.renderer._spinner.stop()
            self.layout.append_output(
                _C("\n  ⚠ Force stopped — interrupt timed out after 5s\n", "yellow")
            )

    def _run_agent(self, user_input: str) -> None:
        """Background thread: stream agent response to output pane."""
        from .ui._colors import _C

        self._processing.set()
        self.layout.set_prompt_indicator(busy=True)

        # Immediate feedback: show "waiting" status + start spinner
        self.layout.set_status(self.renderer._format_status(
            _C("◌ Waiting for response…", "cyan")
        ))
        self.renderer._spinner.start("Waiting for response…")

        t_start = time.time()
        first_event = True

        try:
            if self._coding_mode and self._coding_session:
                # Use CodingSession for coding mode
                session_done = False
                for event in self._coding_session.run(user_input):
                    if not isinstance(event, dict):
                        continue
                    if first_event:
                        first_event = False
                    self.renderer.handle_event(event)
                    if event.get("type") == "done":
                        session_done = True
                        break
                    if event.get("type") == "interrupted":
                        break
                # Auto-exit coding mode when session completes normally
                if session_done:
                    self.disable_coding_mode()
                    self.layout.append_output(
                        _C("  ℹ  Coding mode completed. Returning to normal chat.\n", "grey")
                    )
            else:
                # Normal agent chat
                for event in self.agent.stream_chat(user_input):
                    if not isinstance(event, dict):
                        continue
                    if first_event:
                        first_event = False
                    self.renderer.handle_event(event)
                    if event.get("type") == "interrupted":
                        break
        except Exception as exc:
            self.layout.append_output(
                _C(f"\n  ✗ Error: {exc}\n", "red")
            )
        finally:
            elapsed = time.time() - t_start
            self.renderer.finalize(elapsed)
            self._processing.clear()
            self.layout.set_prompt_indicator(busy=False)
