"""OpenAI provider (API key + Azure OAuth compatible)."""
from typing import Generator
import json
from openai import OpenAI
from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._cfg = cfg
        api_key = self._get_api_key(cfg) or "sk-placeholder"
        self._client = OpenAI(
            api_key=api_key,
            base_url=cfg.get("base_url", "https://api.openai.com/v1"),
        )
        self._model = cfg.get("model", "gpt-4o")

    def _update_client_key(self) -> None:
        new_key = self._get_api_key(self._cfg)
        if new_key and hasattr(self, "_client"):
            self._client.api_key = new_key

    @property
    def name(self) -> str:
        return "openai"

    @property
    def supports_thinking(self) -> bool:
        # o1, o3, o4 series have reasoning/thinking
        return bool(__import__("re").match(r"o[134]", self._model))

    @property
    def supports_vision(self) -> bool:
        # gpt-4o, gpt-4-turbo, and o-series support vision
        m = self._model.lower()
        return "gpt-4o" in m or "gpt-4-turbo" in m or "gpt-4v" in m or m.startswith("o")

    def chat(self, messages, tools=None, stream=False):
        kwargs = {"model": self._model, "messages": self._normalize_openai_messages(messages)}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.function.name, "arguments": json.loads(tc.function.arguments)}
                for tc in msg.tool_calls
            ]
        return {"content": msg.content, "tool_calls": tool_calls}

    def stream_chat(self, messages, tools=None, cancel_event=None) -> Generator[str | dict, None, None]:
        kwargs = {"model": self._model, "messages": self._normalize_openai_messages(messages), "stream": True}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)

        tool_chunks: dict[int, dict] = {}
        _finish_reason = None

        for chunk in resp:
            if cancel_event and cancel_event.is_set():
                resp.close()
                return

            choice = chunk.choices[0]
            delta = choice.delta
            if getattr(choice, "finish_reason", None):
                _finish_reason = choice.finish_reason

            # Buffer tool call deltas
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_chunks:
                        tool_chunks[idx] = {"id": None, "name": "", "args": ""}
                    if getattr(tc, "id", None):
                        tool_chunks[idx]["id"] = tc.id
                    if tc.function:
                        if getattr(tc.function, "name", None):
                            tool_chunks[idx]["name"] += tc.function.name
                        if getattr(tc.function, "arguments", None):
                            tool_chunks[idx]["args"] += tc.function.arguments

            # Yield text content immediately
            if delta.content:
                yield delta.content

        if _finish_reason:
            yield {"__finish_reason__": _finish_reason}

        # Yield buffered tool call chunks after text stream completes
        for idx, stc in sorted(tool_chunks.items()):
            if stc["name"]:
                try:
                    args_parsed = json.loads(stc["args"] or "{}")
                except Exception:
                    args_parsed = {}
                yield {
                    "__tool_chunk__": True,
                    "index": idx,
                    "id": stc["id"] or stc["name"],
                    "name": stc["name"],
                    "args_chunk": json.dumps(args_parsed),
                }

    def list_models(self) -> list[str]:
        try:
            return [m.id for m in self._client.models.list()]
        except Exception:
            return ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]
