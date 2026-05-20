"""Twitter/X search."""
import urllib.parse
from ._base import _get, get_cfg


def twitter_search(query: str, limit: int = 10) -> str:
    token = get_cfg().get("twitter_bearer_token", "")
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
