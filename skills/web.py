"""Web skill — search DuckDuckGo and fetch URLs."""
import urllib.parse
import urllib.request
import html
import re
import threading
import time
import requests
import ipaddress
import socket

def is_safe_url(url: str) -> bool:
    """SSRF Guard: Resolve and validate target host IP to prevent private/loopback connections."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname
        if not host:
            return False
        if host.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        for info in infos:
            ip_str = info[4][0]
            ip = ipaddress.ip_address(ip_str)
            if (ip.is_private or 
                ip.is_loopback or 
                ip.is_link_local or 
                ip.is_reserved or 
                ip.is_multicast or 
                ip.is_unspecified):
                return False
        return True
    except Exception:
        return False

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web. Tries a conservative Google HTML request first, "
                "then falls back to DuckDuckGo if Google blocks, rate-limits, or returns no parseable results. "
                "Returns top results with titles, URLs, and snippets."
            ),
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
            "description": (
                "Fetch the text content of a URL. "
                "For JavaScript-rendered sites (Next.js, React, Vue, Nuxt, Firebase, etc.) "
                "set js_render=true to use a headless browser. "
                "If you're not sure whether the site is JS-rendered, set js_render=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 4000},
                    "js_render": {"type": "boolean", "default": False,
                                  "description": "Use headless browser for JS-rendered pages (Next.js, React, Vue, etc.)"},
                },
                "required": ["url"],
            },
        },
    },
]

_GOOGLE_MIN_INTERVAL_SECONDS = 8.0
_DUCKDUCKGO_MIN_INTERVAL_SECONDS = 4.0
_SEARCH_CACHE_TTL_SECONDS = 300.0
_google_lock = threading.Lock()
_duckduckgo_lock = threading.Lock()
_last_google_request_at = 0.0
_last_duckduckgo_request_at = 0.0
_search_cache: dict[tuple[str, int], tuple[float, str]] = {}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def web_search(query: str, max_results: int = 5) -> str:
    """Search Google HTML conservatively, with DuckDuckGo fallback."""
    cache_key = (query.strip().lower(), max_results)
    now = time.time()
    cached = _search_cache.get(cache_key)
    if cached and now - cached[0] < _SEARCH_CACHE_TTL_SECONDS:
        return cached[1]

    google_result = _google_html_search(query, max_results)
    if google_result and not google_result.startswith("ERROR:"):
        _search_cache[cache_key] = (now, google_result)
        return google_result

    ddg_result = _duckduckgo_search(query, max_results)
    if google_result.startswith("ERROR:") and ddg_result and not ddg_result.startswith("ERROR:"):
        result = f"{ddg_result}\n\n(Search note: Google HTML fallback used DuckDuckGo. {google_result[7:]})"
    elif google_result.startswith("ERROR:") and ddg_result.startswith("ERROR:"):
        result = f"ERROR: Google failed ({google_result[7:]}). DuckDuckGo also failed ({ddg_result[7:]})."
    else:
        result = ddg_result
    _search_cache[cache_key] = (now, result)
    return result


def _duckduckgo_search(query: str, max_results: int = 5) -> str:
    """DuckDuckGo Instant Answer API (no key required)."""
    try:
        _wait_for_duckduckgo_slot()
        encoded = urllib.parse.quote_plus(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"
        resp = requests.get(url, headers={"User-Agent": "KozaAgent/1.0"}, timeout=10)
        resp.raise_for_status()
        if not resp.text.strip():
            return _duckduckgo_html_search(query, max_results)
        data = resp.json()

        results = []
        if data.get("AbstractText"):
            results.append(f"[Summary] {data['AbstractText']}\n  {data.get('AbstractURL','')}")
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(f"- {topic['Text']}\n  {topic.get('FirstURL','')}")
        if results:
            return "\n\n".join(results)
        return _duckduckgo_html_search(query, max_results)
    except Exception as e:
        html_result = _duckduckgo_html_search(query, max_results)
        if html_result and not html_result.startswith("ERROR:"):
            return html_result
        return f"ERROR: {e}"


def _duckduckgo_html_search(query: str, max_results: int = 5) -> str:
    """DuckDuckGo HTML results fallback when the instant-answer API is empty."""
    try:
        _wait_for_duckduckgo_slot()
        url = "https://html.duckduckgo.com/html/"
        resp = requests.get(url, params={"q": query}, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }, timeout=15)
        resp.raise_for_status()
        if resp.status_code == 202:
            return "ERROR: DuckDuckGo returned a rate-limit/challenge page."

        results = []
        for match in re.finditer(r'<a\s+([^>]*)>(.*?)</a>', resp.text, re.I | re.S):
            attrs = match.group(1)
            if "result__a" not in attrs:
                continue
            href_match = re.search(r'href="([^"]+)"', attrs, re.I)
            if not href_match:
                continue
            href = html.unescape(href_match.group(1))
            title = _strip_html(match.group(2))
            if href.startswith("//duckduckgo.com/l/?"):
                parsed = urllib.parse.urlparse("https:" + href)
                params = urllib.parse.parse_qs(parsed.query)
                href = params.get("uddg", [href])[0]
            if not href.startswith(("http://", "https://")) or not title:
                continue
            results.append(f"- {title}\n  {href}")
            if len(results) >= max_results:
                break

        return "\n\n".join(results) if results else "ERROR: DuckDuckGo HTML returned no parseable results."
    except Exception as e:
        return f"ERROR: DuckDuckGo HTML search failed: {e}"


def _wait_for_duckduckgo_slot() -> None:
    global _last_duckduckgo_request_at
    with _duckduckgo_lock:
        wait_for = _DUCKDUCKGO_MIN_INTERVAL_SECONDS - (time.time() - _last_duckduckgo_request_at)
        if wait_for > 0:
            time.sleep(wait_for)
        _last_duckduckgo_request_at = time.time()


def _google_html_search(query: str, max_results: int = 5) -> str:
    """Fetch and parse Google's lightweight HTML results without rapid repeat requests."""
    global _last_google_request_at
    try:
        with _google_lock:
            wait_for = _GOOGLE_MIN_INTERVAL_SECONDS - (time.time() - _last_google_request_at)
            if wait_for > 0:
                time.sleep(wait_for)
            _last_google_request_at = time.time()

        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}&num={max(1, min(max_results, 10))}&hl=tr&gbv=1"
        resp = requests.get(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }, timeout=15)
        resp.raise_for_status()
        raw = resp.text

        lowered = raw.lower()
        block_markers = (
            "/sorry/", "unusual traffic", "recaptcha", "captcha",
            "detected unusual traffic", "consent.google.com",
            "/httpservice/retry/enablejs", "sg_rel",
        )
        if any(marker in lowered for marker in block_markers):
            return "ERROR: Google returned a bot/captcha/consent page."

        results = _parse_google_results(raw, max_results)
        if not results:
            return "ERROR: Google returned no parseable results."
        return "\n\n".join(results)
    except Exception as e:
        return f"ERROR: Google HTML search failed: {e}"


def _parse_google_results(raw: str, max_results: int) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    # Google commonly exposes result links as /url?q=<target>&...
    for match in re.finditer(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', raw, re.I | re.S):
        href = html.unescape(match.group(1))
        body = match.group(2)

        if href.startswith("/url?"):
            parsed = urllib.parse.urlparse(href)
            params = urllib.parse.parse_qs(parsed.query)
            target = params.get("q", [""])[0]
        else:
            target = href

        if not target.startswith(("http://", "https://")):
            continue
        if "google." in urllib.parse.urlparse(target).netloc:
            continue
        if target in seen:
            continue

        title = _strip_html(body)
        if not title or len(title) < 3:
            continue

        seen.add(target)
        results.append(f"- {title}\n  {target}")
        if len(results) >= max_results:
            break

    return results


def fetch_url(url: str, max_chars: int = 4000, js_render: bool = False) -> str:
    """Fetch URL content. Falls back to headless browser for JS-rendered pages."""
    if not is_safe_url(url):
        return "ERROR: URL is blocked by security policy (SSRF Guard)."

    # JS framework markers in raw HTML
    _JS_MARKERS = (
        "__NEXT_DATA__", "__next", "_nuxt", "react-root", "app-root",
        "ng-version", "data-reactroot", "__NUXT__", "window.__INITIAL_STATE__",
    )

    if js_render:
        rendered = _fetch_with_browser(url, max_chars)
        if rendered and not rendered.startswith("(browser render failed"):
            return rendered
        # Fall through to static fetch if browser failed

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8", errors="replace")

        if "html" in content_type:
            text = _strip_html(raw)
            # Auto-detect JS-rendered page: framework marker present OR very little text vs HTML size
            is_js_heavy = any(m in raw for m in _JS_MARKERS)
            content_ratio = len(text.strip()) / max(len(raw), 1)
            if not js_render and (is_js_heavy or (content_ratio < 0.05 and len(raw) > 5000)):
                rendered = _fetch_with_browser(url, max_chars)
                if rendered and not rendered.startswith("(browser render failed"):
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
