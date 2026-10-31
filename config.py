"""Koza Agent — Configuration management."""
import copy
import os
import threading
from pathlib import Path

import yaml
from dotenv import load_dotenv

from utils.secure_files import atomic_write_private, harden_permissions

load_dotenv()
# Also load from central Koza configuration directory (.env holds credentials)
load_dotenv(Path.home() / ".Koza" / ".env")

CONFIG_PATH = Path.home() / ".Koza" / "config.yaml"

# Parsed file contents as ((path, mtime_ns, size), parsed). yaml.safe_load is what
# makes load_config() expensive; the merge on top of it stays per-call.
_yaml_cache: tuple[tuple, dict] | None = None
_yaml_cache_hits = 0
_yaml_cache_misses = 0
_yaml_cache_lock = threading.Lock()


def default_config() -> dict:
    return {
        "provider": "ollama",
        "model": "",
        "fallback_provider": "",
        "fallback_model": "",
        "key_rotation": {
            "auth_disables_key": True,
            "billing_cooldown_seconds": 1800,
            "rate_limit_cooldown_seconds": 60,
            "default_cooldown_seconds": 300,
        },
        # K-27: usage/cost accounting. "prices" overrides map a model id to
        # USD per 1M tokens: {"input": 3.0, "output": 15.0, "cache_read": 0.3,
        # "cache_write": 3.75} or a two-number list [input, output].
        "cost_tracking": {
            "enabled": True,
            "currency": "USD",
            "prices": {},   # optional per-model overrides, USD per 1M tokens
        },
        "providers": {
            "openai":      {"api_key": "", "base_url": "https://api.openai.com/v1"},
            "anthropic":   {"api_key": "", "base_url": "https://api.anthropic.com"},
            "anthropic-oauth": {},
            "deepseek":    {"api_key": "", "base_url": "https://api.deepseek.com/v1"},
            "gemini":      {"api_key": "", "auth": "api_key", "base_url": "https://generativelanguage.googleapis.com"},
            "ollama":      {"base_url": "http://localhost:11434"},
            "antigravity": {"api_key": "", "base_url": "http://127.0.0.1:8045/v1"},
            "github":      {"token": "", "base_url": "https://models.inference.ai.azure.com"},
            "kimi":        {"api_key": "", "base_url": "https://api.moonshot.cn/v1"},
            "minimax":     {"api_key": "", "base_url": "https://api.minimax.io/v1"},
            "zai":         {"api_key": "", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
            "deepgram":    {"api_key": ""},
            "elevenlabs":  {"api_key": ""},
            "portal":      {"api_key": "", "base_url": "https://api.nous.portal/v1"},
            "groq":        {"api_key": "", "base_url": "https://api.groq.com/openai/v1"},
            "openrouter":  {"api_key": "", "base_url": "https://openrouter.ai/api/v1"},
            "lm_studio":   {"base_url": "http://localhost:1234/v1"},
        },
        "messaging": {
            "telegram":  {
                "token": "", "chat_id": "",
                # Voice notes arriving on Telegram are transcribed with the configured
                # voice.stt provider before the agent sees them.
                "voice_notes": {"enabled": True, "max_seconds": 300, "timeout_seconds": 120},
            },
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
        "tool_timeout_seconds": 600,  # per-call deadline for a tool call (0 = no deadline)
        "tool_batching": {          # run independent tool calls in one batch concurrently
            "enabled": True,        # False = every batch runs sequentially, in call order
            "path_scoped": True,    # let read/write calls join a parallel run unless their paths conflict
            "parallel_safe_tools": [],   # extra tool names admitted as stateless/parallel-safe
            "never_parallel_tools": [],  # extra tool names that must always run alone
        },
        "security": {
            # Wrap results of network-facing tools in an untrusted-data block so fetched
            # pages and MCP servers cannot issue instructions to the model.
            "wrap_untrusted_tool_results": True,
            "untrusted_tool_names": ["web_search", "fetch_url", "browser_task",
                                     "mcp_call_tool", "mcp_list_tools", "webhook_listen"],
            "untrusted_tool_prefixes": ["browser_", "mcp_"],
            "untrusted_min_chars": 32,
        },
        "tool_loop_guardrails": {   # warn -> block -> halt escalation for looping tool calls
            "warnings_enabled": True,          # append loop warnings to tool results
            "hard_stop_enabled": True,         # False = warn/block only, never end the turn
            "exact_failure_warn_after": 2,     # identical failing call, warn from here
            "exact_failure_block_after": 4,    # identical failing call, refuse from here
            "max_blocks_before_halt": 2,       # a refused call reissued this often ends the turn
            "same_tool_failure_warn_after": 3,   # failures of one tool (any arguments)
            "same_tool_failure_halt_after": 8,   # ... ends the turn from here
            "no_progress_warn_after": 3,        # identical result from a read-only call
            "no_progress_block_after": 5,       # ... refuse from here
        },
        "ui": {
            "default": "plain",          # plain | tui
            "refresh_interval_ms": 1500,
        },
        "context_compression": {    # summarise old turns when the context window fills
            "enabled": True,        # False = never auto-compress (manual /compress still works)
            "threshold_percent": 0.50,  # compress at this fraction of the model context window
            "summary_model": "",    # model for the summary; "" = reuse the main model
            "timeout_seconds": 60,  # deadline for one summarisation call
        },
        "context_overflow": {      # what to do when the provider rejects a request as too large
            "enabled": True,       # False = surface the provider error and end the turn
            "max_retries": 1,      # how many shortened retries before giving up
            "keep_recent_messages": 12,  # verbatim tail preserved when older turns are dropped
        },
        "clarify": {                 # mid-turn structured questions to the user
            "enabled": True,         # False = ask_user always reports "undelivered"
            "timeout_seconds": 300,  # how long one ask_user call waits for the answer
            "allow_other": True,     # surfaces may offer a free-text "Other" answer
        },
        "self_improvement": {
            "enabled": True,
        },
        "router": {
            "cache_size": 128,  # remembered LLM routing decisions (0 = no caching)
        },
        "language": "en",
        "disabled_skills": [],
    }


def _load_yaml_file() -> dict:
    """Return a private copy of the parsed config file, {} if it cannot be parsed."""
    global _yaml_cache, _yaml_cache_hits, _yaml_cache_misses
    try:
        st = CONFIG_PATH.stat()
        key = (str(CONFIG_PATH), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    with _yaml_cache_lock:
        if key is not None and _yaml_cache is not None and _yaml_cache[0] == key:
            _yaml_cache_hits += 1
            return copy.deepcopy(_yaml_cache[1])
        _yaml_cache_misses += 1

    harden_permissions(CONFIG_PATH, 0o600)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Warning: Failed to load config.yaml due to syntax error: {e}")
        print(f"A backup of the broken config will be saved to config.yaml.broken")
        try:
            import shutil
            shutil.copy(CONFIG_PATH, str(CONFIG_PATH) + ".broken")
        except Exception:
            pass
        return {}

    if key is not None:
        with _yaml_cache_lock:
            _yaml_cache = (key, loaded)
    return copy.deepcopy(loaded)


def config_cache_info() -> dict:
    """Return the parsed-config cache counters."""
    with _yaml_cache_lock:
        return {"hits": _yaml_cache_hits, "misses": _yaml_cache_misses}


def clear_config_cache() -> None:
    """Drop the parsed config and reset the cache counters."""
    global _yaml_cache, _yaml_cache_hits, _yaml_cache_misses
    with _yaml_cache_lock:
        _yaml_cache = None
        _yaml_cache_hits = 0
        _yaml_cache_misses = 0


def load_config() -> dict:
    cfg = default_config()
    if CONFIG_PATH.exists():
        loaded = _load_yaml_file()

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
    global _yaml_cache
    atomic_write_private(
        CONFIG_PATH,
        yaml.safe_dump(cfg, default_flow_style=False, allow_unicode=True),
    )
    # A coarse filesystem mtime could hide this write from the stat key.
    with _yaml_cache_lock:
        _yaml_cache = None


def config_exists() -> bool:
    return CONFIG_PATH.exists()
