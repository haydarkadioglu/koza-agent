"""Discord messaging — send/receive via webhook or bot token."""
import os

_webhook: str = ""
_token: str = ""
_channel_id: str = ""


def init(cfg_discord: dict) -> None:
    global _webhook, _token, _channel_id
    _webhook    = cfg_discord.get("webhook_url", os.getenv("DISCORD_WEBHOOK_URL", ""))
    _token      = cfg_discord.get("token",       os.getenv("DISCORD_TOKEN", ""))
    _channel_id = cfg_discord.get("channel_id",  os.getenv("DISCORD_CHANNEL_ID", ""))


def send(text: str, channel_id: str = "", username: str = "koza") -> str:
    try:
        import requests
    except ImportError:
        return "requests not installed."
    # Webhook (no bot setup needed)
    if _webhook:
        r = requests.post(_webhook, json={"content": text, "username": username}, timeout=10)
        return "✅ Discord sent via webhook" if r.status_code in (200, 204) else f"❌ {r.text}"
    # Bot token fallback
    cid = channel_id or _channel_id
    if not _token or not cid:
        return "Discord not configured. Set DISCORD_WEBHOOK_URL or (DISCORD_TOKEN + DISCORD_CHANNEL_ID)."
    r = requests.post(
        f"https://discord.com/api/v10/channels/{cid}/messages",
        headers={"Authorization": f"Bot {_token}", "Content-Type": "application/json"},
        json={"content": text},
        timeout=10,
    )
    return f"✅ Discord sent to {cid}" if r.ok else f"❌ Discord error: {r.text}"


def get_messages(channel_id: str = "", limit: int = 10) -> str:
    try:
        import requests
    except ImportError:
        return "requests not installed."
    cid = channel_id or _channel_id
    if not _token or not cid:
        return "Discord bot token + channel_id required."
    r = requests.get(
        f"https://discord.com/api/v10/channels/{cid}/messages",
        headers={"Authorization": f"Bot {_token}"},
        params={"limit": limit},
        timeout=10,
    )
    if not r.ok:
        return f"❌ Discord error: {r.text}"
    msgs = r.json()
    return "\n".join(f"[{m['author']['username']}]: {m['content']}" for m in reversed(msgs)) or "No messages."
