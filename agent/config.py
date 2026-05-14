"""Hermes Agent — Configuration management."""
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path.home() / ".hermes" / "config.yaml"


def default_config() -> dict:
    return {
        "provider": "ollama",
        "model": "",
        "providers": {
            "openai": {"api_key": "", "base_url": "https://api.openai.com/v1"},
            "anthropic": {"api_key": ""},
            "deepseek": {"api_key": "", "base_url": "https://api.deepseek.com/v1"},
            "gemini": {"api_key": ""},
            "ollama": {"base_url": "http://localhost:11434"},
        },
        "db_path": str(Path.home() / ".hermes" / "hermes.db"),
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
            else:
                cfg[key] = val
    # ENV overrides
    env_map = {
        "OPENAI_API_KEY": ("providers", "openai", "api_key"),
        "ANTHROPIC_API_KEY": ("providers", "anthropic", "api_key"),
        "DEEPSEEK_API_KEY": ("providers", "deepseek", "api_key"),
        "GEMINI_API_KEY": ("providers", "gemini", "api_key"),
    }
    for env_key, path in env_map.items():
        val = os.getenv(env_key)
        if val:
            cfg[path[0]][path[1]][path[2]] = val
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True)


def config_exists() -> bool:
    return CONFIG_PATH.exists()
