"""OpenRouter provider (unified API gateway for 200+ models)."""
from openai import OpenAI
from typing import Generator
import json
from .base import LLMProvider


class OpenRouterProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._client = OpenAI(
            api_key=cfg.get("api_key", ""),
            base_url=cfg.get("base_url", "https://openrouter.ai/api/v1"),
            default_headers={
                "HTTP-Referer": "https://github.com/haydarkadioglu/koza-agent",
                "X-Title": "Koza Agent",
            },
        )
        self._model = cfg.get("model", "openai/gpt-4o")

    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def supports_thinking(self) -> bool:
        m = self._model.lower()
        return any(k in m for k in ("o1", "o3", "o4", "deepseek-r1", "reasoner"))

    def chat(self, messages, tools=None, stream=False):
        kwargs = {"model": self._model, "messages": messages}
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

    def stream_chat(self, messages, tools=None, cancel_event=None) -> Generator[str, None, None]:
        kwargs = {"model": self._model, "messages": messages, "stream": True}
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
                "openai/gpt-4o",
                "openai/gpt-4o-mini",
                "anthropic/claude-3.5-sonnet",
                "google/gemini-2.0-flash-exp",
                "deepseek/deepseek-chat",
                "meta-llama/llama-3.3-70b-instruct",
                "mistralai/mixtral-8x7b-instruct",
            ]
