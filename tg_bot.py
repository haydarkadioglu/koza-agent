"""
Koza Telegram Bot
- Arka planda thread olarak çalışır, aynı Agent örneğini kullanır
- İlk mesajı atan kullanıcı otomatik olarak owner olur (config'e kaydedilir)
- Sonraki açılışlarda token varsa otomatik başlar
"""
import asyncio
import logging
import threading
from typing import Optional

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from telegram.constants import ChatAction

logging.basicConfig(level=logging.WARNING)

_bot_thread: Optional[threading.Thread] = None
_app: Optional[Application] = None


def _save_owner(chat_id: int):
    """Save first-message sender as the only allowed chat_id."""
    try:
        from config import load_config, save_config
        c = load_config()
        c["telegram_owner_id"] = chat_id
        save_config(c)
    except Exception:
        pass


async def _stream_reply(agent, user_text: str, update: Update):
    """Run agent.stream_chat (sync generator) in a thread and reply."""
    chat_id = update.effective_chat.id
    bot = update.get_bot()
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    full = ""
    tool_log = []

    # stream_chat is a sync generator — run in executor to avoid blocking event loop
    loop = asyncio.get_event_loop()

    def _collect():
        nonlocal full, tool_log
        for event in agent.stream_chat(user_text):
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype == "text":
                full += event.get("token", "")
            elif etype == "tool_start":
                tool_log.append(f"⚙ {event['name']}")
            elif etype == "tool_done":
                elapsed = event.get("elapsed", 0)
                if tool_log:
                    tool_log[-1] += f"  ✓  {elapsed:.1f}s"

    await loop.run_in_executor(None, _collect)

    reply = ""
    if tool_log:
        reply += "\n".join(tool_log) + "\n\n"
    reply += full or "(yanıt yok)"

    for i in range(0, len(reply), 4096):
        await bot.send_message(chat_id=chat_id, text=reply[i:i + 4096])


async def _on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = context.bot_data["cfg"]
    owner_id = cfg.get("telegram_owner_id")
    sender_id = update.effective_user.id

    if not owner_id:
        # First contact — register as owner
        _save_owner(sender_id)
        context.bot_data["cfg"]["telegram_owner_id"] = sender_id
        await update.message.reply_text(
            "👋 Koza Agent aktif!\n"
            "Sen artık bu botun sahibisin. Soru sorabilirsin."
        )
    elif sender_id == owner_id:
        await update.message.reply_text("👋 Koza Agent hazır.")
    else:
        await update.message.reply_text("⛔ Bu bot özel kullanım içindir.")


async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = context.bot_data["cfg"]
    owner_id = cfg.get("telegram_owner_id")
    sender_id = update.effective_user.id

    # Auto-register first sender as owner
    if not owner_id:
        _save_owner(sender_id)
        context.bot_data["cfg"]["telegram_owner_id"] = sender_id
        owner_id = sender_id

    if sender_id != owner_id:
        await update.message.reply_text("⛔ Yetkisiz kullanıcı.")
        return

    agent = context.bot_data["agent"]
    await _stream_reply(agent, update.message.text, update)


def start_bot_thread(agent, cfg: dict) -> bool:
    """
    Start the Telegram bot in a background daemon thread.
    Returns True if started, False if no token configured.
    """
    global _bot_thread, _app

    token = cfg.get("telegram_token", "").strip()
    if not token:
        return False

    if _bot_thread and _bot_thread.is_alive():
        return True  # already running

    def _run():
        global _app
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        app = Application.builder().token(token).build()
        app.bot_data["agent"] = agent
        app.bot_data["cfg"] = cfg

        app.add_handler(CommandHandler("start", _on_start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))

        _app = app
        app.run_polling(drop_pending_updates=True, stop_signals=None)

    _bot_thread = threading.Thread(target=_run, daemon=True, name="koza-telegram")
    _bot_thread.start()
    return True


def run_bot_foreground(token: str, cfg: dict, agent=None):
    """Run bot in foreground (blocking). Used by `koza telegram` command."""
    if agent is None:
        from config import load_config
        from providers.factory import get_provider
        from core import Agent
        cfg = load_config()
        agent = Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg)
        agent.permission_callback = None

    app = Application.builder().token(token).build()
    app.bot_data["agent"] = agent
    app.bot_data["cfg"] = cfg

    app.add_handler(CommandHandler("start", _on_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))

    print(f"  🤖  Koza Telegram Bot dinleniyor. Durdurmak için Ctrl+C\n")
    app.run_polling(drop_pending_updates=True)

