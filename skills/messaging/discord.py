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


def _resolve_discord_credentials() -> tuple[str, str, str]:
    wh = _webhook or os.getenv("DISCORD_WEBHOOK_URL", "")
    tok = _token or os.getenv("DISCORD_TOKEN", "")
    cid = _channel_id or os.getenv("DISCORD_CHANNEL_ID", "")

    if not wh or not tok or not cid:
        try:
            from config import load_config
            cfg = load_config()
            discord_cfg = cfg.get("messaging", {}).get("discord", {}) or cfg.get("discord", {})
            if not wh:
                wh = discord_cfg.get("webhook_url", "").strip()
            if not tok:
                tok = discord_cfg.get("token", "").strip()
            if not cid:
                cid = discord_cfg.get("channel_id", "").strip()
        except Exception:
            pass

    if not wh or not tok or not cid:
        try:
            from skills import shared_memory
            env_data = shared_memory._read_env()
            if not wh and "DISCORD_WEBHOOK_URL" in env_data:
                wh = env_data["DISCORD_WEBHOOK_URL"][0]
            if not tok and "DISCORD_TOKEN" in env_data:
                tok = env_data["DISCORD_TOKEN"][0]
            if not cid and "DISCORD_CHANNEL_ID" in env_data:
                cid = env_data["DISCORD_CHANNEL_ID"][0]
        except Exception:
            pass

    return wh, tok, cid


def send(text: str, channel_id: str = "", username: str = "koza") -> str:
    try:
        import requests
    except ImportError:
        return "requests not installed."
    wh, tok, cid = _resolve_discord_credentials()
    # Webhook (no bot setup needed)
    if wh:
        r = requests.post(wh, json={"content": text, "username": username}, timeout=10)
        return "✅ Discord sent via webhook" if r.status_code in (200, 204) else f"❌ {r.text}"
    # Bot token fallback
    cid = channel_id or cid
    if not tok or not cid:
        return "Discord not configured. Set DISCORD_WEBHOOK_URL or (DISCORD_TOKEN + DISCORD_CHANNEL_ID)."
    r = requests.post(
        f"https://discord.com/api/v10/channels/{cid}/messages",
        headers={"Authorization": f"Bot {tok}", "Content-Type": "application/json"},
        json={"content": text},
        timeout=10,
    )
    return f"✅ Discord sent to {cid}" if r.ok else f"❌ Discord error: {r.text}"


def get_messages(channel_id: str = "", limit: int = 10) -> str:
    try:
        import requests
    except ImportError:
        return "requests not installed."
    _, tok, cid = _resolve_discord_credentials()
    cid = channel_id or cid
    if not tok or not cid:
        return "Discord bot token + channel_id required."
    r = requests.get(
        f"https://discord.com/api/v10/channels/{cid}/messages",
        headers={"Authorization": f"Bot {tok}"},
        params={"limit": limit},
        timeout=10,
    )
    if not r.ok:
        return f"❌ Discord error: {r.text}"
    msgs = r.json()
    return "\n".join(f"[{m['author']['username']}]: {m['content']}" for m in reversed(msgs)) or "No messages."
