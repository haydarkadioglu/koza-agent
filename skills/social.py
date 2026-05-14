"""Social media skill — Twitter/X, Reddit, Mastodon, Bluesky, HackerNews, LinkedIn, Threads, Instagram."""
import urllib.request
import urllib.parse
import json
import base64

TOOL_DEFINITIONS = [
    # ── Twitter/X ────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "twitter_search",
        "description": "Search recent tweets using Twitter/X API v2.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        }, "required": ["query"]},
    }},
    # ── Reddit ───────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "reddit_search",
        "description": "Search Reddit posts. No API key required.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "subreddit": {"type": "string", "default": "", "description": "Optional subreddit filter"},
            "sort": {"type": "string", "default": "relevance", "enum": ["relevance", "hot", "top", "new"]},
            "limit": {"type": "integer", "default": 5},
        }, "required": ["query"]},
    }},
    # ── Mastodon ─────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "mastodon_post",
        "description": "Post a toot to Mastodon.",
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string"},
            "instance_url": {"type": "string", "default": "https://mastodon.social"},
            "token": {"type": "string", "default": ""},
            "visibility": {"type": "string", "default": "public", "enum": ["public", "unlisted", "private", "direct"]},
        }, "required": ["content"]},
    }},
    # ── Bluesky ──────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "bluesky_search",
        "description": "Search Bluesky posts (AT Protocol). No auth required for public search.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "bluesky_post",
        "description": "Post to Bluesky. Requires your handle (e.g. user.bsky.social) and an App Password from Settings.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "Post text (max 300 chars)"},
            "handle": {"type": "string", "default": "", "description": "Your Bluesky handle"},
            "app_password": {"type": "string", "default": "", "description": "App password from Bluesky settings"},
        }, "required": ["text"]},
    }},
    # ── Hacker News ──────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "hackernews_top",
        "description": "Get top stories from Hacker News. No API key required.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "default": 10},
            "story_type": {"type": "string", "default": "top", "enum": ["top", "new", "best", "ask", "show", "job"]},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "hackernews_search",
        "description": "Search Hacker News stories and comments via Algolia API. No API key required.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
            "sort": {"type": "string", "default": "relevance", "enum": ["relevance", "date"]},
        }, "required": ["query"]},
    }},
    # ── LinkedIn ─────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "linkedin_post",
        "description": "Post a text update to LinkedIn. Requires an OAuth 2.0 access token and your person URN.",
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string", "description": "Post text content"},
            "token": {"type": "string", "default": "", "description": "LinkedIn OAuth 2.0 access token"},
            "person_urn": {"type": "string", "default": "", "description": "Your LinkedIn person URN, e.g. urn:li:person:XXXXXXXX"},
            "visibility": {"type": "string", "default": "PUBLIC", "enum": ["PUBLIC", "CONNECTIONS"]},
        }, "required": ["content"]},
    }},
    # ── Threads (Meta) ───────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "threads_post",
        "description": "Post to Threads (Meta). Requires a Threads API access token and your user ID.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "Post text"},
            "user_id": {"type": "string", "default": "", "description": "Threads user ID"},
            "token": {"type": "string", "default": "", "description": "Threads API access token"},
        }, "required": ["text"]},
    }},
    # ── Instagram ────────────────────────────────────────────────────────────
    {"type": "function", "function": {
        "name": "instagram_post",
        "description": "Post a photo to Instagram via Meta Graph API. Requires a page/user access token and user ID.",
        "parameters": {"type": "object", "properties": {
            "image_url": {"type": "string", "description": "Public URL of the image to post"},
            "caption": {"type": "string", "default": "", "description": "Post caption"},
            "user_id": {"type": "string", "default": "", "description": "Instagram business/creator user ID"},
            "token": {"type": "string", "default": "", "description": "Meta Graph API access token"},
        }, "required": ["image_url"]},
    }},
    {"type": "function", "function": {
        "name": "instagram_get_profile",
        "description": "Get an Instagram business/creator account profile and recent media.",
        "parameters": {"type": "object", "properties": {
            "user_id": {"type": "string", "default": "me", "description": "Instagram user ID or 'me'"},
            "token": {"type": "string", "default": "", "description": "Meta Graph API access token"},
        }, "required": []},
    }},
]

_social_cfg: dict = {}


def init_social(cfg: dict):
    global _social_cfg
    _social_cfg = cfg.get("social", {})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(url: str, headers: dict = None, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _post_json(url: str, data: dict, headers: dict = None) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "KozaAgent/1.0", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _post_form(url: str, fields: dict, headers: dict = None) -> dict:
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "KozaAgent/1.0", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


# ── Twitter/X ─────────────────────────────────────────────────────────────────

def twitter_search(query: str, limit: int = 10) -> str:
    token = _social_cfg.get("twitter_bearer_token", "")
    if not token:
        return "Twitter Bearer Token not configured. Add 'twitter_bearer_token' under social in config."
    try:
        encoded = urllib.parse.quote_plus(query)
        url = (f"https://api.twitter.com/2/tweets/search/recent?query={encoded}"
               f"&max_results={min(limit,100)}&tweet.fields=created_at,author_id,public_metrics")
        data = _get(url, {"Authorization": f"Bearer {token}"})
        tweets = data.get("data", [])
        if not tweets:
            return "No tweets found."
        lines = []
        for t in tweets:
            m = t.get("public_metrics", {})
            lines.append(
                f"🐦 {t['text'][:200]}\n"
                f"   ❤️{m.get('like_count',0)}  🔁{m.get('retweet_count',0)}  "
                f"💬{m.get('reply_count',0)}  [{t.get('created_at','')[:10]}]"
            )
        return "\n\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


# ── Reddit ────────────────────────────────────────────────────────────────────

def reddit_search(query: str, subreddit: str = "", sort: str = "relevance", limit: int = 5) -> str:
    try:
        q = urllib.parse.quote_plus(query)
        if subreddit:
            url = f"https://www.reddit.com/r/{subreddit}/search.json?q={q}&sort={sort}&limit={limit}&restrict_sr=1"
        else:
            url = f"https://www.reddit.com/search.json?q={q}&sort={sort}&limit={limit}"
        data = _get(url)
        posts = data.get("data", {}).get("children", [])
        if not posts:
            return "No results found."
        lines = []
        for post in posts:
            p = post["data"]
            lines.append(
                f"📌 r/{p['subreddit']} — {p['title']}\n"
                f"   ⬆️{p['score']:,}  💬{p['num_comments']}  [{p['author']}]\n"
                f"   https://reddit.com{p['permalink']}"
            )
        return "\n\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


# ── Mastodon ──────────────────────────────────────────────────────────────────

def mastodon_post(content: str, instance_url: str = "", token: str = "", visibility: str = "public") -> str:
    try:
        base = (instance_url or _social_cfg.get("mastodon_instance", "https://mastodon.social")).rstrip("/")
        tok = token or _social_cfg.get("mastodon_token", "")
        if not tok:
            return "Mastodon token not configured. Add 'mastodon_token' under social in config."
        result = _post_form(
            f"{base}/api/v1/statuses",
            {"status": content, "visibility": visibility},
            {"Authorization": f"Bearer {tok}"},
        )
        return f"✅ Toot posted! ID: {result.get('id')}\nURL: {result.get('url')}"
    except Exception as e:
        return f"ERROR: {e}"


# ── Bluesky ───────────────────────────────────────────────────────────────────

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
        h = handle or _social_cfg.get("bluesky_handle", "")
        pw = app_password or _social_cfg.get("bluesky_app_password", "")
        if not h or not pw:
            return "Bluesky handle and app_password required. Configure in social.bluesky_handle / bluesky_app_password."
        # Create session
        session = _post_json(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            {"identifier": h, "password": pw},
        )
        access_jwt = session.get("accessJwt", "")
        did = session.get("did", "")
        # Create post
        result = _post_json(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            {
                "repo": did,
                "collection": "app.bsky.feed.post",
                "record": {"$type": "app.bsky.feed.post", "text": text[:300], "createdAt": _now_iso()},
            },
            {"Authorization": f"Bearer {access_jwt}"},
        )
        uri = result.get("uri", "")
        return f"✅ Posted to Bluesky!\nURI: {uri}"
    except Exception as e:
        return f"ERROR: {e}"


# ── Hacker News ───────────────────────────────────────────────────────────────

def hackernews_top(limit: int = 10, story_type: str = "top") -> str:
    try:
        ids = _get(f"https://hacker-news.firebaseio.com/v0/{story_type}stories.json")
        if not isinstance(ids, list):
            return "Could not fetch story IDs."
        lines = []
        for sid in ids[:limit]:
            story = _get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            title = story.get("title", "")
            url = story.get("url", f"https://news.ycombinator.com/item?id={sid}")
            score = story.get("score", 0)
            by = story.get("by", "")
            comments = story.get("descendants", 0)
            lines.append(f"🔶 {title}\n   ⬆️{score}  💬{comments}  [{by}]\n   {url}")
        return "\n\n".join(lines) if lines else "No stories found."
    except Exception as e:
        return f"ERROR: {e}"


def hackernews_search(query: str, limit: int = 5, sort: str = "relevance") -> str:
    try:
        q = urllib.parse.quote_plus(query)
        order = "search" if sort == "relevance" else "search_by_date"
        data = _get(f"https://hn.algolia.com/api/v1/{order}?query={q}&hitsPerPage={limit}&tags=story")
        hits = data.get("hits", [])
        if not hits:
            return "No results found."
        lines = []
        for h in hits:
            title = h.get("title", "")
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            points = h.get("points", 0)
            author = h.get("author", "")
            comments = h.get("num_comments", 0)
            lines.append(f"🔶 {title}\n   ⬆️{points}  💬{comments}  [{author}]\n   {url}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


# ── LinkedIn ──────────────────────────────────────────────────────────────────

def linkedin_post(content: str, token: str = "", person_urn: str = "", visibility: str = "PUBLIC") -> str:
    try:
        tok = token or _social_cfg.get("linkedin_token", "")
        urn = person_urn or _social_cfg.get("linkedin_person_urn", "")
        if not tok:
            return "LinkedIn access token not configured. Add 'linkedin_token' under social in config."
        if not urn:
            return "LinkedIn person URN not configured. Add 'linkedin_person_urn' (e.g. urn:li:person:XXXXXX) under social in config."
        payload = {
            "author": urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        }
        result = _post_json("https://api.linkedin.com/v2/ugcPosts", payload, {"Authorization": f"Bearer {tok}"})
        post_id = result.get("id", "")
        return f"✅ LinkedIn post published! ID: {post_id}"
    except Exception as e:
        return f"ERROR: {e}"


# ── Threads (Meta) ────────────────────────────────────────────────────────────

def threads_post(text: str, user_id: str = "", token: str = "") -> str:
    try:
        uid = user_id or _social_cfg.get("threads_user_id", "")
        tok = token or _social_cfg.get("threads_token", "")
        if not tok or not uid:
            return "Threads user_id and token required. Configure in social.threads_user_id / threads_token."
        # Step 1: create media container
        container = _get(
            f"https://graph.threads.net/v1.0/{uid}/threads"
            f"?media_type=TEXT&text={urllib.parse.quote_plus(text)}&access_token={tok}"
        )
        cid = container.get("id")
        if not cid:
            return f"Failed to create Threads container: {container}"
        # Step 2: publish
        result = _get(
            f"https://graph.threads.net/v1.0/{uid}/threads_publish"
            f"?creation_id={cid}&access_token={tok}"
        )
        return f"✅ Threads post published! ID: {result.get('id')}"
    except Exception as e:
        return f"ERROR: {e}"


# ── Instagram ─────────────────────────────────────────────────────────────────

def instagram_post(image_url: str, caption: str = "", user_id: str = "", token: str = "") -> str:
    try:
        uid = user_id or _social_cfg.get("instagram_user_id", "")
        tok = token or _social_cfg.get("instagram_token", "")
        if not tok or not uid:
            return "Instagram user_id and token required. Configure in social.instagram_user_id / instagram_token."
        # Step 1: create media object
        q = urllib.parse.urlencode({"image_url": image_url, "caption": caption, "access_token": tok})
        container = _get(f"https://graph.instagram.com/v19.0/{uid}/media?{q}")
        cid = container.get("id")
        if not cid:
            return f"Failed to create media container: {container}"
        # Step 2: publish
        q2 = urllib.parse.urlencode({"creation_id": cid, "access_token": tok})
        result = _get(f"https://graph.instagram.com/v19.0/{uid}/media_publish?{q2}")
        return f"✅ Instagram post published! ID: {result.get('id')}"
    except Exception as e:
        return f"ERROR: {e}"


def instagram_get_profile(user_id: str = "me", token: str = "") -> str:
    try:
        tok = token or _social_cfg.get("instagram_token", "")
        if not tok:
            return "Instagram token not configured. Add 'instagram_token' under social in config."
        uid = user_id or _social_cfg.get("instagram_user_id", "me")
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


# ── Utility ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


HANDLERS = {
    "twitter_search":        twitter_search,
    "reddit_search":         reddit_search,
    "mastodon_post":         mastodon_post,
    "bluesky_search":        bluesky_search,
    "bluesky_post":          bluesky_post,
    "hackernews_top":        hackernews_top,
    "hackernews_search":     hackernews_search,
    "linkedin_post":         linkedin_post,
    "threads_post":          threads_post,
    "instagram_post":        instagram_post,
    "instagram_get_profile": instagram_get_profile,
}
