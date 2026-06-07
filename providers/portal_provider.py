"""Nous Portal provider (unified subscription proxy gateway)."""
from openai import OpenAI
from typing import Generator
import json
from .base import LLMProvider


class NousPortalProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._cfg = cfg
        api_key = self._get_api_key(cfg) or "portal-placeholder"
        self._client = OpenAI(
            api_key=api_key,
            base_url=cfg.get("base_url", "https://api.nous.portal/v1"),
            default_headers={
                "X-Client-Name": "Koza Agent",
            },
        )
        self._model = cfg.get("model", "nous/hermes-3-llama-3.1-405b")

    def _update_client_key(self) -> None:
        new_key = self._get_api_key(self._cfg)
        if new_key and hasattr(self, "_client"):
            self._client.api_key = new_key

    @property
    def name(self) -> str:
        return "portal"

    @property
    def supports_thinking(self) -> bool:
        m = self._model.lower()
        return "r1" in m or "reasoner" in m or "thinking" in m

    @property
    def supports_vision(self) -> bool:
        m = self._model.lower()
        return "vision" in m or "gpt-4" in m or "claude-3" in m or "gemini" in m

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
                {"id": tc.id, "name": tc.function.name,
                 "arguments": json.loads(tc.function.arguments)}
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

        for chunk in resp:
            if cancel_event and cancel_event.is_set():
                resp.close()
                return

            choice = chunk.choices[0]
            delta = choice.delta

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
                continue

            if delta.content:
                yield delta.content

        # Yield tool call chunks after text
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
            models = self._client.models.list()
            return [m.id for m in models.data[:50]]
        except Exception:
            return [
                "nous/hermes-3-llama-3.1-405b",
                "nous/hermes-3-llama-3.1-70b",
                "nous/hermes-3-llama-3.1-8b",
                "openai/gpt-4o",
                "anthropic/claude-3-5-sonnet",
                "deepseek/deepseek-r1",
            ]
