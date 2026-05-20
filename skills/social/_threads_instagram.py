"""Threads and Instagram post/profile."""
import urllib.parse
from ._base import _get, get_cfg


def threads_post(text: str, user_id: str = "", token: str = "") -> str:
    try:
        cfg = get_cfg()
        uid = user_id or cfg.get("threads_user_id", "")
        tok = token or cfg.get("threads_token", "")
        if not tok or not uid:
            return "Threads user_id and token required. Configure in social.threads_user_id / threads_token."
        container = _get(
            f"https://graph.threads.net/v1.0/{uid}/threads"
            f"?media_type=TEXT&text={urllib.parse.quote_plus(text)}&access_token={tok}"
        )
        cid = container.get("id")
        if not cid:
            return f"Failed to create Threads container: {container}"
        result = _get(
            f"https://graph.threads.net/v1.0/{uid}/threads_publish"
            f"?creation_id={cid}&access_token={tok}"
        )
        return f"✅ Threads post published! ID: {result.get('id')}"
    except Exception as e:
        return f"ERROR: {e}"


def instagram_post(image_url: str, caption: str = "", user_id: str = "", token: str = "") -> str:
    try:
        cfg = get_cfg()
        uid = user_id or cfg.get("instagram_user_id", "")
        tok = token or cfg.get("instagram_token", "")
        if not tok or not uid:
            return "Instagram user_id and token required. Configure in social.instagram_user_id / instagram_token."
        q = urllib.parse.urlencode({"image_url": image_url, "caption": caption, "access_token": tok})
        container = _get(f"https://graph.instagram.com/v19.0/{uid}/media?{q}")
        cid = container.get("id")
        if not cid:
            return f"Failed to create media container: {container}"
        q2 = urllib.parse.urlencode({"creation_id": cid, "access_token": tok})
        result = _get(f"https://graph.instagram.com/v19.0/{uid}/media_publish?{q2}")
        return f"✅ Instagram post published! ID: {result.get('id')}"
    except Exception as e:
        return f"ERROR: {e}"


def instagram_get_profile(user_id: str = "me", token: str = "") -> str:
    try:
        cfg = get_cfg()
        tok = token or cfg.get("instagram_token", "")
        if not tok:
            return "Instagram token not configured. Add 'instagram_token' under social in config."
        uid = user_id or cfg.get("instagram_user_id", "me")
        fields = "id,username,account_type,media_count,followers_count,follows_count,biography,website"
        q = urllib.parse.urlencode({"fields": fields, "access_token": tok})
        data = _get(f"https://graph.instagram.com/v19.0/{uid}?{q}")
        lines = [
            f"📸 @{data.get('username')} (ID: {data.get('id')})",
            f"   Type: {data.get('account_type', '?')}",
            f"   Posts: {data.get('media_count', '?')}  "
            f"Followers: {data.get('followers_count', '?')}  "
            f"Following: {data.get('follows_count', '?')}",
            f"   Bio: {data.get('biography', '')}",
            f"   Web: {data.get('website', '')}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"
