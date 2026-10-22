from copy import deepcopy

from fastapi.testclient import TestClient

import api_server
from utils.config_secrets import SECRET_MASK, redact_config, strip_masked


def test_redact_config_masks_secrets_without_mutating_input():
    config = {
        "model": "gpt-4o",
        "provider": "openai",
        "base_url": "https://api.example.com",
        "max_tokens": 2048,
        "providers": {"openai": {"api_key": "sk-live-key"}},
        "messaging": {"telegram": {"token": "telegram-secret"}},
        "email": {"password": "email-secret"},
        "mcp": {
            "servers": {
                "x": {"headers": {"Authorization": "bearer-secret"}, "env": {"TOKEN": "env-secret"}}
            }
        },
        "token_count": 12,
        "key_bindings": ["ctrl+c"],
    }
    original = deepcopy(config)

    redacted = redact_config(config)

    assert redacted["providers"]["openai"]["api_key"] == SECRET_MASK
    assert redacted["messaging"]["telegram"]["token"] == SECRET_MASK
    assert redacted["email"]["password"] == SECRET_MASK
    assert redacted["mcp"]["servers"]["x"]["headers"]["Authorization"] == SECRET_MASK
    assert redacted["mcp"]["servers"]["x"]["env"]["TOKEN"] == SECRET_MASK
    assert redacted["model"] == "gpt-4o"
    assert redacted["provider"] == "openai"
    assert redacted["base_url"] == "https://api.example.com"
    assert redacted["max_tokens"] == 2048
    assert redacted["token_count"] == 12
    assert redacted["key_bindings"] == ["ctrl+c"]
    assert config == original


def test_strip_masked_removes_masked_leaves_and_empty_parents():
    config = {
        "providers": {
            "openai": {"api_key": SECRET_MASK, "base_url": "https://api.example.com"},
            "anthropic": {"api_key": SECRET_MASK},
        },
        "items": [SECRET_MASK, "visible", {"token": SECRET_MASK}],
        "real_secret": "still-present",
    }
    original = deepcopy(config)

    stripped = strip_masked(config)

    assert stripped == {
        "providers": {"openai": {"base_url": "https://api.example.com"}},
        "items": ["visible"],
        "real_secret": "still-present",
    }
    assert config == original


def test_get_config_never_returns_real_api_keys(monkeypatch):
    monkeypatch.setattr(
        api_server,
        "load_config",
        lambda: {"providers": {"openai": {"api_key": "sk-live-SECRET"}}},
    )

    response = TestClient(api_server.app, base_url="http://127.0.0.1:8000").get("/api/config")

    assert response.status_code == 200
    assert "sk-live-SECRET" not in response.text
    assert response.json()["providers"]["openai"]["api_key"] == SECRET_MASK


def test_post_config_does_not_overwrite_real_key_with_mask(monkeypatch):
    config = {"providers": {"openai": {"api_key": "sk-live-SECRET"}}}
    saved = {}
    monkeypatch.setattr(api_server, "load_config", lambda: deepcopy(config))
    monkeypatch.setattr(api_server, "save_config", lambda value: saved.update(deepcopy(value)))

    response = TestClient(api_server.app, base_url="http://127.0.0.1:8000").post(
        "/api/config",
        json={"providers": {"openai": {"api_key": SECRET_MASK}}},
    )

    assert response.status_code == 200
    assert saved["providers"]["openai"]["api_key"] == "sk-live-SECRET"
    assert SECRET_MASK not in str(saved)


def test_host_guard_rejects_untrusted_host(monkeypatch):
    monkeypatch.setattr(api_server, "load_config", lambda: {})
    monkeypatch.setattr("cli.update_cmd._check_latest_version", lambda: ("v1", "v1"))
    client = TestClient(api_server.app, base_url="http://127.0.0.1:8000")

    rejected = client.get("/api/version", headers={"Host": "evil.example"})
    accepted = client.get("/api/version", headers={"Host": "127.0.0.1:8000"})

    assert rejected.status_code == 403
    assert accepted.status_code != 403


def test_cross_origin_mutation_is_rejected(monkeypatch):
    monkeypatch.setattr(api_server, "load_config", lambda: {})
    monkeypatch.setattr(api_server, "save_config", lambda _value: None)
    client = TestClient(api_server.app, base_url="http://127.0.0.1:8000")

    rejected = client.post("/api/config", headers={"Origin": "https://evil.example"}, json={})
    accepted = client.post("/api/config", headers={"Origin": "http://localhost:1420"}, json={})

    assert rejected.status_code == 403
    assert accepted.status_code != 403


def test_token_mode_requires_matching_token(monkeypatch):
    monkeypatch.setattr(api_server, "load_config", lambda: {"api_server": {"require_token": True}})
    monkeypatch.setattr(api_server, "save_config", lambda _value: None)
    monkeypatch.setattr(api_server, "load_or_create_token", lambda: "fixed-test-token")
    client = TestClient(api_server.app, base_url="http://127.0.0.1:8000")

    missing = client.post("/api/config", json={})
    wrong = client.post("/api/config", headers={"X-Koza-Token": "wrong"}, json={})
    valid = client.post("/api/config", headers={"X-Koza-Token": "fixed-test-token"}, json={})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert valid.status_code != 401
