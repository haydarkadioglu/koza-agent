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
    {
        "type": "function",
        "function": {
            "name": "start_telegram_daemon",
            "description": (
                "Start the Telegram bot as a persistent background service. "
                "Call this when the user wants to use Telegram or says 'Telegram'dan konuşalım'. "
                "Requires telegram_token in config. Will set the token if provided."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "token": {
                        "type": "string",
                        "description": "Telegram bot token (optional — only needed if not already configured)",
                    },
                },
                "required": [],
            },
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


def start_telegram_daemon(token: str = "") -> str:
    """Start the Telegram background service (koza_daemon --services-only)."""
    try:
        from config import load_config, save_config
        cfg = load_config()
        if token:
            cfg["telegram_token"] = token.strip()
            save_config(cfg)

        tok = cfg.get("telegram_token", "").strip()
        if not tok:
            return "ERROR: telegram_token not set. Please provide the bot token."

        from koza_daemon import start_services_background, get_daemon_port
        port = get_daemon_port()
        if port is not None:
            return "✅ Telegram daemon already running."

        ok = start_services_background(cfg)
        if ok:
            return "✅ Telegram bot başlatıldı (arka planda çalışıyor)."
        return "⚠️ Daemon zaten çalışıyor veya başlatılamadı. `telegram_status` ile kontrol et."
    except Exception as e:
        return f"ERROR starting Telegram daemon: {e}"


HANDLERS = {
    "telegram_send":   telegram_send,
    "telegram_status": telegram_status,
    "start_telegram_daemon": start_telegram_daemon,
}
