"""Koza Agent — Configuration management."""
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()
# Also load from central Koza configuration directory (.env holds credentials)
load_dotenv(Path.home() / ".Koza" / ".env")

CONFIG_PATH = Path.home() / ".Koza" / "config.yaml"


def default_config() -> dict:
    return {
        "provider": "ollama",
        "model": "",
        "fallback_provider": "",
        "fallback_model": "",
        "providers": {
            "openai":     {"api_key": "", "base_url": "https://api.openai.com/v1"},
            "anthropic":  {"api_key": ""},
            "anthropic-oauth": {},
            "deepseek":   {"api_key": "", "base_url": "https://api.deepseek.com/v1"},
            "gemini":     {"api_key": "", "auth": "api_key"},
            "ollama":     {"base_url": "http://localhost:11434"},
            "antigravity": {"api_key": "", "base_url": "http://127.0.0.1:8045/v1"},
            "github":     {"token": ""},
            "kimi":       {"api_key": "", "base_url": "https://api.moonshot.cn/v1"},
            "minimax":    {"api_key": "", "base_url": "https://api.minimax.io/v1"},
            "zai":        {"api_key": "", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
            "deepgram":   {"api_key": ""},
            "elevenlabs": {"api_key": ""},
            "portal":     {"api_key": "", "base_url": "https://api.nous.portal/v1"},
        },
        "messaging": {
            "telegram":  {"token": "", "chat_id": ""},
            "discord":   {"webhook_url": "", "token": "", "channel_id": ""},
            "whatsapp":  {"account_sid": "", "auth_token": "", "from": "whatsapp:+14155238886", "to": ""},
            "twilio": {
                "account_sid": "",
                "auth_token":  "",
                "from_number": "",
                "wa_from":     "",
                "wa_to":       "",
            },
        },
        "social": {
            "twitter_bearer_token": "",
            "mastodon_token": "",
            "mastodon_instance": "https://mastodon.social",
            "bluesky_handle": "",
            "bluesky_app_password": "",
            "linkedin_token": "",
            "linkedin_person_urn": "",
            "threads_user_id": "",
            "threads_token": "",
            "instagram_user_id": "",
            "instagram_token": "",
        },
        "vault_path":      str(Path.home() / "notes"),
        "db_path":         str(Path.home() / ".Koza" / "koza.db"),
        "workspace_path":  str(Path.home() / ".Koza" / "workspace"),
        "multi_host": {
            "mode":                   "single",   # single | master | client | demo
            "sync_port":              7420,
            "sync_token":             "",         # auto-generated on master setup
            "master_url":             "",         # http://master-ip:7420  (client only)
            "sync_on_startup":        True,
            "sync_on_exit":           True,
            "sync_interval_minutes":  5,          # periodic background sync (0 = disabled)
            "host_name":              "",         # optional display name
            "last_sync_at":           0.0,        # unix timestamp of last successful sync
        },
        "voice": {
            "enabled": False,
            "stt": {
                "provider": "local_whisper",  # local_whisper | openai | gemini | deepgram | skip
                "model": "base",              # provider-specific model id
                "language": "",               # empty = auto-detect
            },
            "tts": {
                "provider": "system",         # system | kokoro | openai | gemini | elevenlabs | skip
                "model": "",                  # provider-specific model id
                "voice": "af_sky",            # provider-specific voice id/name
            },
            "input_device": None,
            "output_device": None,
        },
        "coding_mode": {
            "max_retries": 3,       # max retry count when tests fail
            "auto_test":   True,    # run Test Engineer after every coding task
        },
        "tool_approval": True,      # False = auto-approve tools; True = ask for non-safe tools
        "ui": {
            "default": "plain",          # plain | tui
            "refresh_interval_ms": 1500,
        },
        "self_improvement": {
            "enabled": True,
        },
        "language": "en",
        "disabled_skills": [],
    }


def load_config() -> dict:
    cfg = default_config()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        # Deep merge providers
        for key, val in loaded.items():
            if key == "providers" and isinstance(val, dict):
                for p, pval in val.items():
                    cfg["providers"].setdefault(p, {}).update(pval)
            elif key == "multi_host" and isinstance(val, dict):
                cfg["multi_host"].update(val)
            elif key == "ui" and isinstance(val, dict):
                cfg["ui"].update(val)
            elif key == "self_improvement" and isinstance(val, dict):
                cfg["self_improvement"].update(val)
            elif key == "voice" and isinstance(val, dict):
                default_stt = dict(cfg["voice"].get("stt", {}))
                default_tts = dict(cfg["voice"].get("tts", {}))
                cfg["voice"].update(val)
                if isinstance(val.get("stt"), dict):
                    default_stt.update(val["stt"])
                    cfg["voice"]["stt"] = default_stt
                if isinstance(val.get("tts"), dict):
                    default_tts.update(val["tts"])
                    cfg["voice"]["tts"] = default_tts
            else:
                cfg[key] = val
    # ENV overrides
    env_map = {
        "OPENAI_API_KEY":      ("providers", "openai", "api_key"),
        "ANTHROPIC_API_KEY":   ("providers", "anthropic", "api_key"),
        "DEEPSEEK_API_KEY":    ("providers", "deepseek", "api_key"),
        "GEMINI_API_KEY":      ("providers", "gemini", "api_key"),
        "DEEPGRAM_API_KEY":    ("providers", "deepgram", "api_key"),
        "ELEVENLABS_API_KEY":  ("providers", "elevenlabs", "api_key"),
        "PORTAL_API_KEY":      ("providers", "portal", "api_key"),
        "GITHUB_TOKEN":        ("providers", "github", "token"),
        "TELEGRAM_TOKEN":      ("messaging", "telegram", "token"),
        "TELEGRAM_CHAT_ID":    ("messaging", "telegram", "chat_id"),
        "DISCORD_WEBHOOK_URL": ("messaging", "discord", "webhook_url"),
        "DISCORD_TOKEN":       ("messaging", "discord", "token"),
        "DISCORD_CHANNEL_ID":  ("messaging", "discord", "channel_id"),
        "TWILIO_ACCOUNT_SID":  ("messaging", "twilio", "account_sid"),
        "TWILIO_AUTH_TOKEN":   ("messaging", "twilio", "auth_token"),
        "TWILIO_FROM_NUMBER":  ("messaging", "twilio", "from_number"),
        "TWILIO_WA_FROM":      ("messaging", "twilio", "wa_from"),
        "TWILIO_WA_TO":        ("messaging", "twilio", "wa_to"),
        "WHATSAPP_FROM":       ("messaging", "whatsapp", "from"),
        "WHATSAPP_TO":         ("messaging", "whatsapp", "to"),
        # Email settings from env/credentials
        "EMAIL_USERNAME":      ("email", "username"),
        "EMAIL_PASSWORD":      ("email", "password"),
        "SMTP_HOST":           ("email", "smtp_host"),
        "SMTP_PORT":           ("email", "smtp_port"),
        "IMAP_HOST":           ("email", "imap_host"),
    }
    for env_key, path in env_map.items():
        val = os.getenv(env_key)
        if val:
            curr = cfg
            for part in path[:-1]:
                curr = curr.setdefault(part, {})
            # Special case for integer cast
            if path[-1] == "smtp_port" and val.isdigit():
                curr[path[-1]] = int(val)
            else:
                curr[path[-1]] = val
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True)


def config_exists() -> bool:
    return CONFIG_PATH.exists()
