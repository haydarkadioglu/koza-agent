"""
Telegram bot thread for Koza daemon.

Each Telegram chat_id gets its own Agent instance (isolated session).
Messages stream back to the user in real time (chunked text edits).
"""
import asyncio
import logging
import threading
from typing import Dict, Callable

logger = logging.getLogger(__name__)

# chat_id → Agent instance
_agents: Dict[int, object] = {}
_agents_lock = threading.Lock()


def _get_or_create_agent(chat_id: int, agent_factory: Callable):
    with _agents_lock:
        if chat_id not in _agents:
            agent = agent_factory(channel="telegram")
            agent.permission_callback = None  # auto-allow in Telegram
            _agents[chat_id] = agent
        return _agents[chat_id]


async def _process_message(update, context, agent_factory: Callable):
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

    agent = _get_or_create_agent(chat_id, agent_factory)

    if agent._busy:
        agent.interrupt()
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

        from telegram.ext import Application, MessageHandler, filters
        from telegram.error import Conflict as _Conflict

        app = Application.builder().token(token).build()

        async def on_message(update, context):
            try:
                await _process_message(update, context, agent_factory)
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
        app.add_error_handler(on_error)

        try:
            app.run_polling(
                allowed_updates=["message", "edited_message"],
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

