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
    """Fetch URL content. Falls back to headless browser for JS-rendered pages."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8", errors="replace")

        if "html" in content_type:
            text = _strip_html(raw)
            # If content is too short, likely a JS-rendered page (Next.js, React, etc.)
            if len(text.strip()) < 200 and ("__next" in raw or "__NEXT_DATA__" in raw
                                            or "react-root" in raw or "app-root" in raw
                                            or "_nuxt" in raw):
                rendered = _fetch_with_browser(url, max_chars)
                if rendered:
                    return rendered
            return text[:max_chars] + ("..." if len(text) > max_chars else "")
        else:
            return raw[:max_chars] + ("..." if len(raw) > max_chars else "")
    except Exception as e:
        return f"ERROR: {e}"


def _fetch_with_browser(url: str, max_chars: int = 4000) -> str:
    """Use Playwright headless browser to render JS and extract text content."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ""  # Playwright not installed — fall back silently

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=20000, wait_until="networkidle")
            # Wait a bit for dynamic content to load
            page.wait_for_timeout(1500)
            # Extract visible text content
            text = page.inner_text("body")
            browser.close()

        # Clean up whitespace
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    except Exception as e:
        return f"(browser render failed: {e})"


HANDLERS = {"web_search": web_search, "fetch_url": fetch_url}
