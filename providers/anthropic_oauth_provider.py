"""
Anthropic Claude OAuth Provider — Direct OAuth PKCE authentication and Claude API access.

OAuth PKCE Flow:
1. Browser opens -> Anthropic Claude Login
2. Local callback server intercepts the authorization code
3. Access token + refresh token are fetched and saved locally
4. Claude API calls are made directly using Bearer tokens
"""
import hashlib
import http.server
import json
import logging
import os
import re
import secrets
import socketserver
import base64
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Generator
import anthropic
from providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Anthropic OAuth Client ID (public identifier used by Claude Code CLI)
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

# OAuth scopes
SCOPES = [
    "user:profile",
    "user:inference",
    "user:sessions:claude_code",
    "user:mcp_servers",
    "user:file_upload",
    "org:create_api_key",
]

# Auth and Token endpoints
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"

# Stored token path
TOKEN_PATH = Path.home() / ".Koza" / "anthropic_oauth.json"

# Default models
CLAUDE_MODELS = [
    "claude-3-7-sonnet-latest",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-latest",
    "claude-3-opus-20240229",
]


# ─── PKCE Helpers ────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = hashlib.sha256(verifier.encode()).digest()
    challenge_b64 = urllib.parse.quote(
        base64url(challenge).rstrip("="), safe=""
    )
    return verifier, challenge_b64


def base64url(data: bytes) -> str:
    """Base64 URL-safe encoding without padding."""
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


# ─── Token Management ────────────────────────────────────────────────────────

def _load_tokens() -> dict | None:
    """Load saved OAuth tokens."""
    if TOKEN_PATH.exists():
        try:
            data = json.loads(TOKEN_PATH.read_text())
            if data.get("refresh") and data.get("access"):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_tokens(data: dict) -> None:
    """Save OAuth tokens atomically."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.chmod(0o600)
    tmp.replace(TOKEN_PATH)


def _token_expired(token_data: dict) -> bool:
    """Check if access token is expired (with 60s buffer)."""
    expires = token_data.get("expires", 0)
    return time.time() >= (expires / 1000) - 60


def refresh_access_token(token_data: dict) -> dict | None:
    """Refresh the access token using the refresh token."""
    refresh_token = token_data.get("refresh", "")
    if not refresh_token:
        return None

    try:
        data = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode()

        req = urllib.request.Request(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        new_data = dict(token_data)
        new_data["access"] = result["access_token"]
        new_data["expires"] = int(time.time() + result.get("expires_in", 3600)) * 1000

        if "refresh_token" in result:
            new_data["refresh"] = result["refresh_token"]

        _save_tokens(new_data)
        return new_data
    except Exception as e:
        logger.error(f"Anthropic token refresh failed: {e}")
        if "invalid_grant" in str(e):
            TOKEN_PATH.unlink(missing_ok=True)
        return None


def get_valid_access_token(token_data: dict) -> str | None:
    """Get a valid access token, refreshing if needed."""
    if _token_expired(token_data):
        refreshed = refresh_access_token(token_data)
        if refreshed:
            return refreshed["access"]
        return None
    return token_data["access"]


# ─── OAuth Login Flow ────────────────────────────────────────────────────────

def run_oauth_login() -> bool:
    """Run the OAuth PKCE flow for Anthropic Claude. Returns True on success."""
    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(16)

    received_code = []
    received_state = []
    server_ready = threading.Event()

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            query = urllib.parse.parse_qs(parsed.query)
            received_code.append(query.get("code", [None])[0])
            received_state.append(query.get("state", [None])[0])
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<html><body><h3>✅ Koza - Connected to Anthropic Claude!</h3>"
                "<p>You can close this tab and return to the application.</p></body></html>".encode()
            )

        def log_message(self, format, *args):
            pass

    # Start server on a free port first to determine redirect_uri
    server = None
    selected_port = 8085
    for port in [8085, 8086, 8087, 8088, 8089]:
        try:
            server = socketserver.TCPServer(("127.0.0.1", port), CallbackHandler)
            server.timeout = 300  # 5 min timeout
            selected_port = port
            break
        except OSError:
            continue

    if server is None:
        print("  ❌ Could not bind local callback server to ports 8085-8089.")
        return False

    redirect_uri = f"http://localhost:{selected_port}/callback"

    # Auth URL
    params = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    auth_url = f"{AUTHORIZE_URL}?{params}"

    # Browser flow
    import webbrowser
    print(f"\n  🌐 Opening browser...")
    print(f"  Please sign in to your Anthropic Claude account.")
    print(f"  (Will timeout in 5 minutes if not completed)\n")
    webbrowser.open(auth_url)
    server_ready.set()
    server.handle_request()
    server.server_close()

    if not received_code or not received_state[0]:
        print("  ❌ Could not retrieve authorization code.")
        return False

    if received_state[0] != state:
        print("  ❌ State mismatch (CSRF).")
        return False

    # Exchange code for tokens
    code = received_code[0]
    try:
        data = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }).encode()

        req = urllib.request.Request(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read())

        # Get user email
        email = "unknown"
        try:
            # We can request user profile if endpoint exists or just default to connected account
            # Anthropic doesn't have a simple standard userinfo endpoint like Google,
            # but we can try to query or just use a default label.
            pass
        except Exception:
            pass

        # Pack tokens
        token_data = {
            "access": tokens["access_token"],
            "refresh": tokens.get("refresh_token", ""),
            "expires": int(time.time() + tokens.get("expires_in", 3600)) * 1000,
            "email": email,
        }

        _save_tokens(token_data)
        print(f"  ✅ Connected to Anthropic Claude account.")
        print(f"  🧠 Available models: {', '.join(CLAUDE_MODELS)}")
        return True
    except Exception as e:
        print(f"  ❌ Failed to retrieve token: {e}")
        return False


# ─── Custom OAuth Client for Anthropic SDK ────────────────────────────────────

class AnthropicOAuthClient(anthropic.Anthropic):
    """Subclass of Anthropic client to override auth headers with Bearer token."""
    
    def __init__(self, access_token: str, **kwargs):
        # Pass placeholder API key to satisfy SDK check
        super().__init__(api_key="oauth-placeholder", **kwargs)
        self.access_token = access_token

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


# ─── Provider Implementation ──────────────────────────────────────────────────

class AnthropicOAuthProvider(LLMProvider):
    """Claude provider via direct OAuth authentication."""

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self._model = cfg.get("model", "claude-3-5-sonnet-20241022")
        self._token_data = _load_tokens()
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        if self._token_data:
            try:
                token = get_valid_access_token(self._token_data)
                if token:
                    self._client = AnthropicOAuthClient(access_token=token)
            except Exception as e:
                logger.error(f"Failed to initialize Anthropic OAuth client: {e}")

    def _ensure_auth(self) -> AnthropicOAuthClient:
        self._token_data = _load_tokens()
        if not self._token_data:
            raise RuntimeError(
                "Not connected to Anthropic account. "
                "Please connect your account in the settings panel."
            )
        token = get_valid_access_token(self._token_data)
        if not token:
            raise RuntimeError("Token expired or invalid. Please connect your account again.")
        
        # Keep client up to date with refreshed token
        if not self._client or self._client.access_token != token:
            self._client = AnthropicOAuthClient(access_token=token)
        return self._client

    @property
    def name(self) -> str:
        return "anthropic-oauth"

    @property
    def supports_thinking(self) -> bool:
        return "claude-3-7" in self._model or "claude-4" in self._model

    @property
    def supports_vision(self) -> bool:
        return "claude-3" in self._model or "claude-4" in self._model

    def list_models(self) -> list[str]:
        return CLAUDE_MODELS

    @staticmethod
    def _adapt_vision_messages(messages: list[dict]) -> list[dict]:
        adapted = []
        for m in messages:
            content = m.get("content")
            if isinstance(content, list):
                new_content = []
                for item in content:
                    if item.get("type") == "text":
                        new_content.append({"type": "text", "text": item["text"]})
                    elif item.get("type") == "image_url":
                        url = item["image_url"]["url"]
                        if url.startswith("data:"):
                            header, data = url.split(",", 1)
                            media_type = header.split(":")[1].split(";")[0]
                            new_content.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": data,
                                },
                            })
                adapted.append({**m, "content": new_content})
            else:
                adapted.append(m)
        return adapted

    def chat(self, messages, tools=None, stream=False):
        client = self._ensure_auth()
        messages = self._adapt_vision_messages(messages)
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        msgs = [m for m in messages if m["role"] != "system"]
        kwargs = {"model": self._model, "max_tokens": 4096, "messages": msgs}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in tools
            ]
        resp = client.messages.create(**kwargs)
        content_text = None
        tool_calls = None
        for block in resp.content:
            if block.type == "text":
                content_text = block.text
            elif block.type == "tool_use":
                tool_calls = tool_calls or []
                tool_calls.append({"id": block.id, "name": block.name, "arguments": block.input})
        return {"content": content_text, "tool_calls": tool_calls}

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Generator[str | dict, None, None]:
        client = self._ensure_auth()
        messages = self._adapt_vision_messages(messages)
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        msgs = [m for m in messages if m["role"] != "system"]
        kwargs = {"model": self._model, "max_tokens": 4096, "messages": msgs}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in tools
            ]

        tool_blocks: dict[int, dict] = {}
        current_tool_index: int = -1

        with client.messages.stream(**kwargs) as stream:
            for event in stream:
                if cancel_event and cancel_event.is_set():
                    stream.close()
                    return

                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool_index += 1
                        tool_blocks[current_tool_index] = {
                            "id": block.id,
                            "name": block.name,
                            "input_json": "",
                        }
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield delta.text
                    elif delta.type == "input_json_delta":
                        if current_tool_index in tool_blocks:
                            tool_blocks[current_tool_index]["input_json"] += delta.partial_json

        for idx, tb in sorted(tool_blocks.items()):
            if tb["name"]:
                try:
                    args_parsed = json.loads(tb["input_json"] or "{}")
                except Exception:
                    args_parsed = {}
                yield {
                    "__tool_chunk__": True,
                    "index": idx,
                    "id": tb["id"],
                    "name": tb["name"],
                    "args_chunk": json.dumps(args_parsed),
                }


# ─── CLI login command ────────────────────────────────────────────────────────

def cmd_anthropic_login() -> str:
    """Run the Anthropic OAuth login flow from CLI."""
    if _load_tokens():
        print("  ℹ  Already signed in. To reconnect, delete ~/.Koza/anthropic_oauth.json first.")
        return ""
    if run_oauth_login():
        return "✅ Connected to Anthropic Claude account."
    return "❌ Connection failed."
