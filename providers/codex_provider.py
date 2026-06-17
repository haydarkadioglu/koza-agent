"""
OpenAI Codex Provider — OAuth tabanli OpenAI Codex CLI entegrasyonu.

Codex CLI, OpenAI'nin terminal tabanli kodlama asistani.
Bu provider, Codex'in OAuth akisini kullanarak OpenAI API'sine
baglanir ve kod-optimize modelleri kullanir.

Auth: OAuth PKCE (OpenAI login) veya API Key
API: api.openai.com (OpenAI standart API)
"""
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Generator
from providers.base import LLMProvider

logger = logging.getLogger(__name__)

# OpenAI OAuth endpoints
OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"

# OpenAI API
OPENAI_API = "https://api.openai.com/v1"

# Available models (code-optimized + general purpose)
CODEX_MODELS = [
    "o4-mini", "o3", "o4-mini-high", "gpt-4.1", "gpt-4.1-nano",
    "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini",
]

# Token storage
TOKEN_PATH = Path.home() / ".Koza" / "codex_oauth.json"


# ─── Token Management ────────────────────────────────────────────────────────

def _load_tokens() -> dict | None:
    if TOKEN_PATH.exists():
        try:
            return json.loads(TOKEN_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_tokens(data: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.chmod(0o600)
    tmp.replace(TOKEN_PATH)


# ─── Login Flow ──────────────────────────────────────────────────────────────

def cmd_codex_login() -> str:
    """Run Codex login — paste session key or use OAuth."""
    tokens = _load_tokens()
    if tokens and tokens.get("api_key"):
        return "ℹ️  Already logged in."

    print("\n  🅾️  OpenAI Codex — Connection")
    print("  ─────────────────────────────\n")

    choice = input("  [1] Enter API Key\n  [2] Connect with GitHub OAuth\n  Choice: ").strip()

    if choice == "1":
        api_key = input("  OpenAI API Key: ").strip()
        if api_key:
            _save_tokens({"api_key": api_key, "method": "api_key"})
            print("  ✅ API Key saved.")
            return "✅ Codex provider ready."
        else:
            return "❌ API Key not entered."

    elif choice == "2":
        print("\n  🌐 Starting GitHub OAuth...")
        print("  (No direct OAuth support yet, use API Key)\n")
        return "ℹ️  Use with API Key: koza setup → codex"

    return "❌ Invalid choice."


# ─── Provider Implementation ─────────────────────────────────────────────────

class CodexProvider(LLMProvider):
    """OpenAI Codex provider — OAuth veya API Key ile."""

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self._model = cfg.get("model", "gpt-4.1")
        self._token_data = _load_tokens()
        # Fallback to config api_key
        if not self._token_data or not self._token_data.get("api_key"):
            api_key = cfg.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
            if api_key:
                self._token_data = {"api_key": api_key, "method": "config"}

    @property
    def name(self) -> str:
        return "codex"

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def supports_thinking(self) -> bool:
        return self._model in ("o3", "o4-mini", "o4-mini-high")

    def list_models(self) -> list[str]:
        return CODEX_MODELS

    def _get_api_key(self) -> str:
        self._token_data = _load_tokens() or self._token_data
        if not self._token_data:
            raise RuntimeError(
                "Codex auth yok. Terminalde 'codex-login' yazarak API Key girin "
                "veya koza setup ile codex provider'ini secin."
            )
        key = self._token_data.get("api_key", "")
        if not key:
            raise RuntimeError("API Key bulunamadi. codex-login ile tekrar giris yapin.")
        return key

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict:
        if stream:
            return self._fallback_stream(messages, tools)

        api_key = self._get_api_key()
        from .openai_provider import OpenAIProvider

        # Reuse OpenAI provider with our key and model
        pcfg = {
            "api_key": api_key,
            "model": self._model,
            "base_url": self._cfg.get("base_url", ""),
        }
        provider = OpenAIProvider(pcfg)
        return provider.chat(messages, tools=tools, stream=False)

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Generator[str | dict, None, None]:
        api_key = self._get_api_key()
        from .openai_provider import OpenAIProvider

        pcfg = {
            "api_key": api_key,
            "model": self._model,
            "base_url": self._cfg.get("base_url", ""),
        }
        provider = OpenAIProvider(pcfg)
        yield from provider.stream_chat(messages, tools=tools, cancel_event=cancel_event)
