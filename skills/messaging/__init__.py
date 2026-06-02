"""
Messaging package — Telegram, Discord, WhatsApp, Twilio.
Exports TOOL_DEFINITIONS and HANDLERS for core.py.
"""
from __future__ import annotations

from . import telegram     as _tg
from . import discord      as _dc
from . import whatsapp     as _wa
from . import twilio_skill as _tw


def init_messaging(cfg: dict) -> None:
    _tg.init(cfg.get("telegram", {}))
    _dc.init(cfg.get("discord", {}))
    _wa.init(cfg.get("whatsapp", {}))
    _tw.init(cfg.get("twilio", {}))


# ── Unified router ────────────────────────────────────────────────────────────

def send_message(platform: str, text: str, recipient: str = "") -> str:
    p = platform.lower()
    if p == "telegram":
        return _tg.send(text, chat_id=recipient)
    if p == "discord":
        return _dc.send(text, channel_id=recipient)
    if p == "whatsapp":
        return _wa.send(text, to=recipient)
    if p in ("twilio", "sms"):
        return _tw.send_sms(to=recipient, body=text)
    return f"Unknown platform: {platform}. Use telegram/discord/whatsapp/sms."


def get_messages(platform: str, limit: int = 10) -> str:
    p = platform.lower()
    if p == "telegram":
        return _tg.get_updates(limit=limit)
    if p == "discord":
        return _dc.get_messages(limit=limit)
    if p in ("twilio", "sms"):
        return _tw.list_sms(limit=limit)
    return f"get_messages not supported for {platform}."


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "send_message",
        "description": "Send a message on Telegram, Discord, WhatsApp, or SMS (Twilio).",
        "parameters": {
            "type": "object",
            "properties": {
                "platform":  {"type": "string", "description": "telegram | discord | whatsapp | sms"},
                "text":      {"type": "string", "description": "Message content"},
                "recipient": {"type": "string", "description": "chat_id / channel_id / phone in E.164 (optional if configured)"},
            },
            "required": ["platform", "text"],
        },
    },
    {
        "name": "get_messages",
        "description": "Retrieve recent messages from Telegram, Discord, or Twilio SMS.",
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "telegram | discord | sms"},
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
        "description": "Send a photo to Telegram. Accepts a local file path, HTTP/HTTPS URL, or Telegram file_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "image":   {"type": "string", "description": "File path, HTTPS URL, or Telegram file_id"},
                "caption": {"type": "string", "description": "Optional caption text"},
                "chat_id": {"type": "string", "description": "Override chat_id (optional)"},
            },
            "required": ["image"],
        },
    },
    {
        "name": "telegram_send_video",
        "description": "Send a video to Telegram. Accepts a local .mp4 file path or HTTP/HTTPS URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "video":   {"type": "string", "description": "File path or HTTPS URL of the video"},
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
    # ── Twilio tools ───────────────────────────────────────────────────────────
    {
        "name": "twilio_send_sms",
        "description": "Send an SMS message via Twilio to any phone number.",
        "parameters": {
            "type": "object",
            "properties": {
                "to":          {"type": "string",  "description": "Recipient phone in E.164 format (e.g. +905551234567)"},
                "body":        {"type": "string",  "description": "SMS message text"},
                "from_number": {"type": "string",  "description": "Override sender number (optional if configured)"},
            },
            "required": ["to", "body"],
        },
    },
    {
        "name": "twilio_send_whatsapp",
        "description": "Send a WhatsApp message via Twilio (uses configured wa_from / wa_to).",
        "parameters": {
            "type": "object",
            "properties": {
                "body":    {"type": "string", "description": "Message text"},
                "to":      {"type": "string", "description": "Recipient WhatsApp number in E.164 format (optional if configured)"},
                "from_wa": {"type": "string", "description": "Override sender WhatsApp number (optional)"},
            },
            "required": ["body"],
        },
    },
    {
        "name": "twilio_make_call",
        "description": "Make an outbound voice call via Twilio. Can speak a text message (TTS) or execute custom TwiML.",
        "parameters": {
            "type": "object",
            "properties": {
                "to":          {"type": "string", "description": "Recipient phone in E.164 format"},
                "message":     {"type": "string", "description": "Text to speak (TTS). Mutually exclusive with twiml."},
                "twiml":       {"type": "string", "description": "Custom TwiML XML. Use for advanced call flows."},
                "from_number": {"type": "string", "description": "Override caller ID (optional)"},
            },
            "required": ["to"],
        },
    },
    {
        "name": "twilio_call_status",
        "description": "Get the status and duration of a Twilio voice call by its SID.",
        "parameters": {
            "type": "object",
            "properties": {
                "call_sid": {"type": "string", "description": "The Twilio call SID (e.g. CA...)"},
            },
            "required": ["call_sid"],
        },
    },
    {
        "name": "twilio_list_messages",
        "description": "List recent SMS/WhatsApp messages from the Twilio account.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit":       {"type": "integer", "description": "Max messages to return (default 10)"},
                "to_filter":   {"type": "string",  "description": "Filter by recipient number (optional)"},
                "from_filter": {"type": "string",  "description": "Filter by sender number (optional)"},
            },
        },
    },
    {
        "name": "twilio_lookup_phone",
        "description": "Look up carrier information and line type for a phone number using Twilio Lookup.",
        "parameters": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string", "description": "Phone number in E.164 format (e.g. +905551234567)"},
            },
            "required": ["phone_number"],
        },
    },
    {
        "name": "twilio_account_info",
        "description": "Get Twilio account status and balance.",
        "parameters": {"type": "object", "properties": {}},
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
    # Twilio
    "twilio_send_sms":      lambda to, body, from_number="": _tw.send_sms(to, body, from_number),
    "twilio_send_whatsapp": lambda body, to="", from_wa="": _tw.send_whatsapp(to=to, body=body, from_wa=from_wa),
    "twilio_make_call":     lambda to, message="", twiml="", from_number="":
                                _tw.make_call(to, message, twiml, from_number),
    "twilio_call_status":   lambda call_sid: _tw.get_call_status(call_sid),
    "twilio_list_messages": lambda limit=10, to_filter="", from_filter="":
                                _tw.list_sms(int(limit), to_filter, from_filter),
    "twilio_lookup_phone":  lambda phone_number: _tw.lookup_phone(phone_number),
    "twilio_account_info":  lambda **_: _tw.get_account_info(),
}



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


def telegram_status() -> str:
    try:
        from koza_daemon import get_daemon_port, PID_FILE, LOG_FILE
        port = get_daemon_port()
        if port is not None:
            pid = PID_FILE.read_text().strip() if PID_FILE.exists() else "?"
            return (
                f"Background daemon detected (PID {pid}, port marker {port}). "
                "This does not prove Telegram API polling is healthy. "
                f"Check logs with `koza logs` or inspect {LOG_FILE}."
            )
    except Exception as e:
        return f"ERROR checking Telegram daemon: {e}"
    return "Telegram daemon is not running. Use start_telegram_daemon after saving the token."


def start_telegram_daemon(token: str = "") -> str:
    """Persist token if provided and start the services-only daemon."""
    try:
        from config import load_config, save_config
        cfg = load_config()
        if token:
            token = token.strip()
            cfg["telegram_token"] = token
            cfg.setdefault("messaging", {}).setdefault("telegram", {})["token"] = token
            save_config(cfg)

        tok = (
            cfg.get("telegram_token", "").strip()
            or cfg.get("messaging", {}).get("telegram", {}).get("token", "").strip()
        )
        if not tok:
            return "ERROR: Telegram token is not configured."

        from koza_daemon import get_daemon_port, start_services_background
        if get_daemon_port() is not None:
            return "Background daemon already running; Telegram API connectivity is not verified. Check `koza logs`."
        ok = start_services_background(cfg)
        if ok:
            return "Telegram daemon launched. Send /start or a message to the bot, then check `koza logs` if it does not respond."
        return "Telegram daemon could not be started. Run `koza status` and `koza logs`."
    except Exception as e:
        return f"ERROR starting Telegram daemon: {e}"


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
        "name": "telegram_status",
        "description": "Check whether the Telegram/background daemon appears to be running.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "start_telegram_daemon",
        "description": "Start Telegram bot background service. Saves the token first if provided.",
        "parameters": {
            "type": "object",
            "properties": {
                "token": {"type": "string", "description": "Optional Telegram bot token"},
            },
            "required": [],
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
    "telegram_status":      lambda **_: telegram_status(),
    "start_telegram_daemon": lambda token="": start_telegram_daemon(token),
    "telegram_set_webhook": lambda webhook_url: _tg.set_webhook(webhook_url),
    "discord_send":         lambda text, channel_id="": _dc.send(text, channel_id=channel_id),
    "discord_get_messages": lambda channel_id="", limit=10:
                                _dc.get_messages(channel_id=channel_id, limit=int(limit)),
    "whatsapp_send":        lambda text, to="": _wa.send(text, to=to),
}
