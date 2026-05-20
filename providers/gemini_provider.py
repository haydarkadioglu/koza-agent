"""Google Gemini provider.

Auth modes (set via config providers.gemini.auth):
  api_key  — default, uses providers.gemini.api_key
  cookie   — browser cookie auth (no API key, uses Gemini Pro web limits)
             requires providers.gemini.cookie_1psid (and optionally cookie_1psidts)
"""
import json
import asyncio
from typing import Generator
from .base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self, cfg: dict):
        auth_mode = cfg.get("auth", "api_key").lower()
        self._model = cfg.get("model", "gemini-3.5-flash")
        self._auth_mode = auth_mode

        if auth_mode == "cookie":
            self._cookie_1psid   = cfg.get("cookie_1psid", "")
            self._cookie_1psidts = cfg.get("cookie_1psidts", "")
            # If no cookie stored, try auto-extract from browser
            if not self._cookie_1psid:
                self._cookie_1psid, self._cookie_1psidts = self._auto_extract_cookies()
            if not self._cookie_1psid:
                raise ValueError(
                    "Cookie auth: no cookie found.\n"
                    "Run 'koza setup' to configure, or log in to gemini.google.com in your browser."
                )
            self._cookie_client = None  # lazy-init (async)
        else:
            from google import genai
            api_key = cfg.get("api_key")
            if api_key:
                self._client = genai.Client(api_key=api_key)
            else:
                import google.auth
                credentials, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/generative-language"]
                )
                self._client = genai.Client(credentials=credentials)

    @staticmethod
    def _auto_extract_cookies() -> tuple[str, str]:
        """Try to pull __Secure-1PSID from installed browsers."""
        try:
            import browser_cookie3
        except ImportError:
            return "", ""
        browsers = [
            browser_cookie3.chrome,
            browser_cookie3.edge,
            browser_cookie3.firefox,
            browser_cookie3.brave,
            browser_cookie3.opera,
        ]
        for loader in browsers:
            try:
                psid = psidts = ""
                for c in loader(domain_name=".google.com"):
                    if c.name == "__Secure-1PSID":
                        psid = c.value
                    elif c.name == "__Secure-1PSIDTS":
                        psidts = c.value
                if psid:
                    return psid, psidts
            except Exception:
                continue
        return "", ""

    # ── Cookie client (lazy async init) ──────────────────────────────────────

    def _get_cookie_client(self):
        if self._cookie_client is None:
            try:
                from gemini_webapi import GeminiClient
            except ImportError:
                raise ImportError(
                    "gemini-webapi not installed. Run:\n"
                    "  pip install gemini-webapi"
                )
            async def _init():
                client = GeminiClient(self._cookie_1psid, self._cookie_1psidts or None)
                await client.init(timeout=30, auto_close=False, close_delay=300)
                return client
            self._cookie_client = asyncio.run(_init())
        return self._cookie_client

    def _cookie_generate(self, prompt: str) -> str:
        client = self._get_cookie_client()
        async def _run():
            resp = await client.generate_content(prompt)
            return resp.text
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _run())
                return future.result(timeout=60)
        except RuntimeError:
            return asyncio.run(_run())

    @property
    def name(self) -> str:
        return "gemini"

    def _convert_tools(self, tools):
        if not tools:
            return None
        from google.genai import types
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
        if self._auth_mode == "cookie":
            # Cookie mode: flatten conversation to a single prompt
            prompt = "\n".join(
                f"{m['role'].upper()}: {m['content']}"
                for m in messages if m.get("content")
            )
            text = self._cookie_generate(prompt)
            return {"content": text, "tool_calls": None}

        from google.genai import types
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
        if self._auth_mode == "cookie":
            # Cookie mode doesn't support streaming — yield full response
            result = self.chat(messages)
            if result.get("content"):
                yield result["content"]
            return

        from google.genai import types
        contents = [
            types.Content(role="user" if m["role"] == "user" else "model",
                          parts=[types.Part(text=m["content"] or "")])
            for m in messages if m["role"] != "system"
        ]
        for chunk in self._client.models.generate_content_stream(model=self._model, contents=contents):
            if chunk.text:
                yield chunk.text

    def list_models(self) -> list[str]:
        if self._auth_mode == "cookie":
            return ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview"]
        try:
            return [m.name for m in self._client.models.list()]
        except Exception:
            return ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview"]
