"""
Telegram surface for the ``ask_user`` tool.

Bounded v1 behaviour:
- One message per ``ask_user`` call.
- Only the FIRST question is offered as inline buttons, and only when it is a
  single-select question with choices. Remaining questions are listed as
  ``❓ <text>`` lines in the same message and come back ``unanswered``.
- When the first question is open-ended or multi-select, no buttons are shown;
  the message invites a normal reply and the tool result is ``undelivered`` with a
  notice, so the model proceeds on its own judgment.

The handler runs on a gateway worker thread: it schedules the send on the bot loop
with ``asyncio.run_coroutine_threadsafe``, waits a bounded time for the send, and
returns. The answer arrives later through ``resolve_from_callback`` (button press).
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.clarify import GATEWAY, ClarifyReply, ClarifyRequest

logger = logging.getLogger(__name__)

_SEND_TIMEOUT = 10          # seconds to wait for Telegram to accept the message
_EXPIRY_SLACK = 1.0         # edit the message shortly after the gateway gives up
_MAX_TEXT = 3800            # stay under Telegram's 4096-char message limit
_MAX_BUTTON_LABEL = 60
_MAX_BUTTONS = 100          # Telegram per-message inline button limit
_EXPIRED_TEXT = "⏰ This question expired."


@dataclass
class _PendingAsk:
    chat_id: int
    question: dict
    other_count: int
    bot: object
    loop: asyncio.AbstractEventLoop
    message_id: int | None = None
    extra: dict = field(default_factory=dict)


_lock = threading.Lock()
_pending: dict[str, _PendingAsk] = {}


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _render_text(request: ClarifyRequest, with_buttons: bool) -> str:
    lines = [f"❓ {q['question']}" for q in request.questions]
    if not with_buttons:
        lines.append("")
        lines.append("Reply in a normal message if you want to answer; "
                     "Koza continues with its best judgment meanwhile.")
    elif len(request.questions) > 1:
        lines.append("")
        lines.append("Only the first question can be answered with the buttons below.")
    return _truncate("\n".join(lines), _MAX_TEXT)


def _build_keyboard(request_id: str, entry: dict) -> InlineKeyboardMarkup:
    qid = entry["qid"]
    choice_row = [
        InlineKeyboardButton(_truncate(label, _MAX_BUTTON_LABEL),
                             callback_data=f"clarify:{request_id}:{qid}:{index}")
        for index, label in enumerate(entry["choices"])
    ]
    rows = [choice_row]
    if len(choice_row) + 1 <= _MAX_BUTTONS:
        rows.append([InlineKeyboardButton("Skip", callback_data=f"clarify:{request_id}:{qid}:skip")])
    return InlineKeyboardMarkup(rows)


async def _expire_later(request_id: str, delay: float) -> None:
    await asyncio.sleep(delay)
    with _lock:
        pending = _pending.pop(request_id, None)
    if pending is None or pending.message_id is None:
        return
    try:
        await pending.bot.edit_message_text(
            chat_id=pending.chat_id, message_id=pending.message_id, text=_EXPIRED_TEXT,
        )
    except Exception:
        logger.debug("clarify expiry edit failed", exc_info=True)


def make_clarify_handler(chat_id: int, bot, loop, kb_manager=None):
    """Build a gateway handler that asks questions in ``chat_id`` via inline buttons."""

    def handler(request: ClarifyRequest) -> ClarifyReply | None:
        try:
            first = request.questions[0]
            with_buttons = bool(first.get("choices")) and not first.get("multi_select")
            text = _render_text(request, with_buttons)
            markup = _build_keyboard(request.request_id, first) if with_buttons else None

            if with_buttons:
                # Register before sending so an instant tap cannot race the bookkeeping.
                with _lock:
                    _pending[request.request_id] = _PendingAsk(
                        chat_id=chat_id, question=first,
                        other_count=len(request.questions) - 1, bot=bot, loop=loop,
                    )

            send = asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id=chat_id, text=text, reply_markup=markup), loop,
            )
            try:
                sent = send.result(timeout=_SEND_TIMEOUT)
            except Exception:
                with _lock:
                    _pending.pop(request.request_id, None)
                logger.debug("clarify send failed", exc_info=True)
                return ClarifyReply.undelivered("The question could not be sent to Telegram; "
                                                "decide with your best judgment.")

            if not with_buttons:
                return ClarifyReply.undelivered(
                    "Telegram can only collect single-choice answers with buttons; the question was "
                    "posted but cannot be answered inline. Decide with your best judgment and state "
                    "your assumption."
                )

            with _lock:
                pending = _pending.get(request.request_id)
                if pending is not None:
                    pending.message_id = getattr(sent, "message_id", None)
            asyncio.run_coroutine_threadsafe(
                _expire_later(request.request_id, request.timeout_seconds + _EXPIRY_SLACK), loop,
            )
            return None
        except Exception:
            with _lock:
                _pending.pop(request.request_id, None)
            logger.debug("clarify handler failed", exc_info=True)
            return ClarifyReply.undelivered("The question could not be sent to Telegram; "
                                            "decide with your best judgment.")

    return handler


def resolve_from_callback(request_id: str, qid: str, choice: str) -> str | None:
    """Resolve a button press. Returns the confirmation text to show, or None when expired."""
    with _lock:
        pending = _pending.get(request_id)
        if pending is None or pending.question.get("qid") != qid:
            return None
        _pending.pop(request_id, None)

    entry = pending.question
    offered = entry.get("choices_offered") or []
    if choice == "skip":
        answer, shown = "", "Skipped"
    else:
        try:
            index = int(choice)
        except (TypeError, ValueError):
            return None
        if not 0 <= index < len(offered):
            return None
        answer, shown = offered[index], offered[index]

    reply = ClarifyReply.submitted({qid: answer})
    if pending.other_count:
        reply.notice = "Telegram offered only the first question as buttons; the others were not answered."
    if not GATEWAY.resolve(request_id, reply):
        return None
    return _truncate(f"❓ {entry['question']}\n✅ {shown}", _MAX_TEXT)


def _reset_for_tests() -> None:
    with _lock:
        _pending.clear()
