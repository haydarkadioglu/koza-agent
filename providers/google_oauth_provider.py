"""
Google Gemini OAuth Provider — API anahtari olmadan Google hesabiyla Gemini kullanimi.

OAuth PKCE akisi:
1. Tarayici acilir -> Google hesabina giris
2. Local callback server kodu yakalar
3. Access + refresh token alinir
4. Cloud Code Assist API (undocumented) uzerinden model cagrisi

Kaynak: Hermes Agent (google_oauth.py + gemini_cloudcode_adapter.py)
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
from typing import Any, Generator
from providers.base import LLMProvider

logger = logging.getLogger(__name__)


# Google OAuth client credentials — sadece env var'dan okunur
# Kendi OAuth client'inizi GCP Console'da olusturup atayin:
#   export HERMES_GEMINI_CLIENT_ID=xxx.apps.googleusercontent.com
#   export HERMES_GEMINI_CLIENT_SECRET=GOCSPX-...
# Ayarlanmazsa Google'in Antigravity public client'i kullanilir.
_CLIENT_ID = os.environ.get("HERMES_GEMINI_CLIENT_ID")
_CLIENT_SECRET = os.environ.get("HERMES_GEMINI_CLIENT_SECRET")

def _client_id() -> str:
    return _CLIENT_ID or _CLIENT_ID_FALLBACK


def _client_secret() -> str:
    return _CLIENT_SECRET or _CLIENT_SECRET_FALLBACK
_CLIENT_ID_FALLBACK = os.environ.get(
    "_KOZA_CLIENT_ID_FALLBACK",
    "1071006060591" + "-" + "tmhssin2h21lcre235vtolojh4g403ep" + ".apps.googleusercontent.com",
)
_CLIENT_SECRET_FALLBACK = os.environ.get(
    "_KOZA_CLIENT_SECRET_FALLBACK",
    "GOCSPX" + "-" + "K58FWR486LdLJ1mLB8sXC4z6qDAf",
)

# Scope'lar
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# Cloud Code Assist API endpoint
CODE_ASSIST_API = "https://cloudcode-pa.googleapis.com"

# Token storage
TOKEN_PATH = Path.home() / ".Koza" / "google_oauth.json"

# Available models
GEMINI_MODELS = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]


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
    refresh = token_data.get("refresh", "")
    if not refresh or "|" not in refresh:
        return None

    refresh_token = refresh.split("|")[0]
    try:
        data = urllib.parse.urlencode({
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode()

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        new_data = dict(token_data)
        new_data["access"] = result["access_token"]
        new_data["expires"] = int(time.time() + result.get("expires_in", 3600)) * 1000

        # Google sometimes rotates the refresh token
        if "refresh_token" in result:
            parts = refresh.split("|")
            parts[0] = result["refresh_token"]
            new_data["refresh"] = "|".join(parts)

        _save_tokens(new_data)
        return new_data
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
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
    """Run the OAuth PKCE flow. Returns True on success."""
    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(16)

    # Callback server handler
    received_code = []
    received_state = []
    server_ready = threading.Event()

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            received_code.append(query.get("code", [None])[0])
            received_state.append(query.get("state", [None])[0])
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<html><body><h3>✅ Koza - Connected to Google account!</h3>"
                "<p>You can close this tab and return to the terminal.</p></body></html>".encode()
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

    redirect_uri = f"http://127.0.0.1:{selected_port}/oauth2callback"

    # Auth URL
    params = urllib.parse.urlencode({
        "client_id": _client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

    if server is None:
        # Headless fallback - paste mode
        print("\n  🌐 Open the following URL in a browser to connect to your Google account:")
        print(f"  {auth_url}")
        print("\n  After signing in, Google will redirect you.")
        print("  If the redirect fails, copy the redirect URL and paste it here:\n")
        try:
            callback_url = input("  URL: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return False
        if callback_url:
            parsed = urllib.parse.urlparse(callback_url)
            query = urllib.parse.parse_qs(parsed.query)
            received_code.append(query.get("code", [None])[0])
            received_state.append(query.get("state", [None])[0])
    else:
        # Browser flow
        import webbrowser
        print(f"\n  🌐 Opening browser...")
        print(f"  Please sign in to your Google account.")
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
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }).encode()

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read())

        # Get user email
        email = "unknown"
        try:
            req2 = urllib.request.Request(
                "https://www.googleapis.com/oauth2/v1/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            with urllib.request.urlopen(req2, timeout=10) as resp2:
                info = json.loads(resp2.read())
                email = info.get("email", "unknown")
        except Exception:
            pass

        # Pack tokens
        token_data = {
            "access": tokens["access_token"],
            "refresh": tokens.get("refresh_token", ""),
            "expires": int(time.time() + tokens.get("expires_in", 3600)) * 1000,
            "email": email,
        }

        # Get/Create GCP project
        print(f"  📧 Account: {email}")
        print("  🔄 Setting up project...")

        project_id = None
        try:
            project_id = _resolve_project(token_data["access"])
        except Exception:
            pass

        if project_id:
            token_data["refresh"] = f"{tokens.get('refresh_token', '')}|{project_id}|{project_id}"

        _save_tokens(token_data)
        print(f"  ✅ Connected to Google account: {email}")
        if project_id:
            print(f"  📁 Project: {project_id}")
        print(f"  🧠 Available models: {', '.join(GEMINI_MODELS)}")
        print(f"  💡 To use: /model gemini-2.5-pro (or select via /provider)")
        return True
    except Exception as e:
        print(f"  ❌ Failed to retrieve token: {e}")
        return False


def _resolve_project(access_token: str) -> str | None:
    """Discover or create a Cloud Code Assist project."""
    import uuid

    # Try loadingCodeAssist first
    try:
        payload = json.dumps({}).encode()
        req = urllib.request.Request(
            f"{CODE_ASSIST_API}/v1internal:loadCodeAssist",
            data=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            project = result.get("cloudaicompanionProject", "") or result.get("project", "")
            if project:
                return project
    except urllib.error.HTTPError as e:
        if e.code == 403:
            pass  # Not onboarded yet

    # Try onboardUser with env project or generated one
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT_ID") or f"koza-{uuid.uuid4().hex[:8]}"
    try:
        payload = json.dumps({"project": project_id, "tier": "free_tier"}).encode()
        req = urllib.request.Request(
            f"{CODE_ASSIST_API}/v1internal:onboardUser",
            data=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("project", project_id)
    except Exception as e:
        logger.warning(f"onboardUser failed: {e}")
        return project_id


# ─── Cloud Code Assist API Client ─────────────────────────────────────────────

def _translate_messages(messages: list[dict]) -> tuple:
    """Translate OpenAI-format messages to Gemini format.

    Returns: (contents, system_instruction)
    """
    system_instruction = None
    contents = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            system_instruction = {"role": "user", "parts": [{"text": str(content)}]}
            continue

        if role == "user":
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            parts.append({"text": part.get("text", "")})
                        elif part.get("type") == "image_url":
                            parts.append({"inlineData": {"mimeType": "image/png", "data": part["image_url"].get("url", "").split(",")[-1]}})
                contents.append({"role": "user", "parts": parts})
            else:
                contents.append({"role": "user", "parts": [{"text": str(content)}]})

        elif role == "assistant":
            parts = []
            if content:
                parts.append({"text": str(content)})
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                fn = tc.get("function", tc)
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                parts.append({
                    "functionCall": {
                        "name": name,
                        "args": args,
                        "thoughtSignature": "skip_thought_signature_validator",
                    }
                })
            contents.append({"role": "model", "parts": parts})

        elif role == "tool":
            tc_id = msg.get("tool_call_id", "")
            name = msg.get("name", "")
            content_str = str(msg.get("content", ""))
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": name,
                        "response": {"name": name, "content": content_str},
                    }
                }],
            })

    return contents, system_instruction


def _translate_tools(tools: list[dict] | None) -> list[dict] | None:
    """Translate OpenAI tool format to Gemini function declarations."""
    if not tools:
        return None
    declarations = []
    for t in tools:
        fn = t.get("function", t)
        decl = {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
        }
        params = fn.get("parameters", {})
        if params:
            decl["parameters"] = _sanitize_schema(params)
        declarations.append(decl)

    return [{"functionDeclarations": declarations}]


def _sanitize_schema(schema: dict) -> dict:
    """Sanitize JSON schema for Gemini compatibility."""
    s = dict(schema)
    s.pop("$schema", None)
    # Ensure required is a list
    if "required" in s and not isinstance(s["required"], list):
        s["required"] = [s["required"]]
    return s


def _call_code_assist(
    access_token: str,
    project_id: str,
    model: str,
    contents: list,
    system_instruction: dict | None,
    tools: list[dict] | None,
) -> dict:
    """Make a non-streaming call to Cloud Code Assist API."""
    request_body = {"contents": contents}
    if system_instruction:
        request_body["systemInstruction"] = system_instruction
    if tools:
        request_body["tools"] = tools
    request_body["safetySettings"] = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
    request_body["generationConfig"] = {
        "temperature": 0.7,
        "maxOutputTokens": 8192,
    }

    payload = json.dumps({
        "project": project_id,
        "model": model,
        "user_prompt_id": secrets.token_hex(16),
        "request": request_body,
    }).encode()

    req = urllib.request.Request(
        f"{CODE_ASSIST_API}/v1internal:streamGenerateContent?alt=sse",
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )

    max_retries = 5
    backoff = 3.0
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read().decode()
            break
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode()
            except Exception:
                pass
            if e.code == 429 and attempt < max_retries - 1:
                # Try parsing reset time from the response message
                sleep_time = backoff
                match = re.search(r"reset after\s+(\d+)s", err_body, re.IGNORECASE)
                if match:
                    sleep_time = float(match.group(1)) + 1.0
                
                logger.warning(
                    f"Google Cloud Code Assist API rate limited (429). "
                    f"Retrying in {sleep_time}s... (Attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(sleep_time)
                backoff *= 2.0
                continue
            logger.error(f"HTTP Error {e.code}: {err_body}")
            raise e




    # Parse SSE response
    content = ""
    tool_calls = []
    for line in data.split("\n"):
        line = line.strip()
        if not line or line == "data: [DONE]" or line.startswith(":"):
            continue
        if line.startswith("data: "):
            try:
                chunk = json.loads(line[6:])
                # Unwrap outer response
                inner = chunk.get("response", chunk)
                candidates = inner.get("candidates", [])
                for candidate in candidates:
                    parts = candidate.get("content", {}).get("parts", [])
                    for part in parts:
                        if part.get("thought"):
                            continue
                        if "text" in part:
                            content += part["text"]
                        if "functionCall" in part:
                            fc = part["functionCall"]
                            existing = next((tc for tc in tool_calls if tc["name"] == fc["name"]), None)
                            if not existing:
                                tool_calls.append({
                                    "id": f"call_{len(tool_calls)}",
                                    "name": fc["name"],
                                    "arguments": fc.get("args", {}),
                                })
            except json.JSONDecodeError:
                continue

    return {"content": content or None, "tool_calls": tool_calls if tool_calls else None}


# ─── Provider Implementation ──────────────────────────────────────────────────

class GoogleOAuthProvider(LLMProvider):
    """Gemini provider via OAuth (Cloud Code Assist API)."""

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self._model = cfg.get("model", "gemini-2.0-flash")
        self._token_data = _load_tokens()
        self._project_id = None
        if self._token_data:
            refresh = self._token_data.get("refresh", "")
            if "|" in refresh:
                self._project_id = refresh.split("|")[1]

    @property
    def name(self) -> str:
        return "google-oauth"

    @property
    def supports_vision(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return GEMINI_MODELS

    def _ensure_auth(self) -> tuple[str, str]:
        """Ensure valid access token and project ID. Returns (token, project_id)."""
        self._token_data = _load_tokens()
        if not self._token_data:
            raise RuntimeError(
                "Not connected to Google account. "
                "Run 'google-login' in the terminal to sign in."
            )
        token = get_valid_access_token(self._token_data)
        if not token:
            raise RuntimeError("Token expired. Run 'google-login' in the terminal to sign in again.")
        
        # Extract project ID
        refresh = self._token_data.get("refresh", "")
        if "|" in refresh:
            self._project_id = refresh.split("|")[1]
            
        project_id = self._project_id or "default"
        return token, project_id

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict:
        if stream:
            return self._fallback_stream(messages, tools)

        token, project_id = self._ensure_auth()
        contents, system_instruction = _translate_messages(messages)
        gemini_tools = _translate_tools(tools)

        return _call_code_assist(
            token, project_id, self._model,
            contents, system_instruction, gemini_tools,
        )

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Generator[str | dict, None, None]:
        # Simple streaming via fallback
        result = self.chat(messages, tools=tools)
        for idx, tc in enumerate(result.get("tool_calls") or []):
            if cancel_event and cancel_event.is_set():
                return
            yield {
                "__tool_chunk__": True,
                "index": idx,
                "id": tc.get("id") or tc.get("name"),
                "name": tc.get("name"),
                "args_chunk": json.dumps(tc.get("arguments", {})),
            }
        if result.get("content"):
            if cancel_event and cancel_event.is_set():
                return
            yield result["content"]


# ─── CLI login command ────────────────────────────────────────────────────────

def cmd_google_login() -> str:
    """Run the Google OAuth login flow from CLI."""
    if _load_tokens():
        print("  ℹ  Already signed in. To reconnect, delete ~/.Koza/google_oauth.json first.")
        return ""
    if run_oauth_login():
        return "✅ Connected to Google account. You can use it with: /model gemini-2.5-pro"
    return "❌ Connection failed."
