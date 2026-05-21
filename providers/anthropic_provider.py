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

    def stream_chat(self, messages, tools=None) -> Generator[str, None, None]:
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        msgs = [m for m in messages if m["role"] != "system"]
        kwargs = {"model": self._model, "max_tokens": 4096, "messages": msgs}
        if system:
            kwargs["system"] = system
        with self._client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text

    def list_models(self) -> list[str]:
        return [
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-3-5-sonnet-20241022",
            "claude-3-haiku-20240307",
        ]
