"""DeepSeek provider (OpenAI-compatible API)."""
from openai import OpenAI
from typing import Generator
from .base import LLMProvider


class DeepSeekProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._client = OpenAI(
            api_key=cfg.get("api_key", ""),
            base_url=cfg.get("base_url", "https://api.deepseek.com/v1"),
        )
        self._model = cfg.get("model", "deepseek-chat")

    @property
    def name(self) -> str:
        return "deepseek"

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
        resp = self._client.chat.completions.create(
            model=self._model, messages=messages, stream=True
        )
        for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def list_models(self) -> list[str]:
        try:
            return [m.id for m in self._client.models.list()]
        except Exception:
            return ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"]
