"""Kimi (Moonshot AI) provider — OpenAI-compatible API."""
from openai import OpenAI
from typing import Generator
from .base import LLMProvider


class KimiProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._client = OpenAI(
            api_key=cfg.get("api_key", ""),
            base_url=cfg.get("base_url", "https://api.moonshot.cn/v1"),
        )
        self._model = cfg.get("model", "moonshot-v1-8k")

    @property
    def name(self) -> str:
        return "kimi"

    @property
    def supports_thinking(self) -> bool:
        m = self._model.lower()
        return "k1" in m or "thinking" in m

    def chat(self, messages, tools=None, stream=False):
        import json
        kwargs = {"model": self._model, "messages": messages}
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

    def stream_chat(self, messages, tools=None) -> Generator[str, None, None]:
        import json
        kwargs = {"model": self._model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self._client.chat.completions.create(**kwargs)
        tool_chunks: dict[int, dict] = {}
        text_buf = ""
        for chunk in resp:
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
            text_buf += delta.content or ""
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
        if text_buf:
            if not tool_chunks:
                for i in range(0, len(text_buf), 8):
                    yield text_buf[i:i+8]
            else:
                yield text_buf

    def list_models(self) -> list[str]:
        try:
            return [m.id for m in self._client.models.list()]
        except Exception:
            return ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k",
                    "kimi-k2-0711-preview", "kimi-latest"]
