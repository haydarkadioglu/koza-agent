"""Google Gemini provider (API key + ADC OAuth)."""
import json
from typing import Generator
from google import genai
from google.genai import types
from .base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self, cfg: dict):
        api_key = cfg.get("api_key")
        if api_key:
            self._client = genai.Client(api_key=api_key)
        else:
            # Application Default Credentials (OAuth)
            import google.auth
            credentials, _ = google.auth.default()
            self._client = genai.Client(credentials=credentials)
        self._model = cfg.get("model", "gemini-2.0-flash-exp")

    @property
    def name(self) -> str:
        return "gemini"

    def _convert_tools(self, tools):
        if not tools:
            return None
        func_decls = []
        for t in tools:
            fn = t["function"]
            func_decls.append(
                types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters", {}),
                )
            )
        return [types.Tool(function_declarations=func_decls)]

    def chat(self, messages, tools=None, stream=False):
        contents = []
        system_text = None
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            elif m["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
            elif m["role"] == "assistant":
                contents.append(types.Content(role="model", parts=[types.Part(text=m["content"] or "")]))

        kwargs = {"contents": contents}
        if system_text:
            kwargs["system_instruction"] = system_text
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        resp = self._client.models.generate_content(model=self._model, **kwargs)
        tool_calls = None
        content_text = None
        for part in resp.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                content_text = part.text
            elif hasattr(part, "function_call") and part.function_call:
                tool_calls = tool_calls or []
                tool_calls.append({
                    "id": part.function_call.name,
                    "name": part.function_call.name,
                    "arguments": dict(part.function_call.args),
                })
        return {"content": content_text, "tool_calls": tool_calls}

    def stream_chat(self, messages, tools=None) -> Generator[str, None, None]:
        contents = [
            types.Content(role="user" if m["role"] == "user" else "model",
                          parts=[types.Part(text=m["content"] or "")])
            for m in messages if m["role"] != "system"
        ]
        for chunk in self._client.models.generate_content_stream(model=self._model, contents=contents):
            if chunk.text:
                yield chunk.text

    def list_models(self) -> list[str]:
        try:
            return [m.name for m in self._client.models.list()]
        except Exception:
            return ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"]
