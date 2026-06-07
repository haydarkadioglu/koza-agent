"""Base LLM provider interface."""
import json
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
