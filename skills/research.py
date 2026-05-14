"""Research skill — arXiv, Wikipedia, Polymarket, general research."""
import urllib.request
import urllib.parse
import json
import xml.etree.ElementTree as ET

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "arxiv_search",
            "description": "Search arXiv for academic papers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                    "category": {"type": "string", "default": "", "description": "e.g. cs.AI, physics, math"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wikipedia_search",
            "description": "Search and get a Wikipedia article summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "language": {"type": "string", "default": "en"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "polymarket_search",
            "description": "Search Polymarket prediction markets and get current odds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
]


def _fetch(url: str, headers: dict = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def arxiv_search(query: str, limit: int = 5, category: str = "") -> str:
    try:
        q = urllib.parse.quote_plus(query)
        cat_filter = f"+AND+cat:{category}" if category else ""
        url = f"https://export.arxiv.org/api/query?search_query=all:{q}{cat_filter}&max_results={limit}&sortBy=relevance"
        raw = _fetch(url)
        root = ET.fromstring(raw)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = root.findall("a:entry", ns)
        if not entries:
            return "No papers found."
        lines = []
        for entry in entries:
            title = (entry.findtext("a:title", "", ns) or "").strip().replace("\n", " ")
            summary = (entry.findtext("a:summary", "", ns) or "").strip()[:200].replace("\n", " ")
            link = entry.findtext("a:id", "", ns)
            authors = [a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)][:3]
            published = (entry.findtext("a:published", "", ns) or "")[:10]
            lines.append(f"📄 {title}\n   Authors: {', '.join(authors)}\n   {published}\n   {link}\n   {summary}...")
        return "\n\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


def wikipedia_search(query: str, language: str = "en") -> str:
    try:
        q = urllib.parse.quote_plus(query)
        url = f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{q}"
        raw = _fetch(url)
        data = json.loads(raw)
        title = data.get("title", "")
        extract = data.get("extract", "No summary available.")
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
        return f"📖 {title}\n\n{extract}\n\n{page_url}"
    except urllib.request.HTTPError as e:
        if e.code == 404:
            # Try search instead
            try:
                q = urllib.parse.quote_plus(query)
                url = f"https://{language}.wikipedia.org/w/api.php?action=opensearch&search={q}&limit=1&format=json"
                raw = _fetch(url)
                data = json.loads(raw)
                if data[1]:
                    return wikipedia_search(data[1][0], language)
            except Exception:
                pass
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def polymarket_search(query: str, limit: int = 5) -> str:
    try:
        q = urllib.parse.quote_plus(query)
        url = f"https://gamma-api.polymarket.com/markets?search={q}&limit={limit}&active=true&closed=false"
        raw = _fetch(url)
        markets = json.loads(raw)
        if not markets:
            return "No Polymarket markets found."
        lines = [f"Polymarket results for '{query}':"]
        for m in markets[:limit]:
            question = m.get("question", m.get("title", ""))
            volume = m.get("volumeNum", 0)
            outcomes = m.get("outcomes", "[]")
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            prices = m.get("outcomePrices", "[]")
            if isinstance(prices, str):
                prices = json.loads(prices)
            odds = ""
            if outcomes and prices:
                odds = "  |  ".join(f"{o}: {float(p)*100:.1f}%" for o, p in zip(outcomes, prices))
            lines.append(f"\n📊 {question}\n   Odds: {odds}\n   Volume: ${volume:,.0f}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "arxiv_search": arxiv_search,
    "wikipedia_search": wikipedia_search,
    "polymarket_search": polymarket_search,
}
