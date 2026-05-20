"""Reddit search."""
import urllib.parse
from ._base import _get


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
