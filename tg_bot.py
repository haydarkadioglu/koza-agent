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
            agent = agent_factory()
            agent.permission_callback = None  # auto-allow in Telegram
            _agents[chat_id] = agent
        return _agents[chat_id]


async def _process_message(update, context, agent_factory: Callable):
    """Process one Telegram message: stream agent response back in real time."""
    import queue as _queue
    from telegram.constants import ParseMode, ChatAction

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
            user_text = "Bu fotoğrafı incele."

    if not user_text:
        return

    agent = _get_or_create_agent(chat_id, agent_factory)

    if agent._busy:
        agent.interrupt()
        await context.bot.send_message(chat_id=chat_id, text="⏸ Önceki görev kesildi.")

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    if image_path:
        user_text = f"[Fotoğraf: {image_path}]\n{user_text}"

    # Use a queue so the agent thread can push events and we process them live
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

    worker = threading.Thread(target=_stream_worker, daemon=True)
    worker.start()

    loop = asyncio.get_event_loop()
    sent_msg = None
    buffer = ""

    while True:
        # Poll queue without blocking the event loop
        try:
            event = ev_queue.get_nowait()
        except _queue.Empty:
            await asyncio.sleep(0.05)
            continue

        if event is _DONE:
            break

        if not isinstance(event, dict):
            continue

        etype = event.get("type")

        if etype == "text":
            buffer += event.get("token", "")
            # Flush on newlines or every 200 chars
            if len(buffer) >= 200 or "\n" in event.get("token", ""):
                chunk = buffer[:4096]
                buffer = buffer[4096:]
                if sent_msg is None:
                    sent_msg = await context.bot.send_message(
                        chat_id=chat_id, text=chunk, parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=sent_msg.message_id,
                            text=(await context.bot.get_updates()) and chunk or chunk,
                        )
                    except Exception:
                        sent_msg = await context.bot.send_message(
                            chat_id=chat_id, text=chunk, parse_mode=ParseMode.MARKDOWN
                        )

        elif etype == "tool_start":
            # Flush current text buffer first
            if buffer.strip():
                if sent_msg is None:
                    sent_msg = await context.bot.send_message(
                        chat_id=chat_id, text=buffer[:4096], parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=sent_msg.message_id,
                            text=buffer[-4096:],
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    except Exception:
                        pass
                buffer = ""
                sent_msg = None
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚙️ `{event.get('name', '')}` çalışıyor…",
                parse_mode=ParseMode.MARKDOWN,
            )

        elif etype == "tool_done":
            pass  # silent, result will appear in next text

        elif etype == "interrupted":
            await context.bot.send_message(chat_id=chat_id, text="⏹ Kesildi.")
            return

        elif etype == "error":
            await context.bot.send_message(
                chat_id=chat_id, text=f"❌ `{event.get('message', 'Hata')}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

    # Flush remaining buffer
    if buffer.strip():
        if sent_msg is None:
            await context.bot.send_message(
                chat_id=chat_id, text=buffer[:4096], parse_mode=ParseMode.MARKDOWN
            )
        else:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_msg.message_id,
                    text=buffer[-4096:],
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=chat_id, text=buffer[:4096], parse_mode=ParseMode.MARKDOWN
                )


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

        app.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.CAPTION) & ~filters.COMMAND,
            on_message,
        ))

        try:
            app.run_polling(
                allowed_updates=["message", "edited_message"],
                drop_pending_updates=True,
                close_loop=False,
            )
        except Exception as e:
            logger.error(f"Telegram bot crashed: {e}", exc_info=True)
        finally:
            loop.close()

    t = threading.Thread(target=_bot_thread, daemon=True, name="telegram-bot")
    t.start()
    logger.info("Telegram bot thread started.")
    return True

