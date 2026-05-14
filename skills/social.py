"""Social media skill — Twitter/X, Reddit, Mastodon."""
import urllib.request
import urllib.parse
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "twitter_search",
            "description": "Search recent tweets using Twitter/X API v2.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reddit_search",
            "description": "Search Reddit posts. No API key required.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "subreddit": {"type": "string", "default": "", "description": "Optional subreddit filter"},
                    "sort": {"type": "string", "default": "relevance", "enum": ["relevance", "hot", "top", "new"]},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mastodon_post",
            "description": "Post a toot to Mastodon.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "instance_url": {"type": "string", "default": "https://mastodon.social"},
                    "token": {"type": "string", "default": ""},
                    "visibility": {"type": "string", "default": "public", "enum": ["public", "unlisted", "private", "direct"]},
                },
                "required": ["content"],
            },
        },
    },
]

_social_cfg: dict = {}


def init_social(cfg: dict):
    global _social_cfg
    _social_cfg = cfg.get("social", {})


def twitter_search(query: str, limit: int = 10) -> str:
    token = _social_cfg.get("twitter_bearer_token", "")
    if not token:
        return "Twitter Bearer Token not configured. Add 'twitter_bearer_token' to config."
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://api.twitter.com/2/tweets/search/recent?query={encoded}&max_results={min(limit,100)}&tweet.fields=created_at,author_id,public_metrics"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "User-Agent": "HermesAgent/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        tweets = data.get("data", [])
        if not tweets:
            return "No tweets found."
        lines = []
        for t in tweets:
            metrics = t.get("public_metrics", {})
            lines.append(
                f"🐦 {t['text'][:200]}\n"
                f"   ❤️ {metrics.get('like_count',0)}  🔁 {metrics.get('retweet_count',0)}  "
                f"💬 {metrics.get('reply_count',0)}  [{t.get('created_at','')[:10]}]"
            )
        return "\n\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


def reddit_search(query: str, subreddit: str = "", sort: str = "relevance", limit: int = 5) -> str:
    try:
        q = urllib.parse.quote_plus(query)
        if subreddit:
            url = f"https://www.reddit.com/r/{subreddit}/search.json?q={q}&sort={sort}&limit={limit}&restrict_sr=1"
        else:
            url = f"https://www.reddit.com/search.json?q={q}&sort={sort}&limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "HermesAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        posts = data.get("data", {}).get("children", [])
        if not posts:
            return "No results found."
        lines = []
        for post in posts:
            p = post["data"]
            lines.append(
                f"📌 r/{p['subreddit']} — {p['title']}\n"
                f"   ⬆️ {p['score']:,}  💬 {p['num_comments']}  [{p['author']}]\n"
                f"   https://reddit.com{p['permalink']}"
            )
        return "\n\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


def mastodon_post(content: str, instance_url: str = "", token: str = "",
                  visibility: str = "public") -> str:
    try:
        url = (instance_url or _social_cfg.get("mastodon_instance", "https://mastodon.social")).rstrip("/")
        tok = token or _social_cfg.get("mastodon_token", "")
        if not tok:
            return "Mastodon token not configured."
        data = urllib.parse.urlencode({"status": content, "visibility": visibility}).encode()
        req = urllib.request.Request(
            f"{url}/api/v1/statuses",
            data=data,
            headers={"Authorization": f"Bearer {tok}"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
        return f"Toot posted! ID: {result.get('id')}\nURL: {result.get('url')}"
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {"twitter_search": twitter_search, "reddit_search": reddit_search, "mastodon_post": mastodon_post}
