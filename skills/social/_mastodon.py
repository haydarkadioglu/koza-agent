"""Mastodon post."""
from ._base import _post_form, get_cfg


def mastodon_post(content: str, instance_url: str = "", token: str = "", visibility: str = "public") -> str:
    try:
        cfg = get_cfg()
        base = (instance_url or cfg.get("mastodon_instance", "https://mastodon.social")).rstrip("/")
        tok = token or cfg.get("mastodon_token", "")
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
