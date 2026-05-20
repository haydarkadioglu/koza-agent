"""HackerNews top stories and search."""
import urllib.parse
from ._base import _get


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
