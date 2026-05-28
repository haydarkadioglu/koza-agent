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
    # ── Current production models (May 2025) ──────────────────────────────
    "gemini-2.5-flash":               "BASIC_FLASH",      # 3.5 Flash — all-around (thinking capable)
    "gemini-2.5-pro":                 "BASIC_PRO",        # 3.1 Pro — advanced maths & code (thinking capable)
    "gemini-2.0-flash-lite":          "BASIC_FLASH",      # 3.1 Flash-Lite — fastest answers
    "gemini-2.0-flash":               "BASIC_FLASH",
    # ── Thinking-specific aliases ──────────────────────────────────────────
    "gemini-2.5-flash-thinking":      "BASIC_THINKING",
    "gemini-2.5-pro-thinking":        "BASIC_THINKING",
    # ── Plus tier ─────────────────────────────────────────────────────────
    "gemini-2.5-flash-plus":          "PLUS_FLASH",
    "gemini-2.5-pro-plus":            "PLUS_PRO",
    # ── Advanced tier ─────────────────────────────────────────────────────
    "gemini-2.5-pro-advanced":        "ADVANCED_PRO",
    "gemini-2.5-flash-advanced":      "ADVANCED_FLASH",
}

# Image model names for cookie-mode Imagen (Pro account required)
_IMAGEN_MODELS = {
    "imagen-nano":    "IMAGEN_NANO",       # Imagen 3 Nano — fastest, free with Pro
    "imagen-banana":  "IMAGEN_BANANA",     # Imagen Banana  — free with Pro
    "imagen-3":       "IMAGEN_3",          # Imagen 3 standard
}

# Veo video model names for cookie-mode (Pro account required)
_VEO_MODELS = {
    "veo-2":   "VEO_2",     # Veo 2 — free with Pro
    "veo":     "VEO_2",
}


class GeminiProvider(LLMProvider):
    def __init__(self, cfg: dict):
        auth_mode = cfg.get("auth", "api_key").lower()
        self._model      = cfg.get("model", "gemini-2.5-flash")
        self._auth_mode  = auth_mode
        self._cookie_client = None

        if auth_mode == "cookie":
            self._cookie_1psid   = cfg.get("cookie_1psid", "")
            self._cookie_1psidts = cfg.get("cookie_1psidts", "")
            if not self._cookie_1psid:
                self._cookie_1psid, self._cookie_1psidts = self._auto_extract_cookies()
            if not self._cookie_1psid:
                raise ValueError(
                    "Cookie auth: no Google session found.\n"
                    "Run 'koza setup' to configure a Gemini browser session, "
                    "or sign in to gemini.google.com in your browser."
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
        # First try browser_cookie3 (reads from running browser)
        try:
            import browser_cookie3
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
        except ImportError:
            pass

        # Fallback: read from saved Playwright profile
        return GeminiProvider._extract_playwright_cookies()

    @staticmethod
    def _extract_playwright_cookies() -> tuple[str, str]:
        """Extract Google session cookies from the saved Playwright Chromium profile."""
        import os
        profile_dir = os.path.join(os.path.expanduser("~"), ".koza", "gemini_browser")
        prefs = os.path.join(profile_dir, "Default", "Preferences")
        if not os.path.isfile(prefs):
            return "", ""
        try:
            from playwright.sync_api import sync_playwright
            psid = psidts = ""
            with sync_playwright() as pw:
                browser = pw.chromium.launch_persistent_context(
                    profile_dir,
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                cookies = browser.cookies("https://gemini.google.com")
                browser.close()
            for c in cookies:
                if c["name"] == "__Secure-1PSID":
                    psid = c["value"]
                elif c["name"] == "__Secure-1PSIDTS":
                    psidts = c["value"]
            return psid, psidts
        except Exception:
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

    # ── Playwright-based media generation ────────────────────────────────────

    def _get_playwright_profile_dir(self) -> str:
        """Return the persistent browser profile directory for Gemini login session."""
        import os
        base = os.path.join(os.path.expanduser("~"), ".koza", "gemini_browser")
        os.makedirs(base, exist_ok=True)
        return base

    def _playwright_generate_image(self, prompt: str, save_path: str = "") -> str:
        """Use a persistent Playwright browser session to generate an image on gemini.google.com."""
        import os, time, tempfile
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

        profile_dir = self._get_playwright_profile_dir()
        path = save_path or os.path.join(tempfile.gettempdir(), f"koza_img_{int(time.time())}.png")

        with sync_playwright() as pw:
            browser = pw.chromium.launch_persistent_context(
                profile_dir,
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()

            try:
                page.goto("https://gemini.google.com/", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=20000)

                # Detect login wall
                if "accounts.google.com" in page.url or page.locator("text=Sign in").count() > 0:
                    browser.close()
                    return (
                        "❌ PERMANENT FAILURE — do not retry. "
                        "Not logged in to Gemini in the browser profile. "
                        "Run 'koza generate --login' to open the browser and log in first."
                    )

                # Type the image generation prompt into the chat input
                chat_input = page.locator(
                    "div[contenteditable='true'], textarea[placeholder*='Gemini'], "
                    "rich-textarea div[contenteditable]"
                ).first
                chat_input.click()
                chat_input.fill("")
                chat_input.type(f"Generate an image of: {prompt}", delay=30)

                # Intercept the generated image response
                downloaded: list[bytes] = []

                def handle_response(response):
                    url = response.url
                    if any(kw in url for kw in ["lh3.googleusercontent", "aisandbox-pa", "generativelanguage"]):
                        ct = response.headers.get("content-type", "")
                        if "image" in ct:
                            try:
                                downloaded.append(response.body())
                            except Exception:
                                pass

                page.on("response", handle_response)

                # Submit prompt
                page.keyboard.press("Enter")

                # Wait for an image to appear in the DOM (up to 90s for generation)
                try:
                    img_locator = page.locator(
                        "img[src*='lh3.googleusercontent'], "
                        "img[src*='aisandbox-pa'], "
                        "div[data-test-id='generated-image'] img, "
                        "message-content img[alt*='Generated']"
                    ).first
                    img_locator.wait_for(timeout=90000)
                    img_url = img_locator.get_attribute("src")
                except PwTimeout:
                    img_url = None

                browser.close()

                # Save from intercepted response bytes first
                if downloaded:
                    with open(path, "wb") as f:
                        f.write(downloaded[-1])
                    return path

                # Fallback: download via URL found in DOM
                if img_url:
                    import requests as _req
                    r = _req.get(img_url, timeout=60)
                    r.raise_for_status()
                    with open(path, "wb") as f:
                        f.write(r.content)
                    return path

                return (
                    "❌ PERMANENT FAILURE — do not retry. "
                    "No image appeared in Gemini after 90 seconds. "
                    "Ensure your account has Pro access (Imagen requires a Pro plan)."
                )

            except PwTimeout:
                try:
                    browser.close()
                except Exception:
                    pass
                return (
                    "❌ PERMANENT FAILURE — do not retry. "
                    "Timed out waiting for Gemini to load. Check internet connection."
                )
            except Exception as e:
                try:
                    browser.close()
                except Exception:
                    pass
                return f"❌ PERMANENT FAILURE — do not retry. Playwright error: {e}"

    def _playwright_generate_video(self, prompt: str, save_path: str = "") -> str:
        """Use a persistent Playwright browser session to generate a video on gemini.google.com."""
        import os, time, tempfile
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

        profile_dir = self._get_playwright_profile_dir()
        path = save_path or os.path.join(tempfile.gettempdir(), f"koza_vid_{int(time.time())}.mp4")

        with sync_playwright() as pw:
            browser = pw.chromium.launch_persistent_context(
                profile_dir,
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()

            try:
                page.goto("https://gemini.google.com/", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=20000)

                if "accounts.google.com" in page.url or page.locator("text=Sign in").count() > 0:
                    browser.close()
                    return (
                        "❌ PERMANENT FAILURE — do not retry. "
                        "Not logged in to Gemini. Run 'koza generate --login' first."
                    )

                chat_input = page.locator(
                    "div[contenteditable='true'], textarea[placeholder*='Gemini'], "
                    "rich-textarea div[contenteditable]"
                ).first
                chat_input.click()
                chat_input.fill("")
                chat_input.type(f"Generate a video of: {prompt}", delay=30)

                downloaded_video: list[tuple[str, bytes]] = []

                def handle_video_response(response):
                    url = response.url
                    ct = response.headers.get("content-type", "")
                    if "video" in ct or url.endswith(".mp4"):
                        try:
                            downloaded_video.append((url, response.body()))
                        except Exception:
                            pass

                page.on("response", handle_video_response)
                page.keyboard.press("Enter")

                # Videos take longer — wait up to 3 minutes
                try:
                    vid_locator = page.locator(
                        "video, "
                        "div[data-test-id='generated-video'] video, "
                        "message-content video"
                    ).first
                    vid_locator.wait_for(timeout=180000)
                    vid_src = vid_locator.get_attribute("src")
                except PwTimeout:
                    vid_src = None

                browser.close()

                if downloaded_video:
                    with open(path, "wb") as f:
                        f.write(downloaded_video[-1][1])
                    return path

                if vid_src:
                    import requests as _req
                    r = _req.get(vid_src, timeout=300)
                    r.raise_for_status()
                    with open(path, "wb") as f:
                        f.write(r.content)
                    return path

                return (
                    "❌ PERMANENT FAILURE — do not retry. "
                    "No video appeared in Gemini after 3 minutes. "
                    "Ensure your account has Pro access (Veo requires a Pro plan)."
                )

            except PwTimeout:
                try:
                    browser.close()
                except Exception:
                    pass
                return (
                    "❌ PERMANENT FAILURE — do not retry. "
                    "Timed out waiting for Gemini. Check internet connection."
                )
            except Exception as e:
                try:
                    browser.close()
                except Exception:
                    pass
                return f"❌ PERMANENT FAILURE — do not retry. Playwright error: {e}"

    def generate_image_cookie(self, prompt: str, model_name: str = "imagen-nano", save_path: str = "") -> str:
        """Generate an image via Playwright browser session (Pro account required)."""
        return self._playwright_generate_image(prompt, save_path)

    def generate_video_cookie(self, prompt: str, model_name: str = "veo-2", save_path: str = "") -> str:
        """Generate a video via Playwright browser session (Pro account required)."""
        return self._playwright_generate_video(prompt, save_path)

    @staticmethod
    def _build_react_tools_prompt(tools: list) -> str:
        """Inject tool definitions into the prompt for ReAct-style tool calling in cookie mode."""
        if not tools:
            return ""
        lines = [
            "## Available Tools",
            "You can call tools by outputting EXACTLY this format on its own lines:",
            '<tool_call>{"name": "TOOL_NAME", "arguments": {"param": "value"}}</tool_call>',
            "You may call multiple tools. After tool results are provided, continue answering.",
            "",
            "Tools:",
        ]
        for t in tools[:40]:  # cap to keep prompt size reasonable
            fn = t.get("function", t)
            name = fn.get("name", "")
            desc = fn.get("description", "")[:120]
            props = fn.get("parameters", {}).get("properties", {})
            params = ", ".join(f"{k}" for k in list(props.keys())[:6])
            lines.append(f"- {name}({params}): {desc}")
        return "\n".join(lines)

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

    def _messages_to_contents(self, messages):
        """Convert OpenAI-style messages list to Gemini contents + system_text.

        Gemini rules:
        - system → extracted separately as system_instruction
        - user/assistant turns alternate; consecutive same-role turns are merged
        - tool results (role=tool) MUST be grouped into the single user Content
          that immediately follows the assistant's function_call Content
        """
        from google.genai import types
        system_text = None
        contents = []

        i = 0
        while i < len(messages):
            m = messages[i]
            role = m.get("role", "")

            if role == "system":
                system_text = m.get("content") or system_text
                i += 1
                continue

            if role == "user":
                # Collect consecutive tool results that immediately follow as one Content
                parts = []
                content = m.get("content")
                if isinstance(content, list):
                    # Vision message: content is a list of text/image_url items
                    for item in content:
                        if item.get("type") == "text":
                            parts.append(types.Part(text=item["text"]))
                        elif item.get("type") == "image_url":
                            url = item["image_url"]["url"]
                            if url.startswith("data:"):
                                header, b64data = url.split(",", 1)
                                mime = header.split(":")[1].split(";")[0]
                                import base64 as _b64
                                parts.append(types.Part.from_bytes(
                                    data=_b64.b64decode(b64data),
                                    mime_type=mime,
                                ))
                elif content:
                    parts.append(types.Part(text=content))
                i += 1
                # Peek: collect any consecutive tool turns right after
                while i < len(messages) and messages[i].get("role") == "tool":
                    t = messages[i]
                    try:
                        parts.append(types.Part(
                            function_response=types.FunctionResponse(
                                name=t.get("name", "tool"),
                                response={"result": t.get("content", "")},
                            )
                        ))
                    except Exception:
                        parts.append(types.Part(
                            text=f"Tool result ({t.get('name','tool')}): {t.get('content','')}"
                        ))
                    i += 1
                if parts:
                    contents.append(types.Content(role="user", parts=parts))
                continue

            if role == "tool":
                # Orphan tool messages (no preceding user turn) — group them
                parts = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    t = messages[i]
                    try:
                        parts.append(types.Part(
                            function_response=types.FunctionResponse(
                                name=t.get("name", "tool"),
                                response={"result": t.get("content", "")},
                            )
                        ))
                    except Exception:
                        parts.append(types.Part(
                            text=f"Tool result ({t.get('name','tool')}): {t.get('content','')}"
                        ))
                    i += 1
                if parts:
                    contents.append(types.Content(role="user", parts=parts))
                continue

            if role == "assistant":
                text = m.get("content") or ""
                parts = [types.Part(text=text)] if text else []
                for tc in (m.get("tool_calls") or []):
                    try:
                        parts.append(types.Part(
                            function_call=types.FunctionCall(
                                name=tc["name"],
                                args=tc.get("arguments", {}),
                            )
                        ))
                    except Exception:
                        pass
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
                i += 1
                continue

            i += 1

        return contents, system_text

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def supports_vision(self) -> bool:
        # All Gemini API-key models support vision; cookie mode doesn't (yet)
        return self._auth_mode == "api_key"

    @property
    def supports_thinking(self) -> bool:
        # gemini-2.5-flash and gemini-2.5-pro support thinking levels
        m = self._model.lower()
        return "2.5" in m or "thinking" in m

    def chat(self, messages, tools=None, stream=False):
        if self._auth_mode == "cookie":
            import re, json as _json
            parts = []
            # Prepend system message (Koza persona) if present
            for m in messages:
                if m.get("role") == "system" and m.get("content"):
                    parts.append(f"SYSTEM INSTRUCTION:\n{m['content']}")
                    break
            # Prepend tools prompt if tools provided
            if tools:
                parts.append(self._build_react_tools_prompt(tools))
            for m in messages:
                if not m.get("content"):
                    continue
                role = m["role"]
                if role == "system":
                    continue  # already prepended above
                if role == "tool":
                    parts.append(f"TOOL_RESULT ({m.get('name', 'tool')}): {m['content']}")
                elif role == "user":
                    parts.append(f"USER: {m['content']}")
                elif role == "assistant":
                    parts.append(f"ASSISTANT: {m['content']}")
            prompt = "\n\n".join(parts)
            raw = self._cookie_generate(prompt)

            # Parse <tool_call>...</tool_call> blocks
            tool_calls = []
            pattern = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
            for i, match in enumerate(pattern.findall(raw)):
                try:
                    tc = _json.loads(match.strip())
                    tool_calls.append({
                        "id":        tc.get("name", f"call_{i}"),
                        "name":      tc.get("name"),
                        "arguments": tc.get("arguments", {}),
                    })
                except Exception:
                    pass

            # Strip tool_call blocks from visible text
            clean = pattern.sub("", raw).strip()
            return {
                "content":    clean or None,
                "tool_calls": tool_calls if tool_calls else None,
            }

        # api_key mode
        contents, system_text = self._messages_to_contents(messages)

        from google.genai import types as _types
        cfg_kwargs: dict = {}
        if system_text:
            cfg_kwargs["system_instruction"] = system_text
        if tools:
            cfg_kwargs["tools"] = self._convert_tools(tools)
        config = _types.GenerateContentConfig(**cfg_kwargs) if cfg_kwargs else None

        gen_kwargs: dict = {"model": self._model, "contents": contents}
        if config:
            gen_kwargs["config"] = config

        resp = self._client.models.generate_content(**gen_kwargs)
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
            import json as _json
            result = self.chat(messages, tools=tools)
            # Yield tool chunks first so core.py's _tool_buf is populated
            for idx, tc in enumerate(result.get("tool_calls") or []):
                yield {
                    "__tool_chunk__": True,
                    "index": idx,
                    "id":   tc.get("id") or tc.get("name"),
                    "name": tc.get("name"),
                    "args_chunk": _json.dumps(tc.get("arguments", {})),
                }
            if result.get("content"):
                yield result["content"]
            return

        # api_key streaming — use shared message converter
        contents, system_text = self._messages_to_contents(messages)

        from google.genai import types as _types
        cfg_kwargs: dict = {}
        if system_text:
            cfg_kwargs["system_instruction"] = system_text
        if tools:
            cfg_kwargs["tools"] = self._convert_tools(tools)
        stream_config = _types.GenerateContentConfig(**cfg_kwargs) if cfg_kwargs else None

        gen_stream_kwargs: dict = {"model": self._model, "contents": contents}
        if stream_config:
            gen_stream_kwargs["config"] = stream_config

        for chunk in self._client.models.generate_content_stream(**gen_stream_kwargs):
            if chunk.text:
                yield chunk.text
            # Handle streaming tool calls
            if chunk.candidates:
                for part in (chunk.candidates[0].content.parts if chunk.candidates[0].content else []):
                    if hasattr(part, "function_call") and part.function_call:
                        import json as _json
                        yield {
                            "__tool_chunk__": True,
                            "index": 0,
                            "id":   part.function_call.name,
                            "name": part.function_call.name,
                            "args_chunk": _json.dumps(dict(part.function_call.args)),
                        }

    def list_models(self) -> list[str]:
        if self._auth_mode == "cookie":
            return list(_COOKIE_MODELS.keys())
        try:
            return [m.name for m in self._client.models.list()]
        except Exception:
            return ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash-lite", "gemini-2.0-flash"]
