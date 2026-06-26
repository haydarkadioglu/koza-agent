"""
Inline keyboard builder and pending confirmation tracker for the Telegram bot.

Provides InlineKeyboardManager which builds inline keyboards for tool
confirmations and background task control, and tracks pending confirmations
until they are resolved or timed out.
"""
import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


@dataclass
class PendingConfirmation:
    """Tracks a tool confirmation awaiting user response."""

    confirmation_id: str
    tool_name: str
    tool_args: dict
    future: asyncio.Future
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)


class InlineKeyboardManager:
    """Builds inline keyboards and tracks pending confirmations."""

    def __init__(self):
        self._pending: Dict[str, PendingConfirmation] = {}
        self._lock = threading.Lock()

    def build_tool_confirmation_kb(
        self, tool_name: str, tool_args: dict, loop: asyncio.AbstractEventLoop
    ) -> tuple[str, str, InlineKeyboardMarkup, asyncio.Future]:
        """
        Build a tool confirmation message with approve/reject buttons.

        Returns (confirmation_id, text, keyboard_markup, future).
        The future resolves to True (approve) or False (reject/timeout).
        """
        conf_id = uuid.uuid4().hex[:8]
        future = loop.create_future()

        import html
        # Format message text
        args_summary = ", ".join(
            f"{html.escape(k)}={html.escape(str(v)[:50])}" for k, v in tool_args.items()
        )
        text = f"🔧 <b>Tool:</b> <code>{html.escape(tool_name)}</code>\n📋 <b>Args:</b> <code>{args_summary}</code>\n\nApprove execution?"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Approve", callback_data=f"tool:{conf_id}:approve"
                ),
                InlineKeyboardButton(
                    "❌ Reject", callback_data=f"tool:{conf_id}:reject"
                ),
            ]
        ])

        pending = PendingConfirmation(
            confirmation_id=conf_id,
            tool_name=tool_name,
            tool_args=tool_args,
            future=future,
        )
        with self._lock:
            self._pending[conf_id] = pending

        return conf_id, text, keyboard, future

    def build_task_control_kb(self, task_id: str) -> InlineKeyboardMarkup:
        """Build status/cancel buttons for a background task."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📊 Status", callback_data=f"task:{task_id}:status"
                ),
                InlineKeyboardButton(
                    "🛑 Cancel", callback_data=f"task:{task_id}:cancel"
                ),
            ]
        ])

    def resolve_confirmation(
        self, conf_id: str, approved: bool
    ) -> Optional[PendingConfirmation]:
        """Resolve a pending confirmation. Returns the PendingConfirmation or None."""
        with self._lock:
            pending = self._pending.pop(conf_id, None)
        if pending and not pending.future.done():
            pending.future.get_loop().call_soon_threadsafe(
                pending.future.set_result, approved
            )
        return pending

    def timeout_confirmation(self, conf_id: str) -> Optional[PendingConfirmation]:
        """Timeout a pending confirmation (resolves as rejected)."""
        return self.resolve_confirmation(conf_id, False)
