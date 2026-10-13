"""Koza Agent — shared utilities.

Small, dependency-free helpers that more than one subsystem needs.  Module
specific helpers belong in the module that owns them; only genuinely
cross-cutting symbols live here.
"""

from urllib.parse import urlparse

__all__ = ["base_url_host_matches", "base_url_hostname"]


def base_url_hostname(base_url: str) -> str:
    """Return the bare, lower-cased hostname of a base URL.

    Accepts URLs with or without a scheme (``api.openai.com/v1``), and strips
    userinfo, port and any trailing dot so callers can match on the host
    alone.  Returns an empty string when no host can be parsed.
    """
    if not base_url:
        return ""
    raw = str(base_url).strip()
    if "//" not in raw:
        # urlparse treats "api.openai.com/v1" as a path, so give it a scheme.
        raw = "//" + raw
    try:
        host = urlparse(raw).hostname or ""
    except ValueError:
        return ""
    return host.strip().rstrip(".").lower()


def base_url_host_matches(base_url: str, domain: str) -> bool:
    """True when the base URL's host is ``domain`` or one of its subdomains."""
    host = base_url_hostname(base_url)
    if not host or not domain:
        return False
    domain = str(domain).strip().lower().lstrip(".")
    return host == domain or host.endswith("." + domain)
