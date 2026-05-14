"""Ollama provider (local REST API)."""
import json
import requests
from typing import Generator
from .base import LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(self, cfg: dict):
        self._base_url = cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self._model = cfg.get("model", "llama3")

    @property
    def name(self) -> str:
        return "ollama"

    def chat(self, messages, tools=None, stream=False):
        payload = {"model": self._model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        resp = requests.post(f"{self._base_url}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {})
        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = [
                {
                    "id": f"ollama_{i}",
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                }
                for i, tc in enumerate(msg["tool_calls"])
            ]
        return {"content": msg.get("content"), "tool_calls": tool_calls}

    def stream_chat(self, messages, tools=None) -> Generator[str, None, None]:
        payload = {"model": self._model, "messages": messages, "stream": True}
        with requests.post(f"{self._base_url}/api/chat", json=payload, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=5)
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return ["llama3", "mistral", "codellama", "phi3"]
