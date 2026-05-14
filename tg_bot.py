"""
Koza Telegram Bot — run with: koza telegram
Polls for messages and processes them through the Koza agent.
"""
import asyncio
import logging
import sys
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from telegram.constants import ChatAction

logging.basicConfig(level=logging.WARNING)


def _build_agent():
    from config import load_config
    from providers.factory import get_provider
    from core import Agent
    cfg = load_config()
    provider = get_provider(cfg)
    return Agent(provider, db_path=cfg["db_path"], cfg=cfg), cfg


async def _stream_to_telegram(agent, user_text: str, update: Update):
    """Run agent.stream_chat and send collected response to Telegram."""
    chat_id = update.effective_chat.id
    bot = update.get_bot()

    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    full = ""
    tool_log = []

    for event in agent.stream_chat(user_text):
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "text":
            full += event.get("token", "")
        elif etype == "tool_start":
            tool_log.append(f"⚙ {event['name']}")
        elif etype == "tool_done":
            pass  # already logged on start

    # Build reply
    reply = ""
    if tool_log:
        reply += "\n".join(tool_log) + "\n\n"
    reply += full or "(no response)"

    # Telegram max message length = 4096
    for i in range(0, len(reply), 4096):
        await bot.send_message(chat_id=chat_id, text=reply[i:i+4096])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Koza Agent hazır. Soru sorabilirsin."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = context.bot_data["agent"]
    user_text = update.message.text
    await _stream_to_telegram(agent, user_text, update)


def run_bot(token: str, allowed_users: list = None):
    agent, cfg = _build_agent()

    # Auto-allow all tools in telegram mode (no interactive TTY)
    agent.permission_callback = None

    app = Application.builder().token(token).build()
    app.bot_data["agent"] = agent

    app.add_handler(CommandHandler("start", start))

    if allowed_users:
        user_filter = filters.User(username=allowed_users)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, handle_message))
    else:
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"  🤖  Koza Telegram Bot başlatıldı. Durdurmak için Ctrl+C\n")
    app.run_polling(drop_pending_updates=True)
