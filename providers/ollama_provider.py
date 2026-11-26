"""Ollama provider (local REST API)."""
import json
import logging
from collections.abc import Generator

import requests

from utils.model_metadata import is_local_endpoint, query_ollama_num_ctx

from .base import LLMProvider

_log = logging.getLogger(__name__)

# Marks "num_ctx not resolved yet" (None is a valid, cached outcome).
_UNSET = object()


def _positive_int(value) -> int | None:
    """Return value as a positive int, or None. Accepts int (not bool) or a digit-only str."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


class OllamaProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._cfg = dict(cfg or {})
        self._base_url = cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self._model = cfg.get("model", "llama3")
        self._api_key = cfg.get("api_key", "") or ""
        self._num_ctx_cache = _UNSET

    @property
    def name(self) -> str:
        return "ollama"

    def _resolve_num_ctx(self) -> int | None:
        """Context window to send as options.num_ctx; resolved once per instance.

        An explicit ``num_ctx`` wins. Otherwise a local server is probed once
        (the outcome, including None, is cached) and the detected value is
        capped by an explicit ``context_length``. Hosted endpoints are never
        probed. Never raises.
        """
        if self._num_ctx_cache is not _UNSET:
            return self._num_ctx_cache
        num_ctx = None
        try:
            num_ctx = _positive_int(self._cfg.get("num_ctx"))
            if num_ctx is None and is_local_endpoint(self._base_url):
                detected = _positive_int(
                    query_ollama_num_ctx(self._model, self._base_url, api_key=self._api_key)
                )
                context_length = _positive_int(self._cfg.get("context_length"))
                if detected is not None and context_length is not None:
                    detected = min(detected, context_length)
                num_ctx = detected
        except Exception as exc:  # noqa: BLE001 - a probe failure must never break a chat
            _log.debug("ollama num_ctx resolution failed: %s", exc)
            num_ctx = None
        self._num_ctx_cache = num_ctx
        if num_ctx is not None:
            _log.info("ollama num_ctx=%d for model %s", num_ctx, self._model)
        return num_ctx

    def _request_options(self) -> dict:
        """Per-request Ollama ``options``; empty when nothing is configured or detected."""
        options = {}
        num_ctx = self._resolve_num_ctx()
        if num_ctx:
            options["num_ctx"] = num_ctx
        num_predict = _positive_int(self._cfg.get("num_predict"))
        if num_predict:
            options["num_predict"] = num_predict
        return options

    def chat(self, messages, tools=None, stream=False):
        payload = {"model": self._model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        options = self._request_options()
        if options:
            payload["options"] = options
        resp = requests.post(f"{self._base_url}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {})
        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = [
                {
                    "id": f"ollama_{i}",
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                }
                for i, tc in enumerate(msg["tool_calls"])
            ]
        return {"content": msg.get("content"), "tool_calls": tool_calls}

    def stream_chat(self, messages, tools=None, cancel_event=None) -> Generator[str, None, None]:
        payload = {"model": self._model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools
        options = self._request_options()
        if options:
            payload["options"] = options
        with requests.post(f"{self._base_url}/api/chat", json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            buffered_tool_calls: list[dict] = []
            cancelled = False
            for line in resp.iter_lines():
                if cancel_event and cancel_event.is_set():
                    resp.close()
                    cancelled = True
                    break
                if line:
                    data = json.loads(line)
                    msg = data.get("message", {})
                    # Buffer any tool_calls found in this chunk
                    if msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            buffered_tool_calls.append({
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            })
                    # Yield text content incrementally
                    content = msg.get("content", "")
                    if content:
                        yield content

        # After stream ends, yield buffered tool calls as __tool_chunk__ dicts
        # (skip if cancelled — consistent with other providers)
        if not cancelled:
            for i, tc in enumerate(buffered_tool_calls):
                yield {
                    "__tool_chunk__": True,
                    "index": i,
                    "id": f"ollama_{i}",
                    "name": tc["name"],
                    "args_chunk": json.dumps(tc["arguments"]) if isinstance(tc["arguments"], dict) else tc["arguments"],
                }

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=5)
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:  # noqa: BLE001
            return ["llama3", "mistral", "codellama", "phi3"]
