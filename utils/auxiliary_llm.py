"""Koza Agent — auxiliary LLM calls (summarisation and other internal work).

A deliberately tiny OpenAI-compatible client for model calls that are *not*
part of the user-facing conversation: context summarisation, title
generation, and anything else that needs a cheap model without touching the
main stream.

Koza owns a single provider configuration, so there is no separate auxiliary
provider stack here.  The caller passes the runtime it wants used (normally
the main one) and this module POSTs a plain ``/chat/completions`` request to
it.  Credentials are read from the runtime dict, which koza fills from
``~/.Koza/.env`` via ``config.py`` — never hardcoded in this file.

No new dependency: ``requests`` is already a koza dependency.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Providers that serve a local model and therefore need no API key.
LOCAL_PROVIDERS = {"ollama", "lm_studio"}

DEFAULT_TIMEOUT_SECONDS = 60

# Substrings that mean "the socket died mid-response" rather than "the
# request was rejected".  Callers treat these as transient and retry or fall
# back instead of entering a long cooldown.
_CONNECTION_ERROR_MARKERS = (
    "incomplete chunked read",
    "peer closed connection",
    "response ended prematurely",
    "unexpected eof",
    "connection reset",
    "connection aborted",
    "connection refused",
    "timed out",
    "timeout",
)


class AuxLLMError(Exception):
    """An auxiliary LLM call failed with a usable HTTP status code."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class _Message:
    def __init__(self, content: Any = "", role: str = "assistant"):
        self.content = content
        self.role = role

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<_Message role={self.role!r} content={str(self.content)[:40]!r}>"


class _Choice:
    def __init__(self, message: _Message, finish_reason: str = "stop", index: int = 0):
        self.message = message
        self.finish_reason = finish_reason
        self.index = index


class _Response:
    """Minimal stand-in for an OpenAI SDK chat-completion response.

    Only the attributes koza's callers use are exposed (``choices[0].message
    .content``, ``usage``, ``model``, ``id``), so internal callers do not have
    to depend on the SDK.
    """

    def __init__(self, choices: list[_Choice], usage: dict[str, Any] | None = None,
                 model: str = "", response_id: str = ""):
        self.choices = choices
        self.usage = usage or {}
        self.model = model
        self.id = response_id


def is_connection_error(exc: BaseException) -> bool:
    """True when ``exc`` looks like a dropped/timed-out connection."""
    if isinstance(exc, (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout)):
        return True
    if isinstance(exc, requests.exceptions.RequestException):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _CONNECTION_ERROR_MARKERS)


def _config_section(name: str) -> dict[str, Any]:
    """Read one section of ``~/.Koza/config.yaml``; {} when unavailable."""
    try:
        from config import load_config

        section = load_config().get(name)
        return section if isinstance(section, dict) else {}
    except Exception as exc:  # fail open — defaults are always usable
        logger.debug("Could not read config section %r: %s", name, exc)
        return {}


def _provider_base_url(provider: str) -> str:
    try:
        from config import load_config

        providers = load_config().get("providers") or {}
        entry = providers.get(provider) or {}
        return str(entry.get("base_url") or "")
    except Exception:
        return ""


def resolve_runtime(main_runtime: dict[str, Any] | None = None,
                    model: str = "") -> dict[str, str]:
    """Resolve the endpoint an auxiliary call should use.

    ``main_runtime`` wins; anything it leaves empty is filled from koza's
    configured provider, then from the model named in
    ``context_compression.summary_model`` when that is the only thing set.
    Raises ``RuntimeError`` when there is nothing to call.
    """
    runtime = dict(main_runtime or {})
    provider = str(runtime.get("provider") or "")
    base_url = str(runtime.get("base_url") or "")
    api_key = str(runtime.get("api_key") or "")
    resolved_model = str(model or runtime.get("model") or "")

    if not base_url and provider:
        base_url = _provider_base_url(provider)

    if not resolved_model:
        # Fall back to koza's configured model so a call that only names a
        # provider still works.
        try:
            from config import load_config

            resolved_model = str(load_config().get("model") or "")
        except Exception:
            resolved_model = ""

    if not base_url:
        raise RuntimeError(
            "No auxiliary LLM provider configured: pass a runtime with a "
            "base_url, or set a provider in ~/.Koza/config.yaml."
        )
    if not resolved_model:
        raise RuntimeError(
            "No auxiliary LLM model configured: pass a model, or set one in "
            "~/.Koza/config.yaml."
        )
    if not api_key and provider not in LOCAL_PROVIDERS and not base_url.startswith(
        ("http://localhost", "http://127.0.0.1")
    ):
        raise RuntimeError(
            f"No API key available for auxiliary LLM provider {provider or base_url!r}."
        )

    return {"provider": provider, "base_url": base_url.rstrip("/"),
            "api_key": api_key, "model": resolved_model}


def call_llm(task: str = "", main_runtime: dict[str, Any] | None = None,
             messages: list[dict[str, Any]] | None = None,
             max_tokens: int | None = None, model: str = "",
             timeout: float | None = None) -> _Response:
    """Run one non-streaming chat completion and return the response.

    ``task`` is a label used in logs (e.g. ``"compression"``).  Errors from
    the transport propagate as ``requests`` exceptions so callers can classify
    them with :func:`is_connection_error`; HTTP error responses raise
    :class:`AuxLLMError` carrying ``status_code``.
    """
    section = _config_section("context_compression")
    if timeout is None:
        try:
            timeout = float(section.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_SECONDS

    runtime = resolve_runtime(main_runtime, model=model or str(section.get("summary_model") or ""))

    payload: dict[str, Any] = {
        "model": runtime["model"],
        "messages": messages or [],
        "stream": False,
    }
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)

    headers = {"Content-Type": "application/json"}
    if runtime["api_key"]:
        headers["Authorization"] = f"Bearer {runtime['api_key']}"

    url = f"{runtime['base_url']}/chat/completions"
    label = task or "auxiliary"
    logger.debug("Auxiliary LLM call (%s): model=%s url=%s", label, runtime["model"], url)

    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        body = (response.text or "")[:500]
        raise AuxLLMError(
            f"{label} request rejected with HTTP {response.status_code}: {body}",
            status_code=response.status_code,
        )

    data = response.json()
    return _parse_response(data, fallback_model=runtime["model"])


def _parse_response(data: Any, fallback_model: str = "") -> _Response:
    """Convert a raw chat-completion body into a :class:`_Response`."""
    if not isinstance(data, dict):
        raise AuxLLMError(f"Malformed auxiliary LLM response: {str(data)[:200]}")

    choices: list[_Choice] = []
    for entry in data.get("choices") or []:
        if not isinstance(entry, dict):
            continue
        message = entry.get("message") or {}
        content = message.get("content", "") if isinstance(message, dict) else message
        choices.append(_Choice(
            _Message(content=content, role=str(message.get("role", "assistant"))
                     if isinstance(message, dict) else "assistant"),
            finish_reason=str(entry.get("finish_reason") or "stop"),
            index=int(entry.get("index") or len(choices)),
        ))

    if not choices:
        raise AuxLLMError(
            "Auxiliary LLM response contained no choices: "
            f"{json.dumps(data)[:200]}"
        )

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return _Response(choices, usage=usage,
                     model=str(data.get("model") or fallback_model),
                     response_id=str(data.get("id") or ""))
