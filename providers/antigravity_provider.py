"""Antigravity Provider — Direct Google/Anthropic OAuth router without external proxy app.

Delegates calls to GoogleOAuthProvider or AnthropicOAuthProvider based on the selected model.
"""
from typing import Generator
from .base import LLMProvider


class AntigravityProvider(LLMProvider):
    """Routes requests directly via OAuth credentials without an external proxy."""

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._model = cfg.get("model", "gemini-2.5-flash")
        self._delegate = None
        self._init_delegate()

    def _init_delegate(self):
        # Update model name from config
        self._model = self._cfg.get("model", self._model)
        m = self._model.lower()
        
        if "gemini" in m:
            from .google_oauth_provider import GoogleOAuthProvider
            self._delegate = GoogleOAuthProvider(self._cfg)
        elif "claude" in m or "anthropic" in m:
            from .anthropic_oauth_provider import AnthropicOAuthProvider
            self._delegate = AnthropicOAuthProvider(self._cfg)
        else:
            # Default fallback to Google OAuth
            from .google_oauth_provider import GoogleOAuthProvider
            self._delegate = GoogleOAuthProvider(self._cfg)

    def _update_client_key(self) -> None:
        self._init_delegate()
        if self._delegate and hasattr(self._delegate, "_update_client_key"):
            self._delegate._update_client_key()

    @property
    def name(self) -> str:
        return "antigravity"

    @property
    def supports_vision(self) -> bool:
        self._init_delegate()
        return self._delegate.supports_vision

    @property
    def supports_thinking(self) -> bool:
        self._init_delegate()
        return self._delegate.supports_thinking

    def chat(self, messages, tools=None, stream=False):
        self._init_delegate()
        return self._delegate.chat(messages, tools, stream)

    def stream_chat(self, messages, tools=None, cancel_event=None) -> Generator[str | dict, None, None]:
        self._init_delegate()
        return self._delegate.stream_chat(messages, tools, cancel_event)

    def list_models(self) -> list[str]:
        from .google_oauth_provider import GEMINI_MODELS
        from .anthropic_oauth_provider import CLAUDE_MODELS
        return GEMINI_MODELS + CLAUDE_MODELS
