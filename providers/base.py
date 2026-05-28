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
