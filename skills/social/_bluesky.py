"""Bluesky search and post."""
import urllib.parse
from ._base import _get, _post_json, get_cfg, _now_iso


def bluesky_search(query: str, limit: int = 10) -> str:
    try:
        q = urllib.parse.quote_plus(query)
        data = _get(f"https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q={q}&limit={limit}")
        posts = data.get("posts", [])
        if not posts:
            return "No Bluesky posts found."
        lines = []
        for p in posts:
            author = p.get("author", {})
            record = p.get("record", {})
            text = record.get("text", "")[:200]
            handle = author.get("handle", "")
            like_count = p.get("likeCount", 0)
            repost_count = p.get("repostCount", 0)
            created = record.get("createdAt", "")[:10]
            lines.append(f"🦋 @{handle}: {text}\n   ❤️{like_count}  🔁{repost_count}  [{created}]")
        return "\n\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


def bluesky_post(text: str, handle: str = "", app_password: str = "") -> str:
    try:
        cfg = get_cfg()
        h = handle or cfg.get("bluesky_handle", "")
        pw = app_password or cfg.get("bluesky_app_password", "")
        if not h or not pw:
            return "Bluesky handle and app_password required. Configure in social.bluesky_handle / bluesky_app_password."
        session = _post_json(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            {"identifier": h, "password": pw},
        )
        access_jwt = session.get("accessJwt", "")
        did = session.get("did", "")
        result = _post_json(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            {
                "repo": did,
                "collection": "app.bsky.feed.post",
                "record": {"$type": "app.bsky.feed.post", "text": text[:300], "createdAt": _now_iso()},
            },
            {"Authorization": f"Bearer {access_jwt}"},
        )
        return f"✅ Posted to Bluesky!\nURI: {result.get('uri', '')}"
    except Exception as e:
        return f"ERROR: {e}"
