"""Base LLM provider interface."""
import json
import re
import threading
from abc import ABC, abstractmethod
from typing import Any, Generator


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict:
        """Send messages and return assistant response dict.
        
        Returns:
            {
                "content": str | None,
                "tool_calls": [ {"id": str, "name": str, "arguments": dict} ] | None
            }
        """

    @abstractmethod
    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Generator[str | dict, None, None]:
        """Stream response tokens as a generator.

        Args:
            messages: The conversation messages to send.
            tools: Optional tool definitions for function calling.
            cancel_event: When set, the provider should stop iterating over
                the response stream and return early.

        Yields:
            str — text token (immediate, unbuffered). Each text chunk from the
                API is yielded as a plain string as soon as it is received.
            dict — tool chunk with the structure:
                {"__tool_chunk__": True, "index": int, "id": str,
                 "name": str, "args_chunk": str}
                Tool call data is buffered during the text stream and yielded
                as ``__tool_chunk__`` dictionaries after text streaming completes.

        Cancellation:
            Check ``cancel_event.is_set()`` on each iteration of the response
            stream. When set, close the underlying API connection and return
            immediately. The provider MUST stop yielding within 500ms of
            ``cancel_event`` being set.

        Errors:
            Propagate connection errors as exceptions (do not swallow).
            The streaming engine is responsible for catching and converting
            them into error events.
        """

    def _fallback_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Generator[str | dict, None, None]:
        """Fallback streaming: call self.chat() and yield the result.

        Use this in stream_chat() implementations when the provider (or a
        specific mode) does not support native streaming. The method:
          1. Calls self.chat(messages, tools) to get the complete response.
          2. Yields any tool calls as __tool_chunk__ dicts first.
          3. Yields the complete text response as a single string.

        The CLI/StreamRenderer handles this identically to streamed output:
        the response box opens on the first text token, the full text appears,
        and the box closes — indistinguishable from native streaming to the user.

        Cancellation is checked between each yield to allow early termination.
        """
        result = self.chat(messages, tools=tools)

        # Yield tool chunks first so the streaming engine's _tool_buf is populated
        for idx, tc in enumerate(result.get("tool_calls") or []):
            if cancel_event and cancel_event.is_set():
                return
            yield {
                "__tool_chunk__": True,
                "index": idx,
                "id": tc.get("id") or tc.get("name"),
                "name": tc.get("name"),
                "args_chunk": json.dumps(tc.get("arguments", {})),
            }

        # Yield complete text response as a single string
        if result.get("content"):
            if cancel_event and cancel_event.is_set():
                return
            yield result["content"]

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return available model names."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'openai')."""

    @property
    def model(self) -> str:
        """The active model name (e.g. 'gpt-4o')."""
        return getattr(self, "_model", "")

    def _get_api_key(self, cfg: dict, key_name: str = "api_key") -> str:
        if not hasattr(self, "_api_keys"):
            raw_key = cfg.get(key_name) or cfg.get("token") or ""
            if isinstance(raw_key, list):
                self._api_keys = [str(k).strip() for k in raw_key if k]
            elif isinstance(raw_key, str) and "," in raw_key:
                self._api_keys = [str(k).strip() for k in raw_key.split(",") if k]
            elif raw_key:
                self._api_keys = [str(raw_key).strip()]
            else:
                self._api_keys = []
            self._api_key_index = 0
        if not self._api_keys:
            return ""
        return self._api_keys[self._api_key_index]

    def rotate_key(self) -> bool:
        if not hasattr(self, "_api_keys") or len(self._api_keys) <= 1:
            return False
        self._api_key_index = (self._api_key_index + 1) % len(self._api_keys)
        self._update_client_key()
        return True

    def _update_client_key(self) -> None:
        pass

    @property
    def supports_thinking(self) -> bool:
        """True for models with native reasoning/thinking tokens (e.g. o1, Claude extended thinking, DeepSeek-R1)."""
        return False

    @property
    def supports_vision(self) -> bool:
        """True if this provider/model can process image content."""
        return False

    @staticmethod
    def _extract_text_content(content) -> str:
        """Flatten list-format vision content to plain text (for non-vision providers)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item["text"])
            return " ".join(parts)
        return str(content) if content else ""

    @staticmethod
    def _flatten_messages_for_text(messages: list[dict]) -> list[dict]:
        """Return messages with any list-content (vision) flattened to plain text.

        Use in non-vision providers so they still work when history contains
        messages that were originally sent with images.
        """
        result = []
        for m in messages:
            if isinstance(m.get("content"), list):
                m = {**m, "content": LLMProvider._extract_text_content(m["content"])}
            result.append(m)
        return result

    @staticmethod
    def _normalize_openai_messages(messages: list[dict]) -> list[dict]:
        """Convert Koza's internal tool-call shape to OpenAI chat format.

        Koza stores tool calls internally as {"id", "name", "arguments"}.
        OpenAI-compatible APIs require each assistant tool call to include
        {"type": "function", "function": {"name", "arguments"}}.
        """
        normalized: list[dict] = []
        for msg in messages:
            m = dict(msg)
            if m.get("role") == "assistant" and m.get("tool_calls"):
                api_tool_calls = []
                for tc in m.get("tool_calls") or []:
                    if not isinstance(tc, dict):
                        continue
                    if "function" in tc:
                        api_tool_calls.append(
                            {"type": "function", **tc} if "type" not in tc else tc
                        )
                        continue

                    args = tc.get("arguments", {})
                    api_tool_calls.append({
                        "id": tc.get("id") or tc.get("name") or "call",
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": (
                                json.dumps(args) if isinstance(args, dict) else str(args)
                            ),
                        },
                    })
                m["tool_calls"] = api_tool_calls
                m["content"] = m.get("content")
            elif m.get("role") == "tool":
                m["content"] = str(m.get("content", ""))
            normalized.append(m)
        return normalized


_SURROGATE_RE = re.compile(r'[\ud800-\udfff]')


def sanitize_messages_surrogates(messages: list[dict]) -> bool:
    """Sanitize surrogate characters from all string content in a messages list.

    Walks message dicts in-place. Returns True if any surrogates were found
    and replaced, False otherwise.
    """
    found = False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and _SURROGATE_RE.search(content):
            msg["content"] = _SURROGATE_RE.sub('\ufffd', content)
            found = True
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str) and _SURROGATE_RE.search(text):
                        part["text"] = _SURROGATE_RE.sub('\ufffd', text)
                        found = True
        name = msg.get("name")
        if isinstance(name, str) and _SURROGATE_RE.search(name):
            msg["name"] = _SURROGATE_RE.sub('\ufffd', name)
            found = True
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                tc_id = tc.get("id")
                if isinstance(tc_id, str) and _SURROGATE_RE.search(tc_id):
                    tc["id"] = _SURROGATE_RE.sub('\ufffd', tc_id)
                    found = True
                fn = tc.get("function")
                if isinstance(fn, dict):
                    fn_name = fn.get("name")
                    if isinstance(fn_name, str) and _SURROGATE_RE.search(fn_name):
                        fn["name"] = _SURROGATE_RE.sub('\ufffd', fn_name)
                        found = True
                    fn_args = fn.get("arguments")
                    if isinstance(fn_args, str) and _SURROGATE_RE.search(fn_args):
                        fn["arguments"] = _SURROGATE_RE.sub('\ufffd', fn_args)
                        found = True
        # Walk any additional string / nested fields
        for key, value in msg.items():
            if key in {"content", "name", "tool_calls", "role"}:
                continue
            if isinstance(value, str):
                if _SURROGATE_RE.search(value):
                    msg[key] = _SURROGATE_RE.sub('\ufffd', value)
                    found = True
            elif isinstance(value, (dict, list)):
                if _sanitize_structure_surrogates(value):
                    found = True
    return found


def _sanitize_structure_surrogates(payload: Any) -> bool:
    """Replace surrogate code points in nested dict/list payloads in-place."""
    found = False

    def _walk(node):
        nonlocal found
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str):
                    if _SURROGATE_RE.search(value):
                        node[key] = _SURROGATE_RE.sub('\ufffd', value)
                        found = True
                elif isinstance(value, (dict, list)):
                    _walk(value)
        elif isinstance(node, list):
            for idx, value in enumerate(node):
                if isinstance(value, str):
                    if _SURROGATE_RE.search(value):
                        node[idx] = _SURROGATE_RE.sub('\ufffd', value)
                        found = True
                elif isinstance(value, (dict, list)):
                    _walk(value)

    _walk(payload)
    return found


class SanitizingProviderWrapper(LLMProvider):
    """Wraps an LLMProvider to sanitize surrogate characters in messages before API calls."""
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    def chat(self, messages, tools=None, stream=False):
        sanitize_messages_surrogates(messages)
        return self._provider.chat(messages, tools=tools, stream=stream)

    def stream_chat(self, messages, tools=None, cancel_event=None):
        sanitize_messages_surrogates(messages)
        return self._provider.stream_chat(messages, tools=tools, cancel_event=cancel_event)

    def list_models(self) -> list[str]:
        return self._provider.list_models()

    @property
    def name(self) -> str:
        return self._provider.name

    @property
    def model(self) -> str:
        return self._provider.model

    def rotate_key(self) -> bool:
        return self._provider.rotate_key()

    @property
    def supports_thinking(self) -> bool:
        return self._provider.supports_thinking

    @property
    def supports_vision(self) -> bool:
        return self._provider.supports_vision

    def __getattr__(self, name):
        return getattr(self._provider, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_provider":
            super().__setattr__(name, value)
        elif hasattr(self, "_provider") and hasattr(self._provider, name):
            setattr(self._provider, name, value)
        else:
            super().__setattr__(name, value)
