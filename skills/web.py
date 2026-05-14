"""Web skill — search DuckDuckGo and fetch URLs."""
import urllib.parse
import urllib.request
import json
import html
import re

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo. Returns top results with titles, URLs, and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch the text content of a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 4000},
                },
                "required": ["url"],
            },
        },
    },
]


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def web_search(query: str, max_results: int = 5) -> str:
    """DuckDuckGo Instant Answer API (no key required)."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"
        req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        results = []
        if data.get("AbstractText"):
            results.append(f"[Summary] {data['AbstractText']}\n  {data.get('AbstractURL','')}")
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(f"- {topic['Text']}\n  {topic.get('FirstURL','')}")
        return "\n\n".join(results) if results else "No results found."
    except Exception as e:
        return f"ERROR: {e}"


def fetch_url(url: str, max_chars: int = 4000) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8", errors="replace")
        if "html" in content_type:
            raw = _strip_html(raw)
        return raw[:max_chars] + ("..." if len(raw) > max_chars else "")
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {"web_search": web_search, "fetch_url": fetch_url}
