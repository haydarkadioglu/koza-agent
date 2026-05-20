"""Google Gemini provider.

Auth modes (set via config providers.gemini.auth):
  api_key  — uses providers.gemini.api_key with google-genai SDK
  cookie   — browser cookie auth via gemini-webapi (no API key)
"""
import asyncio
import threading
from typing import Generator
from .base import LLMProvider


# ── Cookie auth: persistent background event loop ────────────────────────────
_cookie_loop: asyncio.AbstractEventLoop | None = None
_cookie_loop_lock = threading.Lock()


def _get_cookie_loop() -> asyncio.AbstractEventLoop:
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
    loop = _get_cookie_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=120)


# gemini-webapi model name → Model enum mapping
# Free/Basic tier
_COOKIE_MODELS = {
    "gemini-3.5-flash":               "BASIC_FLASH",      # latest flagship free model
    "gemini-3-flash":                 "BASIC_FLASH",
    "gemini-3.1-flash-lite":          "BASIC_FLASH",      # fastest, maps to base flash
    "gemini-3-pro":                   "BASIC_PRO",
    "gemini-3.1-pro":                 "BASIC_PRO",
    "gemini-3-flash-thinking":        "BASIC_THINKING",
    "gemini-3.1-flash-thinking":      "BASIC_THINKING",
    # Plus tier
    "gemini-3-pro-plus":              "PLUS_PRO",
    "gemini-3-flash-plus":            "PLUS_FLASH",
    "gemini-3.5-flash-plus":          "PLUS_FLASH",
    "gemini-3-flash-thinking-plus":   "PLUS_THINKING",
    # Advanced tier
    "gemini-3-pro-advanced":          "ADVANCED_PRO",
    "gemini-3-flash-advanced":        "ADVANCED_FLASH",
    "gemini-3-flash-thinking-advanced": "ADVANCED_THINKING",
}


class GeminiProvider(LLMProvider):
    def __init__(self, cfg: dict):
        auth_mode = cfg.get("auth", "api_key").lower()
        self._model      = cfg.get("model", "gemini-3-flash")
        self._auth_mode  = auth_mode
        self._cookie_client = None

        if auth_mode == "cookie":
            self._cookie_1psid   = cfg.get("cookie_1psid", "")
            self._cookie_1psidts = cfg.get("cookie_1psidts", "")
            if not self._cookie_1psid:
                self._cookie_1psid, self._cookie_1psidts = self._auto_extract_cookies()
            if not self._cookie_1psid:
                raise ValueError(
                    "Cookie auth: no cookie found.\n"
                    "Run 'koza setup' to configure, or log in to gemini.google.com in your browser."
                )

        else:  # api_key
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _auto_extract_cookies() -> tuple[str, str]:
        try:
            import browser_cookie3
        except ImportError:
            return "", ""
        for loader in [
            browser_cookie3.chrome, browser_cookie3.edge,
            browser_cookie3.firefox, browser_cookie3.brave, browser_cookie3.opera,
        ]:
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
        enum_name = _COOKIE_MODELS.get(self._model, "UNSPECIFIED")
        model = getattr(Model, enum_name, Model.UNSPECIFIED)
        async def _run():
            resp = await client.generate_content(prompt, model=model)
            return resp.text
        return _run_async(_run())

    def _convert_tools(self, tools):
        if not tools:
            return None
        from google.genai import types
        decls = []
        for t in tools:
            fn = t["function"]
            decls.append(types.FunctionDeclaration(
                name=fn["name"],
                description=fn.get("description", ""),
                parameters=fn.get("parameters", {}),
            ))
        return [types.Tool(function_declarations=decls)]

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "gemini"

    def chat(self, messages, tools=None, stream=False):
        if self._auth_mode == "cookie":
            prompt = "\n".join(
                f"{m['role'].upper()}: {m['content']}"
                for m in messages if m.get("content")
            )
            return {"content": self._cookie_generate(prompt), "tool_calls": None}

        # api_key mode
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

        kwargs: dict = {"contents": contents}
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
                    "id":        part.function_call.name,
                    "name":      part.function_call.name,
                    "arguments": dict(part.function_call.args),
                })
        return {"content": content_text, "tool_calls": tool_calls}

    def stream_chat(self, messages, tools=None) -> Generator[str, None, None]:
        if self._auth_mode == "cookie":
            result = self.chat(messages)
            if result.get("content"):
                yield result["content"]
            return

        # api_key streaming
        from google.genai import types
        contents = [
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part(text=m["content"] or "")]
            )
            for m in messages if m["role"] != "system"
        ]
        for chunk in self._client.models.generate_content_stream(model=self._model, contents=contents):
            if chunk.text:
                yield chunk.text

    def list_models(self) -> list[str]:
        if self._auth_mode == "cookie":
            return list(_COOKIE_MODELS.keys())
        try:
            return [m.name for m in self._client.models.list()]
        except Exception:
            return ["gemini-3-flash", "gemini-3-pro", "gemini-flash-latest", "gemini-pro-latest"]
