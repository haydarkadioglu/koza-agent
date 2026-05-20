"""Google Gemini provider.

Auth modes (set via config providers.gemini.auth):
  api_key  — default, uses providers.gemini.api_key
  cookie   — browser cookie auth (no API key, uses Gemini Pro web limits)
             requires providers.gemini.cookie_1psid (and optionally cookie_1psidts)
"""
import asyncio
import threading
from typing import Generator
from .base import LLMProvider


# ── Shared persistent event loop for cookie client ───────────────────────────
_cookie_loop: asyncio.AbstractEventLoop | None = None
_cookie_loop_lock = threading.Lock()


def _get_cookie_loop() -> asyncio.AbstractEventLoop:
    """Return (and lazily start) a persistent background event loop."""
    global _cookie_loop
    if _cookie_loop is not None and not _cookie_loop.is_closed():
        return _cookie_loop
    with _cookie_loop_lock:
        if _cookie_loop is None or _cookie_loop.is_closed():
            loop = asyncio.new_event_loop()
            t = threading.Thread(target=loop.run_forever, daemon=True)
            t.start()
            _cookie_loop = loop
    return _cookie_loop


def _run_async(coro):
    """Submit a coroutine to the background loop and block until done."""
    loop = _get_cookie_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=120)


class GeminiProvider(LLMProvider):
    def __init__(self, cfg: dict):
        auth_mode = cfg.get("auth", "api_key").lower()
        self._model = cfg.get("model", "gemini-3.5-flash")
        self._auth_mode = auth_mode
        self._cookie_client = None

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

    def _get_cookie_client(self):
        """Return (lazily initialized) persistent GeminiClient."""
        if self._cookie_client is not None:
            return self._cookie_client
        try:
            from gemini_webapi import GeminiClient
        except ImportError:
            raise ImportError("gemini-webapi not installed. Run: pip install gemini-webapi")

        psid, psidts = self._cookie_1psid, self._cookie_1psidts or None

        async def _init():
            c = GeminiClient(psid, psidts)
            await c.init(timeout=30, auto_close=False, close_delay=600, auto_refresh=True)
            return c

        self._cookie_client = _run_async(_init())
        return self._cookie_client

    def _cookie_generate(self, prompt: str) -> str:
        client = self._get_cookie_client()
        from gemini_webapi.constants import Model

        async def _run():
            try:
                resp = await client.generate_content(prompt, model=self._model)
            except ValueError:
                resp = await client.generate_content(prompt, model=Model.UNSPECIFIED)
            return resp.text

        return _run_async(_run())

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
