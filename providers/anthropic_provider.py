"""Anthropic (Claude) provider."""
import json
from typing import Generator
import anthropic
from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._client = anthropic.Anthropic(api_key=cfg.get("api_key", ""))
        self._model = cfg.get("model", "claude-3-5-sonnet-20241022")

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def supports_thinking(self) -> bool:
        # claude-3-7+ has extended thinking
        return "claude-3-7" in self._model or "claude-4" in self._model

    def chat(self, messages, tools=None, stream=False):
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

    def stream_chat(self, messages, tools=None, cancel_event=None) -> Generator[str, None, None]:
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
                if cancel_event and cancel_event.is_set():
                    break

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
