"""Messaging skill — Telegram bot integration for Koza agent."""
import threading
import asyncio
import queue
import os
from typing import Optional

# ── Telegram bot state ────────────────────────────────────────────────────────
_bot_thread: Optional[threading.Thread] = None
_bot_running = False
_pending_responses: dict = {}  # chat_id → response text

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "telegram_send",
            "description": "Send a message to a Telegram chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Telegram chat ID"},
                    "text": {"type": "string", "description": "Message text"},
                },
                "required": ["chat_id", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "telegram_status",
            "description": "Check if the Telegram bot is running.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def telegram_send(chat_id: str, text: str) -> str:
    try:
        import asyncio as _asyncio
        from telegram import Bot
        from config import load_config
        token = load_config().get("telegram_token", "")
        if not token:
            return "ERROR: telegram_token not set. Run: koza setup"

        async def _send():
            bot = Bot(token=token)
            await bot.send_message(chat_id=int(chat_id), text=text)

        _asyncio.run(_send())
        return f"Sent to {chat_id}"
    except Exception as e:
        return f"ERROR: {e}"


def telegram_status() -> str:
    return "Telegram bot is running." if _bot_running else "Telegram bot is not running. Start with: koza telegram"


HANDLERS = {
    "telegram_send": telegram_send,
    "telegram_status": telegram_status,
}
