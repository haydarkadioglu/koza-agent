"""Shared HTTP helpers and config state for social skill."""
import urllib.request
import urllib.parse
import json

_social_cfg: dict = {}


def set_cfg(cfg: dict):
    global _social_cfg
    _social_cfg = cfg.get("social", {})


def get_cfg() -> dict:
    return _social_cfg


def _get(url: str, headers: dict = None, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _post_json(url: str, data: dict, headers: dict = None) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "KozaAgent/1.0", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _post_form(url: str, fields: dict, headers: dict = None) -> dict:
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "KozaAgent/1.0", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
