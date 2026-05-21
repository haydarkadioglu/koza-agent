"""
Messaging package — Telegram, Discord, WhatsApp.
Exports TOOL_DEFINITIONS and HANDLERS for core.py.
"""
from __future__ import annotations

from . import telegram as _tg
from . import discord  as _dc
from . import whatsapp as _wa


def init_messaging(cfg: dict) -> None:
    _tg.init(cfg.get("telegram", {}))
    _dc.init(cfg.get("discord", {}))
    _wa.init(cfg.get("whatsapp", {}))


# ── Unified router ────────────────────────────────────────────────────────────

def send_message(platform: str, text: str, recipient: str = "") -> str:
    p = platform.lower()
    if p == "telegram":
        return _tg.send(text, chat_id=recipient)
    if p == "discord":
        return _dc.send(text, channel_id=recipient)
    if p == "whatsapp":
        return _wa.send(text, to=recipient)
    return f"Unknown platform: {platform}. Use telegram/discord/whatsapp."


def get_messages(platform: str, limit: int = 10) -> str:
    p = platform.lower()
    if p == "telegram":
        return _tg.get_updates(limit=limit)
    if p == "discord":
        return _dc.get_messages(limit=limit)
    return f"get_messages not supported for {platform}."


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "send_message",
        "description": "Send a message on Telegram, Discord, or WhatsApp.",
        "parameters": {
            "type": "object",
            "properties": {
                "platform":  {"type": "string", "description": "telegram | discord | whatsapp"},
                "text":      {"type": "string", "description": "Message content"},
                "recipient": {"type": "string", "description": "chat_id / channel_id / phone (optional if configured)"},
            },
            "required": ["platform", "text"],
        },
    },
    {
        "name": "get_messages",
        "description": "Retrieve recent messages from Telegram or Discord.",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "telegram | discord"},
                "limit":    {"type": "integer", "description": "Max messages to return"},
            },
            "required": ["platform"],
        },
    },
    {
        "name": "telegram_send",
        "description": "Send a Telegram message directly via bot token.",
        "parameters": {
            "type": "object",
            "properties": {
                "text":      {"type": "string", "description": "Message text"},
                "chat_id":   {"type": "string", "description": "Override chat_id (optional)"},
                "parse_mode":{"type": "string", "description": "Markdown or HTML"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "telegram_get_updates",
        "description": "Fetch latest Telegram bot updates/messages.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit":  {"type": "integer", "description": "Max updates"},
                "offset": {"type": "integer", "description": "Offset for pagination"},
            },
        },
    },
    {
        "name": "telegram_send_photo",
        "description": "Send a photo to Telegram. Accepts a local file path, HTTP/HTTPS URL, or Telegram file_id. Use generate_image first to create an image, then send it here.",
        "parameters": {
            "type": "object",
            "properties": {
                "image":   {"type": "string", "description": "File path, HTTPS URL, or Telegram file_id of the image"},
                "caption": {"type": "string", "description": "Optional caption text"},
                "chat_id": {"type": "string", "description": "Override chat_id (optional)"},
            },
            "required": ["image"],
        },
    },
    {
        "name": "telegram_send_video",
        "description": "Send a video to Telegram. Accepts a local .mp4 file path or HTTP/HTTPS URL. Use generate_video first to create a video, then send it here.",
        "parameters": {
            "type": "object",
            "properties": {
                "video":   {"type": "string", "description": "File path or HTTPS URL of the video (.mp4)"},
                "caption": {"type": "string", "description": "Optional caption text"},
                "chat_id": {"type": "string", "description": "Override chat_id (optional)"},
            },
            "required": ["video"],
        },
    },
    {
        "name": "telegram_set_webhook",
        "description": "Set or update the Telegram bot webhook URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "webhook_url": {"type": "string", "description": "HTTPS URL for webhook"},
            },
            "required": ["webhook_url"],
        },
    },
    {
        "name": "discord_send",
        "description": "Send a message to a Discord channel or webhook.",
        "parameters": {
            "type": "object",
            "properties": {
                "text":       {"type": "string", "description": "Message content"},
                "channel_id": {"type": "string", "description": "Override channel_id (optional)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "discord_get_messages",
        "description": "Fetch recent messages from a Discord channel.",
        "parameters": {
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Override channel_id (optional)"},
                "limit":      {"type": "integer", "description": "Max messages"},
            },
        },
    },
    {
        "name": "whatsapp_send",
        "description": "Send a WhatsApp message via Twilio.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Message content"},
                "to":   {"type": "string",  "description": "Destination WhatsApp number (optional if configured)"},
            },
            "required": ["text"],
        },
    },
]

HANDLERS = {
    "send_message":         lambda platform, text, recipient="":
                                send_message(platform, text, recipient),
    "get_messages":         lambda platform, limit=10:
                                get_messages(platform, int(limit)),
    "telegram_send_photo": lambda image, caption="", chat_id="": _tg.send_photo(image, caption=caption, chat_id=chat_id),
    "telegram_send_video": lambda video, caption="", chat_id="": _tg.send_video(video, caption=caption, chat_id=chat_id),
    "telegram_send":        lambda text, chat_id="", parse_mode="Markdown":
                                _tg.send(text, chat_id=chat_id, parse_mode=parse_mode),
    "telegram_get_updates": lambda limit=10, offset=0:
                                _tg.get_updates(int(limit), int(offset)),
    "telegram_set_webhook": lambda webhook_url: _tg.set_webhook(webhook_url),
    "discord_send":         lambda text, channel_id="": _dc.send(text, channel_id=channel_id),
    "discord_get_messages": lambda channel_id="", limit=10:
                                _dc.get_messages(channel_id=channel_id, limit=int(limit)),
    "whatsapp_send":        lambda text, to="": _wa.send(text, to=to),
}
