"""Anthropic (Claude) provider."""
import json
import threading
from typing import Generator
import anthropic
from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._cfg = cfg
        api_key = self._get_api_key(cfg) or ""
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = cfg.get("model", "claude-3-5-sonnet-20241022")

    def _update_client_key(self) -> None:
        new_key = self._get_api_key(self._cfg)
        if new_key and hasattr(self, "_client"):
            self._client.api_key = new_key

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def supports_thinking(self) -> bool:
        # claude-3-7+ has extended thinking
        return "claude-3-7" in self._model or "claude-4" in self._model

    @property
    def supports_vision(self) -> bool:
        # claude-3 and later all support vision
        return "claude-3" in self._model or "claude-4" in self._model

    @staticmethod
    def _adapt_vision_messages(messages: list[dict]) -> list[dict]:
        """Convert OpenAI-format image_url content blocks to Anthropic's image source format."""
        adapted = []
        for m in messages:
            content = m.get("content")
            if isinstance(content, list):
                new_content = []
                for item in content:
                    if item.get("type") == "text":
                        new_content.append({"type": "text", "text": item["text"]})
                    elif item.get("type") == "image_url":
                        url = item["image_url"]["url"]
                        if url.startswith("data:"):
                            header, data = url.split(",", 1)
                            media_type = header.split(":")[1].split(";")[0]
                            new_content.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": data,
                                },
                            })
                adapted.append({**m, "content": new_content})
            else:
                adapted.append(m)
        return adapted

    def chat(self, messages, tools=None, stream=False):
        messages = self._adapt_vision_messages(messages)
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        msgs = [m for m in messages if m["role"] != "system"]
        kwargs = {"model": self._model, "max_tokens": 4096, "messages": msgs}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in tools
            ]
        resp = self._client.messages.create(**kwargs)
        content_text = None
        tool_calls = None
        for block in resp.content:
            if block.type == "text":
                content_text = block.text
            elif block.type == "tool_use":
                tool_calls = tool_calls or []
                tool_calls.append({"id": block.id, "name": block.name, "arguments": block.input})
        return {"content": content_text, "tool_calls": tool_calls}

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Generator[str | dict, None, None]:
        """Stream response tokens from Anthropic's API.

        Yields:
            str — text token (immediate, unbuffered)
            dict — tool chunk: {"__tool_chunk__": True, "index": int,
                    "id": str, "name": str, "args_chunk": str}

        Cancellation:
            Checks cancel_event.is_set() on each event. When set, closes
            the stream and returns immediately.

        Errors:
            Connection errors propagate as exceptions (not caught).
        """
        messages = self._adapt_vision_messages(messages)
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        msgs = [m for m in messages if m["role"] != "system"]
        kwargs = {"model": self._model, "max_tokens": 4096, "messages": msgs}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in tools
            ]

        # Buffer tool_use blocks; yield text incrementally
        tool_blocks: dict[int, dict] = {}
        current_tool_index: int = -1

        with self._client.messages.stream(**kwargs) as stream:
            for event in stream:
                # Check cancellation on each event iteration
                if cancel_event and cancel_event.is_set():
                    stream.close()
                    return

                # content_block_start: begins a new content block (text or tool_use)
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool_index += 1
                        tool_blocks[current_tool_index] = {
                            "id": block.id,
                            "name": block.name,
                            "input_json": "",
                        }

                # content_block_delta: incremental data for the current block
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield delta.text
                    elif delta.type == "input_json_delta":
                        # Accumulate JSON fragments for tool_use input
                        if current_tool_index in tool_blocks:
                            tool_blocks[current_tool_index]["input_json"] += delta.partial_json

        # Yield buffered tool_use blocks as __tool_chunk__ dicts after stream ends
        for idx, tb in sorted(tool_blocks.items()):
            if tb["name"]:
                try:
                    args_parsed = json.loads(tb["input_json"] or "{}")
                except Exception:
                    args_parsed = {}
                yield {
                    "__tool_chunk__": True,
                    "index": idx,
                    "id": tb["id"],
                    "name": tb["name"],
                    "args_chunk": json.dumps(args_parsed),
                }

    def list_models(self) -> list[str]:
        return [
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-3-5-sonnet-20241022",
            "claude-3-haiku-20240307",
        ]
