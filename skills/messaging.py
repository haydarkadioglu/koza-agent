"""Messaging skill — Telegram, Discord, WhatsApp unified interface."""
import json
import os
import threading
import time
from typing import Callable

# ─── Config (injected via init_messaging) ───────────────────────────────────
_telegram_token: str = ""
_telegram_chat_id: str = ""

_discord_webhook: str = ""
_discord_token: str = ""
_discord_channel_id: str = ""

_whatsapp_account_sid: str = ""
_whatsapp_auth_token: str = ""
_whatsapp_from: str = ""     # e.g. "whatsapp:+14155238886"
_whatsapp_to: str = ""       # default recipient

# Incoming message buffer (for listen/polling)
_inbox: list[dict] = []
_listeners: dict[str, threading.Thread] = {}


def init_messaging(cfg: dict) -> None:
    global _telegram_token, _telegram_chat_id
    global _discord_webhook, _discord_token, _discord_channel_id
    global _whatsapp_account_sid, _whatsapp_auth_token, _whatsapp_from, _whatsapp_to

    tg = cfg.get("messaging", {}).get("telegram", {})
    _telegram_token   = tg.get("token", os.getenv("TELEGRAM_TOKEN", ""))
    _telegram_chat_id = tg.get("chat_id", os.getenv("TELEGRAM_CHAT_ID", ""))

    dc = cfg.get("messaging", {}).get("discord", {})
    _discord_webhook    = dc.get("webhook_url", os.getenv("DISCORD_WEBHOOK_URL", ""))
    _discord_token      = dc.get("token", os.getenv("DISCORD_TOKEN", ""))
    _discord_channel_id = dc.get("channel_id", os.getenv("DISCORD_CHANNEL_ID", ""))

    wa = cfg.get("messaging", {}).get("whatsapp", {})
    _whatsapp_account_sid = wa.get("account_sid", os.getenv("TWILIO_ACCOUNT_SID", ""))
    _whatsapp_auth_token  = wa.get("auth_token",  os.getenv("TWILIO_AUTH_TOKEN", ""))
    _whatsapp_from        = wa.get("from",  os.getenv("WHATSAPP_FROM", "whatsapp:+14155238886"))
    _whatsapp_to          = wa.get("to",    os.getenv("WHATSAPP_TO", ""))


# ═══════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════════════════════

def telegram_send(text: str, chat_id: str = "", parse_mode: str = "Markdown") -> str:
    """Send a Telegram message."""
    try:
        import requests
    except ImportError:
        return "requests not installed."
    token = _telegram_token
    cid   = chat_id or _telegram_chat_id
    if not token:
        return "Telegram token not configured. Set TELEGRAM_TOKEN env var."
    if not cid:
        return "Telegram chat_id not configured. Set TELEGRAM_CHAT_ID env var."
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": cid, "text": text, "parse_mode": parse_mode},
        timeout=10,
    )
    if r.ok:
        return f"✅ Telegram message sent to {cid}"
    return f"❌ Telegram error: {r.text}"


def telegram_get_updates(limit: int = 10, offset: int = 0) -> str:
    """Fetch recent Telegram messages (updates)."""
    try:
        import requests
    except ImportError:
        return "requests not installed."
    token = _telegram_token
    if not token:
        return "Telegram token not configured."
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"limit": limit, "offset": offset},
        timeout=10,
    )
    if not r.ok:
        return f"❌ Telegram error: {r.text}"
    updates = r.json().get("result", [])
    if not updates:
        return "No new Telegram messages."
    lines = []
    for u in updates:
        msg = u.get("message", {})
        sender = msg.get("from", {}).get("username", "unknown")
        text   = msg.get("text", "")
        ts     = time.strftime("%H:%M", time.localtime(msg.get("date", 0)))
        lines.append(f"[{ts}] @{sender}: {text}")
    return "\n".join(lines)


def telegram_set_webhook(webhook_url: str) -> str:
    """Set a Telegram webhook URL for receiving messages."""
    try:
        import requests
    except ImportError:
        return "requests not installed."
    token = _telegram_token
    if not token:
        return "Telegram token not configured."
    r = requests.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={"url": webhook_url},
        timeout=10,
    )
    return f"Webhook set: {r.json().get('description','')}" if r.ok else f"Error: {r.text}"


# ═══════════════════════════════════════════════════════════════════════════
# DISCORD
# ═══════════════════════════════════════════════════════════════════════════

def discord_send(text: str, channel_id: str = "", username: str = "Hermes") -> str:
    """Send a Discord message via webhook or bot token."""
    try:
        import requests
    except ImportError:
        return "requests not installed."

    # Try webhook first (simpler, no bot setup needed)
    webhook = _discord_webhook
    if webhook:
        r = requests.post(
            webhook,
            json={"content": text, "username": username},
            timeout=10,
        )
        if r.status_code in (200, 204):
            return "✅ Discord message sent via webhook"
        return f"❌ Discord webhook error: {r.text}"

    # Fall back to bot token + channel ID
    token = _discord_token
    cid   = channel_id or _discord_channel_id
    if not token or not cid:
        return "Discord not configured. Set DISCORD_WEBHOOK_URL or (DISCORD_TOKEN + DISCORD_CHANNEL_ID)."
    r = requests.post(
        f"https://discord.com/api/v10/channels/{cid}/messages",
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        json={"content": text},
        timeout=10,
    )
    if r.ok:
        return f"✅ Discord message sent to channel {cid}"
    return f"❌ Discord error: {r.text}"


def discord_get_messages(channel_id: str = "", limit: int = 10) -> str:
    """Fetch recent Discord messages from a channel (requires bot token)."""
    try:
        import requests
    except ImportError:
        return "requests not installed."
    token = _discord_token
    cid   = channel_id or _discord_channel_id
    if not token or not cid:
        return "Discord bot token + channel_id required."
    r = requests.get(
        f"https://discord.com/api/v10/channels/{cid}/messages",
        headers={"Authorization": f"Bot {token}"},
        params={"limit": limit},
        timeout=10,
    )
    if not r.ok:
        return f"❌ Discord error: {r.text}"
    msgs = r.json()
    if not msgs:
        return "No messages."
    lines = [f"[{m['author']['username']}]: {m['content']}" for m in reversed(msgs)]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# WHATSAPP (via Twilio)
# ═══════════════════════════════════════════════════════════════════════════

def whatsapp_send(text: str, to: str = "") -> str:
    """Send a WhatsApp message via Twilio API."""
    try:
        import requests
        from requests.auth import HTTPBasicAuth
    except ImportError:
        return "requests not installed."
    sid   = _whatsapp_account_sid
    token = _whatsapp_auth_token
    frm   = _whatsapp_from
    to    = to or _whatsapp_to
    if not sid or not token:
        return "WhatsApp/Twilio not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN."
    if not to:
        return "WhatsApp recipient not specified. Set WHATSAPP_TO or pass 'to' parameter."
    if not to.startswith("whatsapp:"):
        to = f"whatsapp:{to}"
    r = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        auth=HTTPBasicAuth(sid, token),
        data={"From": frm, "To": to, "Body": text},
        timeout=10,
    )
    if r.ok:
        data = r.json()
        return f"✅ WhatsApp sent to {to} (SID: {data.get('sid','')})"
    return f"❌ WhatsApp error: {r.text}"


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED ROUTER
# ═══════════════════════════════════════════════════════════════════════════

def send_message(platform: str, text: str, to: str = "") -> str:
    """
    Unified message sender. Routes to Telegram, Discord, or WhatsApp.
    platform: 'telegram' | 'discord' | 'whatsapp'
    """
    p = platform.lower().strip()
    if p == "telegram":
        return telegram_send(text, chat_id=to)
    elif p == "discord":
        return discord_send(text, channel_id=to)
    elif p in ("whatsapp", "wp", "wa"):
        return whatsapp_send(text, to=to)
    else:
        return f"Unknown platform '{platform}'. Use: telegram, discord, whatsapp"


def get_messages(platform: str, limit: int = 10) -> str:
    """Fetch recent messages from a platform."""
    p = platform.lower().strip()
    if p == "telegram":
        return telegram_get_updates(limit=limit)
    elif p == "discord":
        return discord_get_messages(limit=limit)
    elif p in ("whatsapp", "wp", "wa"):
        return "WhatsApp message reading requires webhook setup. Use Twilio webhook listener."
    return f"Unknown platform '{platform}'."


# ═══════════════════════════════════════════════════════════════════════════
# Tool definitions
# ═══════════════════════════════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "name": "send_message",
        "description": "Send a message via Telegram, Discord, or WhatsApp. Use platform='telegram'/'discord'/'whatsapp'.",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "telegram, discord, or whatsapp"},
                "text":     {"type": "string", "description": "Message text to send"},
                "to":       {"type": "string", "description": "Recipient: chat_id (Telegram), channel_id (Discord), phone number (WhatsApp). Uses config default if empty.", "default": ""},
            },
            "required": ["platform", "text"],
        },
    },
    {
        "name": "get_messages",
        "description": "Fetch recent incoming messages from Telegram or Discord.",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "telegram or discord"},
                "limit":    {"type": "integer", "description": "Max messages to fetch", "default": 10},
            },
            "required": ["platform"],
        },
    },
    {
        "name": "telegram_send",
        "description": "Send a Telegram message directly.",
        "parameters": {
            "type": "object",
            "properties": {
                "text":       {"type": "string"},
                "chat_id":    {"type": "string", "default": ""},
                "parse_mode": {"type": "string", "default": "Markdown"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "telegram_get_updates",
        "description": "Get recent Telegram messages / updates.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit":  {"type": "integer", "default": 10},
                "offset": {"type": "integer", "default": 0},
            },
        },
    },
    {
        "name": "discord_send",
        "description": "Send a Discord message via webhook or bot token.",
        "parameters": {
            "type": "object",
            "properties": {
                "text":       {"type": "string"},
                "channel_id": {"type": "string", "default": ""},
                "username":   {"type": "string", "default": "Hermes"},
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
                "channel_id": {"type": "string", "default": ""},
                "limit":      {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "whatsapp_send",
        "description": "Send a WhatsApp message via Twilio.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "to":   {"type": "string", "default": "", "description": "Phone number e.g. +905551234567"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "telegram_set_webhook",
        "description": "Register a Telegram bot webhook URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "webhook_url": {"type": "string"},
            },
            "required": ["webhook_url"],
        },
    },
]

HANDLERS: dict = {
    "send_message":          lambda platform, text, to="": send_message(platform, text, to),
    "get_messages":          lambda platform, limit=10: get_messages(platform, int(limit)),
    "telegram_send":         lambda text, chat_id="", parse_mode="Markdown": telegram_send(text, chat_id, parse_mode),
    "telegram_get_updates":  lambda limit=10, offset=0: telegram_get_updates(int(limit), int(offset)),
    "telegram_set_webhook":  lambda webhook_url: telegram_set_webhook(webhook_url),
    "discord_send":          lambda text, channel_id="", username="Hermes": discord_send(text, channel_id, username),
    "discord_get_messages":  lambda channel_id="", limit=10: discord_get_messages(channel_id, int(limit)),
    "whatsapp_send":         lambda text, to="": whatsapp_send(text, to),
}
