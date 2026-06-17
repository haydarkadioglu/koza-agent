"""Config Manager skill — agent can read/write any config value by dot-path."""
import re


def _deep_get(d: dict, path: str):
    """Get nested value by dot-path. e.g. 'messaging.telegram.token'"""
    keys = path.strip().split(".")
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _deep_set(d: dict, path: str, value):
    """Set nested value by dot-path, creating intermediate dicts as needed."""
    keys = path.strip().split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def _mask(val):
    """Mask sensitive-looking values."""
    if not isinstance(val, str) or len(val) < 8:
        return val
    return val[:4] + "****" + val[-2:]


def _flatten(d: dict, prefix: str = "") -> dict:
    """Flatten nested dict to dot-path keys."""
    result = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten(v, key))
        else:
            result[key] = v
    return result


SENSITIVE_KEYS = {
    "token", "api_key", "key", "secret", "password",
    "auth_token", "app_password", "webhook_url",
}


def _is_sensitive(path: str) -> bool:
    last = path.split(".")[-1].lower()
    return any(s in last for s in SENSITIVE_KEYS)


def handle_get_config(path: str = "", show_all: bool = False) -> str:
    from config import load_config
    cfg = load_config()

    if not path:
        flat = _flatten(cfg)
        lines = []
        for k, v in sorted(flat.items()):
            if v == "" or v is None:
                continue
            display = _mask(str(v)) if _is_sensitive(k) else str(v)
            lines.append(f"{k}: {display}")
        if not lines:
            return "Config boş veya tüm değerler varsayılan."
        return "Mevcut config ayarları (dolu olanlar):\n" + "\n".join(lines)

    val = _deep_get(cfg, path)
    if val is None:
        return f"'{path}' bulunamadı."
    display = _mask(str(val)) if _is_sensitive(path) else str(val)
    return f"{path} = {display}"


def handle_set_config(path: str, value: str) -> str:
    from config import load_config, save_config
    cfg = load_config()

    # Type coercion: int, bool, or string
    coerced = value
    if value.lower() in ("true", "yes", "evet"):
        coerced = True
    elif value.lower() in ("false", "no", "hayır"):
        coerced = False
    elif re.match(r"^\d+$", value):
        coerced = int(value)

    _deep_set(cfg, path, coerced)
    save_config(cfg)

    display = _mask(str(coerced)) if _is_sensitive(path) else str(coerced)
    return f"✓ {path} = {display} olarak kaydedildi."


def handle_delete_config(path: str) -> str:
    from config import load_config, save_config
    cfg = load_config()

    keys = path.strip().split(".")
    cur = cfg
    for k in keys[:-1]:
        if not isinstance(cur, dict) or k not in cur:
            return f"'{path}' bulunamadı."
        cur = cur[k]

    last = keys[-1]
    if last not in cur:
        return f"'{path}' bulunamadı."
    del cur[last]
    save_config(cfg)
    return f"✓ '{path}' silindi."


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_config",
            "description": (
                "Read Koza config. Provide a dot-path like 'messaging.telegram.token' "
                "to read a specific value, or leave empty to list all non-empty settings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Dot-path key, e.g. 'provider', 'messaging.telegram.token', 'providers.deepseek.api_key'. Leave empty to list all.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_config",
            "description": (
                "Save a value to Koza config. Use dot-path keys. Examples: "
                "'messaging.telegram.token' = 'xxx', 'provider' = 'deepseek', "
                "'providers.openai.api_key' = 'sk-...'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Dot-path key to set.",
                    },
                    "value": {
                        "type": "string",
                        "description": "Value to store (string, will auto-coerce to int/bool if appropriate).",
                    },
                },
                "required": ["path", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_config",
            "description": "Remove a key from Koza config by dot-path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Dot-path key to delete.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_enable",
            "description": "Enable a core Koza skill (e.g. email_skill, media, etc.) by removing it from disabled_skills list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the skill to enable (e.g. email_skill)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_disable",
            "description": "Disable a core Koza skill by adding it to disabled_skills list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the skill to disable"},
                },
                "required": ["name"],
            },
        },
    },
]

def handle_skill_enable(name: str) -> str:
    from config import load_config, save_config
    cfg = load_config()
    disabled = cfg.get("disabled_skills", [])
    if not isinstance(disabled, list):
        disabled = []
    if name in disabled:
        disabled.remove(name)
        cfg["disabled_skills"] = disabled
        save_config(cfg)
        from tools.registry import rebuild_registry
        rebuild_registry(force=True)
        return f"✅ Skill '{name}' enabled successfully and registry rebuilt."
    return f"ℹ️ Skill '{name}' is already enabled."

def handle_skill_disable(name: str) -> str:
    from config import load_config, save_config
    cfg = load_config()
    disabled = cfg.get("disabled_skills", [])
    if not isinstance(disabled, list):
        disabled = []
    if name not in disabled:
        disabled.append(name)
        cfg["disabled_skills"] = disabled
        save_config(cfg)
        from tools.registry import rebuild_registry
        rebuild_registry(force=True)
        return f"⏹️ Skill '{name}' disabled successfully."
    return f"ℹ️ Skill '{name}' is already disabled."

HANDLERS = {
    "get_config":    lambda **kw: handle_get_config(kw.get("path", "")),
    "set_config":    lambda **kw: handle_set_config(kw["path"], kw["value"]),
    "delete_config": lambda **kw: handle_delete_config(kw["path"]),
    "skill_enable":  lambda **kw: handle_skill_enable(kw["name"]),
    "skill_disable": lambda **kw: handle_skill_disable(kw["name"]),
}
