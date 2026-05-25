"""
Telegram bot thread for Koza daemon.

Each Telegram chat_id gets its own Agent instance (isolated session).
Messages stream back to the user in real time (chunked text edits).
"""
import asyncio
import logging
import re
import threading
from typing import Dict, Callable

from skills.agents.background import BackgroundTaskManager, _background_tasks

logger = logging.getLogger(__name__)

# ── Module-level config reference (set by start_bot_thread) ──────────────────
_bot_cfg: dict | None = None


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting from text for clean Telegram display."""
    # Remove headers (## Title → Title)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold (**text** or __text__ → text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Remove italic (*text* or _text_ → text) — careful not to hit underscores in code
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"\1", text)
    # Remove inline code (`text` → text)
    text = re.sub(r"`([^`]+?)`", r"\1", text)
    # Remove code block fences (```lang ... ``` → just the code)
    text = re.sub(r"```\w*\n?", "", text)
    # Remove horizontal rules (--- or ***)
    text = re.sub(r"^[-*]{3,}\s*$", "", text, flags=re.MULTILINE)
    # Remove bullet markers (- item → item, * item → item)
    text = re.sub(r"^[\-\*]\s+", "• ", text, flags=re.MULTILINE)
    return text.strip()


# ── LLM-driven routing (replaces keyword-based detection) ────────────────────
# The router is accessed via the agent instance: agent._router.classify(text)
# No more keyword lists here — the LLM decides what's a coding task.


def _register_completion_watcher(task_id: str, chat_id: int, bot, loop=None) -> None:
    """Poll task status and send notification on completion."""

    def _watcher():
        import time
        _loop = loop or asyncio.new_event_loop()
        while True:
            time.sleep(5)
            status = BackgroundTaskManager.get_status(task_id)
            if not status:
                break
            if status["status"] == "done":
                summary = BackgroundTaskManager.get_summary(task_id)
                msg_text = f"✅ Task {task_id} done:\n{summary}"
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(chat_id=chat_id, text=msg_text),
                    _loop,
                )
                break
            elif status["status"] == "error":
                task = _background_tasks.get(task_id)
                err = task.error_message if task else "Unknown error"
                msg_text = f"❌ Task {task_id} failed:\n{err}"
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(chat_id=chat_id, text=msg_text),
                    _loop,
                )
                break
            elif status["status"] == "cancelled":
                break

    threading.Thread(target=_watcher, daemon=True, name=f"tg-watcher-{task_id}").start()


# chat_id → Agent instance
_agents: Dict[int, object] = {}
_agents_lock = threading.Lock()


# Tools that require explicit user approval via inline buttons.
# Everything else is auto-approved to avoid spamming the chat.
_TOOLS_REQUIRING_APPROVAL = {
    "delete_file", "delete_directory",
    "send_email", "git_push", "deploy", "install_package",
}


def _make_permission_callback(chat_id: int, bot, loop, kb_manager):
    """Create a permission callback that uses inline buttons for tool confirmation.

    Only tools in _TOOLS_REQUIRING_APPROVAL prompt the user. All other tools
    are auto-approved to keep the chat clean.
    """

    def permission_callback(tool_name: str, tool_args: dict) -> bool:
        """Block until user approves/rejects via inline button (or timeout)."""
        # Auto-approve safe tools — no inline button needed
        if tool_name not in _TOOLS_REQUIRING_APPROVAL:
            return True

        conf_id, text, keyboard, future = kb_manager.build_tool_confirmation_kb(
            tool_name, tool_args, loop
        )

        # Send confirmation message from the agent's worker thread
        send_coro = bot.send_message(
            chat_id=chat_id, text=text, reply_markup=keyboard,
            parse_mode="Markdown"
        )
        msg_future = asyncio.run_coroutine_threadsafe(send_coro, loop)
        try:
            sent_msg = msg_future.result(timeout=10)
        except Exception:
            # If we can't send the message, default to reject
            return False

        # Store message_id for later editing
        with kb_manager._lock:
            if conf_id in kb_manager._pending:
                kb_manager._pending[conf_id].message_id = sent_msg.message_id
                kb_manager._pending[conf_id].chat_id = chat_id

        # Schedule 5-minute async timeout that resolves as rejected
        async def _timeout():
            await asyncio.sleep(300)  # 5 minutes
            kb_manager.timeout_confirmation(conf_id)

        asyncio.run_coroutine_threadsafe(_timeout(), loop)

        # Wait for resolution (blocks the agent thread)
        try:
            result = future.result(timeout=310)  # slightly longer than async timeout
        except Exception:
            result = False

        return result

    return permission_callback


def _get_or_create_agent(chat_id: int, agent_factory: Callable, permission_cb=None):
    with _agents_lock:
        if chat_id not in _agents:
            agent = agent_factory(channel="telegram")
            agent.permission_callback = permission_cb
            _agents[chat_id] = agent
        return _agents[chat_id]


async def _process_message(update, context, agent_factory: Callable,
                           kb_manager=None, bot_loop=None):
    """Process one Telegram message: stream agent response back in real time."""
    import time as _time
    import queue as _queue
    from telegram.constants import ParseMode, ChatAction
    from telegram.error import BadRequest as _BadRequest

    msg = update.message or update.edited_message
    if not msg:
        return

    chat_id = msg.chat_id
    user_text = msg.text or msg.caption or ""
    image_path = None

    # Photo support
    if msg.photo:
        photo = msg.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.close()
        await file.download_to_drive(tmp.name)
        image_path = tmp.name
        if not user_text:
            user_text = "Analyze this photo."

    if not user_text:
        return

    # ── Background delegation disabled ────────────────────────────────────────
    # Koza handles all requests directly. User can explicitly use spawn_subagent
    # tool if they want background delegation.
    # Get or create agent first
    permission_cb = None
    if kb_manager and bot_loop:
        permission_cb = _make_permission_callback(
            chat_id, context.bot, bot_loop, kb_manager
        )
    agent = _get_or_create_agent(chat_id, agent_factory, permission_cb=permission_cb)

    if agent._busy:
        agent.interrupt()
        # Wait for the previous stream to finish (max 5s)
        for _ in range(50):
            if not agent._busy:
                break
            await asyncio.sleep(0.1)
        await context.bot.send_message(chat_id=chat_id, text="⏸ Previous task interrupted.")

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    if image_path:
        user_text = f"[Photo: {image_path}]\n{user_text}"

    ev_queue: _queue.Queue = _queue.Queue()
    _DONE = object()

    def _stream_worker():
        try:
            for event in agent.stream_chat(user_text):
                ev_queue.put(event)
        except Exception as e:
            ev_queue.put({"type": "error", "message": str(e)})
        finally:
            ev_queue.put(_DONE)

    threading.Thread(target=_stream_worker, daemon=True).start()

    # ── Single-message streaming with throttled edits ────────────────────────
    # Strategy: maintain ONE message. Accumulate text + status lines.
    # Edit at most once per 1.5s to stay within Telegram rate limits (~20 edits/min).
    # Only create a new message when current exceeds 4000 chars.

    text_buf  = ""          # accumulated response text
    status    = ""          # ephemeral status line (tool activity)
    sent_msg  = None        # current Telegram message object
    last_edit = 0.0         # timestamp of last edit

    async def _flush(force: bool = False):
        nonlocal sent_msg, last_edit, status
        now = _time.time()
        if not force and (now - last_edit) < 1.5:
            return
        display = text_buf + (f"\n\n{status}" if status else "")
        display = _strip_markdown(display)
        if not display.strip():
            return
        # Overflow: start new message
        if len(display) > 4000:
            overflow = display[4000:]
            display  = display[:4000]
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_msg.message_id,
                    text=display,
                )
            except Exception:
                pass
            sent_msg = await context.bot.send_message(
                chat_id=chat_id, text=overflow[:4000],
            )
            last_edit = now
            return
        if sent_msg is None:
            sent_msg = await context.bot.send_message(chat_id=chat_id, text=display)
        else:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_msg.message_id,
                    text=display,
                )
            except _BadRequest:
                pass   # "message not modified" — ignore
            except Exception:
                sent_msg = await context.bot.send_message(chat_id=chat_id, text=display)
        last_edit = now

    while True:
        try:
            event = ev_queue.get_nowait()
        except _queue.Empty:
            await _flush()
            await asyncio.sleep(0.05)
            continue

        if event is _DONE:
            break

        if not isinstance(event, dict):
            continue

        etype = event.get("type")

        if etype == "text":
            text_buf += event.get("token", "")
            await _flush()

        elif etype == "tool_start":
            status = f"⚙️ `{event.get('name', '')}` running…"
            await _flush(force=True)

        elif etype == "tool_done":
            status = f"✅ `{event.get('name', '')}` done."
            await _flush(force=True)

        elif etype == "interrupted":
            status = ""
            text_buf += "\n\n⏹ *Kesildi.*"
            await _flush(force=True)
            return

        elif etype == "error":
            err = event.get('message', 'Hata')
            text_buf += f"\n\n❌ `{err}`"
            await _flush(force=True)
            return

    # Final flush: clear status, show clean response
    status = ""
    await _flush(force=True)


def start_bot_thread(agent_factory: Callable, cfg: dict) -> bool:
    """
    Start the Telegram bot in a dedicated daemon thread with its own event loop.
    agent_factory: callable() → Agent (called once per chat_id for isolation).
    Returns True on successful thread start.
    """
    global _bot_cfg
    _bot_cfg = cfg

    token = (
        cfg.get("telegram_token", "").strip()
        or cfg.get("messaging", {}).get("telegram", {}).get("token", "").strip()
    )
    if not token:
        return False

    def _bot_thread():
        # Each thread needs its own event loop for python-telegram-bot v20+
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters
        from telegram.error import Conflict as _Conflict
        from bots.telegram_keyboards import InlineKeyboardManager
        from bots.telegram_notifier import ProactiveNotifier

        app = Application.builder().token(token).concurrent_updates(True).build()

        # ── Inline keyboard manager instance ─────────────────────────────────
        _kb_manager = InlineKeyboardManager()

        # ── ProactiveNotifier initialization via post_init hook ───────────────
        chat_id = cfg.get("messaging", {}).get("telegram", {}).get("chat_id", "")
        notifier = ProactiveNotifier.get_instance()

        async def _post_init(application):
            """Initialize ProactiveNotifier once the bot and loop are ready."""
            notifier.initialize(application.bot, loop, chat_id)
            notifier.schedule_daily_summary()

        app.post_init = _post_init

        # ── Callback query handler for inline buttons ────────────────────────
        async def on_callback_query(update, context):
            """Route inline button presses to the appropriate handler."""
            query = update.callback_query
            await query.answer()  # Acknowledge the callback

            data = query.data  # e.g. "tool:a1b2c3d4:approve"
            if not data:
                return

            parts = data.split(":", 2)
            if len(parts) != 3:
                return

            action_type, identifier, payload = parts

            if action_type == "tool":
                await _handle_tool_callback(query, identifier, payload, _kb_manager)
            elif action_type == "task":
                await _handle_task_callback(query, identifier, payload)

        async def _handle_tool_callback(query, conf_id: str, action: str, kb_manager):
            """Handle tool approve/reject button press."""
            approved = action == "approve"
            pending = kb_manager.resolve_confirmation(conf_id, approved)

            if pending is None:
                await query.edit_message_text("⏰ This confirmation has expired.")
                return

            if approved:
                await query.edit_message_text(
                    f"✅ Approved: `{pending.tool_name}`", parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(
                    f"❌ Rejected: `{pending.tool_name}`", parse_mode="Markdown"
                )

        async def _handle_task_callback(query, task_id: str, action: str):
            """Handle background task status/cancel button press."""
            status = BackgroundTaskManager.get_status(task_id)

            # Task not found — handle for both actions
            if not status:
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text(
                    f"⚠️ Task `{task_id}` not found.", parse_mode="Markdown"
                )
                return

            # If task is in terminal state, remove keyboard and inform user
            if status["status"] in ("done", "error", "cancelled"):
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text(
                    f"Task `{task_id}` is already {status['status']}.",
                    parse_mode="Markdown",
                )
                return

            if action == "status":
                elapsed = status.get("elapsed_seconds", 0)
                persona = status.get("current_persona") or "initializing"
                completed = status.get("completed_subtasks", 0)
                total = status.get("total_subtasks", 0)
                text = (
                    f"📊 **Task {task_id}**\n"
                    f"⏱ Elapsed: {elapsed:.0f}s\n"
                    f"🎭 Current: {persona}\n"
                    f"📋 Progress: {completed}/{total} subtasks"
                )
                await query.message.reply_text(text, parse_mode="Markdown")

            elif action == "cancel":
                success = BackgroundTaskManager.cancel_task(task_id)
                if success:
                    await query.edit_message_reply_markup(reply_markup=None)
                    await query.edit_message_text(
                        f"🛑 Task `{task_id}` cancelled.", parse_mode="Markdown"
                    )
                else:
                    await query.message.reply_text(
                        f"⚠️ Cannot cancel task `{task_id}` — not in a running state.",
                        parse_mode="Markdown",
                    )

        async def on_message(update, context):
            try:
                await _process_message(
                    update, context, agent_factory,
                    kb_manager=_kb_manager, bot_loop=loop,
                )
            except Exception as e:
                logger.error(f"Telegram handler error: {e}", exc_info=True)
                try:
                    chat_id = (update.message or update.edited_message).chat_id
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ Hata: {e}")
                except Exception:
                    pass

        async def on_error(update, context):
            """Handle errors silently — especially Conflict errors."""
            if isinstance(context.error, _Conflict):
                logger.warning("Telegram Conflict: another bot instance is running. Stopping this one.")
                # Don't crash — just log and let polling retry handle it
                return
            logger.error(f"Telegram error: {context.error}", exc_info=context.error)

        app.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.CAPTION) & ~filters.COMMAND,
            on_message,
        ))
        app.add_handler(CallbackQueryHandler(on_callback_query))
        app.add_error_handler(on_error)

        try:
            app.run_polling(
                allowed_updates=["message", "edited_message", "callback_query"],
                drop_pending_updates=True,
                close_loop=False,
            )
        except _Conflict:
            logger.warning("Telegram bot stopped: another instance is already running.")
        except Exception as e:
            logger.error(f"Telegram bot crashed: {e}", exc_info=True)
        finally:
            loop.close()

    t = threading.Thread(target=_bot_thread, daemon=True, name="telegram-bot")
    t.start()
    logger.info("Telegram bot thread started.")
    return True

