"""Secret handling for API configuration.

Set ``api_server.require_token: true`` in ``~/.Koza/config.yaml`` to require
the local API token on every mutating request. The token is read from
``KOZA_API_TOKEN`` or stored in ``~/.Koza/api_token``.
"""

import copy
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

SECRET_KEYS: frozenset[str] = frozenset({
    "api_key",
    "apikey",
    "token",
    "auth_token",
    "bot_token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "password",
    "app_password",
    "private_key",
    "webhook_url",
    "key",
    "authorization",
})
SECRET_MASK = "***redacted***"
API_TOKEN_ENV = "KOZA_API_TOKEN"


def redact_config(cfg: dict) -> dict:
    """Return a deep-copied config with secret values replaced by a mask."""
    redacted = copy.deepcopy(cfg)

    def redact(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and key.lower() in SECRET_KEYS:
                    value[key] = SECRET_MASK
                else:
                    redact(item)
        elif isinstance(value, list):
            for item in value:
                redact(item)

    redact(redacted)
    return redacted


def strip_masked(cfg: dict) -> dict:
    """Return a deep-copied config with masked leaves and empty parents removed."""
    stripped = copy.deepcopy(cfg)

    def strip(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if item == SECRET_MASK:
                    continue
                cleaned = strip(item)
                if cleaned is not None:
                    result[key] = cleaned
            return result or None
        if isinstance(value, list):
            result = []
            for item in value:
                if item == SECRET_MASK:
                    continue
                cleaned = strip(item)
                if cleaned is not None:
                    result.append(cleaned)
            return result or None
        return value

    result = strip(stripped)
    return result if result is not None else {}


def token_path() -> Path:
    """Return the per-user path used to persist the local API token."""
    return Path.home() / ".Koza" / "api_token"


def load_or_create_token() -> str:
    """Load the API token from the environment or a private file, creating it if needed."""
    env_token = os.getenv(API_TOKEN_ENV)
    if env_token is not None:
        return env_token

    path = token_path()
    try:
        stored_token = path.read_text(encoding="utf-8").strip()
        if stored_token:
            return stored_token
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError) as exc:
        logger.warning("Could not read the local API token file: %s", exc)

    token = secrets.token_urlsafe(32)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError as exc:
        logger.warning("Could not persist the local API token file: %s", exc)
    return token
