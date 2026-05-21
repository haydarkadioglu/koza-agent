"""Telegram messaging — send/receive via Bot API."""
import os
import time

_token: str = ""
_chat_id: str = ""


def init(cfg_telegram: dict) -> None:
    global _token, _chat_id
    _token   = cfg_telegram.get("token",   os.getenv("TELEGRAM_TOKEN", ""))
    _chat_id = cfg_telegram.get("chat_id", os.getenv("TELEGRAM_CHAT_ID", ""))


def send(text: str, chat_id: str = "", parse_mode: str = "Markdown") -> str:
    try:
        import requests
    except ImportError:
        return "requests not installed."
    cid = chat_id or _chat_id
    if not _token:
        return "Telegram token not configured. Set TELEGRAM_TOKEN."
    if not cid:
        return "Telegram chat_id not configured. Set TELEGRAM_CHAT_ID."
    r = requests.post(
        f"https://api.telegram.org/bot{_token}/sendMessage",
        json={"chat_id": cid, "text": text, "parse_mode": parse_mode},
        timeout=10,
    )
    return f"✅ Telegram sent to {cid}" if r.ok else f"❌ Telegram error: {r.text}"


def get_updates(limit: int = 10, offset: int = 0) -> str:
    try:
        import requests
    except ImportError:
        return "requests not installed."
    if not _token:
        return "Telegram token not configured."
    r = requests.get(
        f"https://api.telegram.org/bot{_token}/getUpdates",
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
        msg    = u.get("message", {})
        sender = msg.get("from", {}).get("username", "unknown")
        text   = msg.get("text", "")
        ts     = time.strftime("%H:%M", time.localtime(msg.get("date", 0)))
        lines.append(f"[{ts}] @{sender}: {text}")
    return "\n".join(lines)


def send_photo(image: str, caption: str = "", chat_id: str = "") -> str:
    """Send a photo to Telegram. `image` can be a file path, HTTP URL, or file_id."""
    try:
        import requests
    except ImportError:
        return "requests not installed."
    cid = chat_id or _chat_id
    if not _token:
        return "Telegram token not configured. Set TELEGRAM_TOKEN."
    if not cid:
        return "Telegram chat_id not configured. Set TELEGRAM_CHAT_ID."

    url = f"https://api.telegram.org/bot{_token}/sendPhoto"

    if image.startswith("http://") or image.startswith("https://"):
        r = requests.post(
            url,
            json={"chat_id": cid, "photo": image, "caption": caption},
            timeout=30,
        )
    else:
        # Local file path
        if not os.path.isfile(image):
            return f"❌ File not found: {image}"
        with open(image, "rb") as f:
            r = requests.post(
                url,
                data={"chat_id": cid, "caption": caption},
                files={"photo": f},
                timeout=60,
            )

    return f"✅ Photo sent to {cid}" if r.ok else f"❌ Telegram error: {r.text}"


def send_video(video: str, caption: str = "", chat_id: str = "") -> str:
    """Send a video to Telegram. `video` can be a local file path or HTTP URL."""
    try:
        import requests
    except ImportError:
        return "requests not installed."
    cid = chat_id or _chat_id
    if not _token:
        return "Telegram token not configured. Set TELEGRAM_TOKEN."
    if not cid:
        return "Telegram chat_id not configured. Set TELEGRAM_CHAT_ID."

    url = f"https://api.telegram.org/bot{_token}/sendVideo"

    if video.startswith("http://") or video.startswith("https://"):
        r = requests.post(
            url,
            json={"chat_id": cid, "video": video, "caption": caption},
            timeout=60,
        )
    else:
        if not os.path.isfile(video):
            return f"❌ File not found: {video}"
        with open(video, "rb") as f:
            r = requests.post(
                url,
                data={"chat_id": cid, "caption": caption},
                files={"video": f},
                timeout=300,
            )

    return f"✅ Video sent to {cid}" if r.ok else f"❌ Telegram error: {r.text}"


def set_webhook(webhook_url: str) -> str:
    try:
        import requests
    except ImportError:
        return "requests not installed."
    if not _token:
        return "Telegram token not configured."
    r = requests.post(
        f"https://api.telegram.org/bot{_token}/setWebhook",
        json={"url": webhook_url},
        timeout=10,
    )
    return f"Webhook set: {r.json().get('description','')}" if r.ok else f"Error: {r.text}"
