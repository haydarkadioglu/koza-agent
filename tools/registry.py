"""Tool registry — ALL_TOOLS and ALL_HANDLERS assembled from all skill modules."""
from typing import Callable

# Runtime plugin tools accumulator — populated by plugin_manager
_PLUGIN_TOOLS: list[dict] = []
_PLUGIN_HANDLERS: dict[str, Callable] = {}


def register_plugin_tools(tools: list[dict], handlers: dict[str, Callable]) -> None:
    """Register tools and handlers from an external plugin.
    
    Called at runtime by plugin_manager.load_plugin(). After registration,
    ALL_TOOLS and ALL_HANDLERS are rebuilt to include the new entries.
    """
    global ALL_TOOLS, ALL_HANDLERS
    _PLUGIN_TOOLS.extend(_normalize(tools))
    _PLUGIN_HANDLERS.update(handlers)
    
    # Rebuild in-place to preserve reference bindings in other modules
    new_tools = _build_all_tools()
    ALL_TOOLS.clear()
    ALL_TOOLS.extend(new_tools)
    
    new_handlers = _build_all_handlers()
    ALL_HANDLERS.clear()
    ALL_HANDLERS.update(new_handlers)


def _build_all_tools() -> list[dict]:
    return _normalize(
        _STATIC_TOOLS + _PLUGIN_TOOLS
    )


def _build_all_handlers() -> dict[str, Callable]:
    h = dict(_STATIC_HANDLERS)
    h.update(_PLUGIN_HANDLERS)
    return h

# plugin_manager import removed to prevent circular import
from skills import (
    filesystem, shell, web, code_runner, system_info, kanban, cron,
    agents, browser_control, creative, datascience, devops, email_skill, finance,
    gaming, github_skill, mcp_skill, media, mlops, notes,
    productivity, research, security, smarthome, social,
    session_memory, messaging, shared_memory, working_memory,
    config_manager, image_gen, sync, skill_ecosystem, vision, delegation, repo_manager, code_tools,
    reminder, user_profile,
)


def _normalize(tools: list[dict]) -> list[dict]:
    """Ensure every tool is in OpenAI's nested format: {"type":"function","function":{...}}"""
    result = []
    for t in tools:
        if "function" in t:
            # Already nested — ensure 'type' field is present
            result.append({"type": "function", **t} if "type" not in t else t)
        elif "name" in t:
            # Flat format — wrap it
            result.append({"type": "function", "function": t})
        # Skip anything else (malformed)
    return result

_STATIC_TOOLS: list[dict] = _normalize(
    filesystem.TOOL_DEFINITIONS
    + shell.TOOL_DEFINITIONS
    + web.TOOL_DEFINITIONS
    + browser_control.TOOL_DEFINITIONS
    + code_runner.TOOL_DEFINITIONS
    + code_tools.TOOL_DEFINITIONS
    + email_skill.TOOL_DEFINITIONS
    + messaging.TOOL_DEFINITIONS
    + github_skill.TOOL_DEFINITIONS
    + repo_manager.TOOL_DEFINITIONS
    + cron.TOOL_DEFINITIONS
    + agents.TOOL_DEFINITIONS
    + delegation.TOOL_DEFINITIONS
    + shared_memory.TOOL_DEFINITIONS
    + working_memory.TOOL_DEFINITIONS
    + session_memory.TOOL_DEFINITIONS
    + config_manager.TOOL_DEFINITIONS
    + skill_ecosystem.TOOL_DEFINITIONS
    + system_info.TOOL_DEFINITIONS
    + kanban.TOOL_DEFINITIONS
    + creative.TOOL_DEFINITIONS
    + datascience.TOOL_DEFINITIONS
    + devops.TOOL_DEFINITIONS
    + finance.TOOL_DEFINITIONS
    + gaming.TOOL_DEFINITIONS
    + mcp_skill.TOOL_DEFINITIONS
    + media.TOOL_DEFINITIONS
    + mlops.TOOL_DEFINITIONS
    + notes.TOOL_DEFINITIONS
    + productivity.TOOL_DEFINITIONS
    + research.TOOL_DEFINITIONS
    + security.TOOL_DEFINITIONS
    + smarthome.TOOL_DEFINITIONS
    + social.TOOL_DEFINITIONS
    + image_gen.TOOL_DEFINITIONS
    + sync.TOOL_DEFINITIONS
    + vision.TOOL_DEFINITIONS
    + reminder.TOOL_DEFINITIONS
    + user_profile.TOOL_DEFINITIONS
)

_STATIC_HANDLERS: dict[str, Callable] = {
    **filesystem.HANDLERS,
    **shell.HANDLERS,
    **web.HANDLERS,
    **browser_control.HANDLERS,
    **code_runner.HANDLERS,
    **code_tools.HANDLERS,
    **email_skill.HANDLERS,
    **messaging.HANDLERS,
    **github_skill.HANDLERS,
    **repo_manager.HANDLERS,
    **cron.HANDLERS,
    **agents.HANDLERS,
    **delegation.HANDLERS,
    **shared_memory.HANDLERS,
    **working_memory.HANDLERS,
    **session_memory.HANDLERS,
    **config_manager.HANDLERS,
    **skill_ecosystem.HANDLERS,
    **system_info.HANDLERS,
    **kanban.HANDLERS,
    **creative.HANDLERS,
    **datascience.HANDLERS,
    **devops.HANDLERS,
    **finance.HANDLERS,
    **gaming.HANDLERS,
    **mcp_skill.HANDLERS,
    **media.HANDLERS,
    **mlops.HANDLERS,
    **notes.HANDLERS,
    **productivity.HANDLERS,
    **research.HANDLERS,
    **security.HANDLERS,
    **smarthome.HANDLERS,
    **social.HANDLERS,
    **image_gen.HANDLERS,
    **sync.HANDLERS,
    **vision.HANDLERS,
    **reminder.HANDLERS,
    **user_profile.HANDLERS,
}

STATIC_SKILL_MODULES = {
    "filesystem": filesystem,
    "shell": shell,
    "web": web,
    "browser_control": browser_control,
    "code_runner": code_runner,
    "system_info": system_info,
    "kanban": kanban,
    "cron": cron,
    "agents": agents,
    "creative": creative,
    "datascience": datascience,
    "devops": devops,
    "email_skill": email_skill,
    "finance": finance,
    "gaming": gaming,
    "github_skill": github_skill,
    "mcp_skill": mcp_skill,
    "media": media,
    "mlops": mlops,
    "notes": notes,
    "productivity": productivity,
    "research": research,
    "security": security,
    "smarthome": smarthome,
    "social": social,
    "session_memory": session_memory,
    "messaging": messaging,
    "shared_memory": shared_memory,
    "working_memory": working_memory,
    "config_manager": config_manager,
    "image_gen": image_gen,
    "sync": sync,
    "skill_ecosystem": skill_ecosystem,
    "vision": vision,
    "delegation": delegation,
    "repo_manager": repo_manager,
    "code_tools": code_tools,
    "reminder": reminder,
    "user_profile": user_profile,
}

_REGISTRY_INITIALIZED = True
ALL_TOOLS = _build_all_tools()
ALL_HANDLERS = _build_all_handlers()


def rebuild_registry(force: bool = False) -> None:
    """Rebuild the tool registry based on config and plugin state."""
    global ALL_TOOLS, ALL_HANDLERS, _STATIC_TOOLS, _STATIC_HANDLERS, _PLUGIN_TOOLS, _PLUGIN_HANDLERS, _REGISTRY_INITIALIZED
    if _REGISTRY_INITIALIZED and not force:
        return
    import sys
    
    # 1. Load config and determine disabled core skills
    from config import load_config
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    
    provider = cfg.get("provider", "ollama")
    is_local = provider in ("ollama", "lm_studio")
    if is_local:
        disabled = cfg.get("disabled_skills", [])
        # If the user has the legacy default list of all 20 disabled skills,
        # ignore it so they run smoothly out-of-the-box with dynamic tool selection.
        if len(disabled) >= 18:
            disabled = []
    else:
        disabled = []
    
    # 2. Rebuild static tools and handlers
    static_tools_list = []
    static_handlers_dict = {}
    
    for name, mod in STATIC_SKILL_MODULES.items():
        if name in disabled:
            continue
        static_tools_list.extend(getattr(mod, "TOOL_DEFINITIONS", []))
        static_handlers_dict.update(getattr(mod, "HANDLERS", {}))
        
    _STATIC_TOOLS.clear()
    _STATIC_TOOLS.extend(_normalize(static_tools_list))
    
    _STATIC_HANDLERS.clear()
    _STATIC_HANDLERS.update(static_handlers_dict)
    
    # 3. Reload plugin tools and handlers
    _PLUGIN_TOOLS.clear()
    _PLUGIN_HANDLERS.clear()
    
    try:
        from skills import plugin_manager
        # Clear plugin cache in plugin_manager
        if hasattr(plugin_manager, "_loaded_plugins"):
            plugin_manager._loaded_plugins.clear()
        # Call load_all_plugins with this module to register them
        plugin_manager.load_all_plugins(registry_module=sys.modules[__name__])
    except Exception:
        pass

    try:
        from skills.mcp_skill import load_dynamic_mcp_tools
        mcp_tools, mcp_handlers = load_dynamic_mcp_tools()
        _PLUGIN_TOOLS.extend(_normalize(mcp_tools))
        _PLUGIN_HANDLERS.update(mcp_handlers)
    except Exception:
        pass
    
    # 4. Update ALL_TOOLS and ALL_HANDLERS in-place
    new_tools = _normalize(_STATIC_TOOLS + _PLUGIN_TOOLS)
    ALL_TOOLS.clear()
    ALL_TOOLS.extend(new_tools)
    
    ALL_HANDLERS.clear()
    ALL_HANDLERS.update(_STATIC_HANDLERS)
    ALL_HANDLERS.update(_PLUGIN_HANDLERS)
    _REGISTRY_INITIALIZED = True
    
    # 5. Update core._TOOL_BY_NAME if core is imported
    if "core" in sys.modules:
        core_mod = sys.modules["core"]
        if hasattr(core_mod, "_TOOL_BY_NAME") and hasattr(core_mod, "_tool_name"):
            core_mod._TOOL_BY_NAME.clear()
            core_mod._TOOL_BY_NAME.update({core_mod._tool_name(t): t for t in ALL_TOOLS})


def coerce_tool_args(tool_name: str, args: dict) -> dict:
    """Coerce tool call arguments to match their JSON Schema types.
    LLMs frequently return numbers as strings ("42" instead of 42)
    and booleans as strings ("true" instead of True).
    """
    if not args or not isinstance(args, dict):
        return args

    schema = get_schema(tool_name)
    if not schema:
        return args

    properties = schema.get("parameters", {}).get("properties")
    if not properties:
        return args

    for key, value in list(args.items()):
        prop_schema = properties.get(key)
        if not prop_schema:
            del args[key]
            continue
        expected = prop_schema.get("type")

        # Wrap bare non-list values when the schema declares array
        if expected == "array" and value is not None and not isinstance(value, (list, tuple)):
            if isinstance(value, str):
                coerced = _coerce_value(value, expected, schema=prop_schema)
                if coerced is not value:
                    args[key] = coerced
                    continue
                if value.strip().startswith("["):
                    try:
                        import json as _json
                        args[key] = _json.loads(value)
                        continue
                    except Exception:
                        pass
                args[key] = [value]
                continue
            args[key] = [value]
            continue

        if not isinstance(value, str):
            continue
        if not expected and not _schema_allows_null(prop_schema):
            continue
        coerced = _coerce_value(value, expected, schema=prop_schema)
        if coerced is not value:
            args[key] = coerced

    return args


def get_schema(tool_name: str) -> dict | None:
    """Find a tool schema by name in ALL_TOOLS."""
    for t in ALL_TOOLS:
        if t.get("type") == "function":
            fn = t.get("function") or {}
            if fn.get("name") == tool_name:
                return fn
        elif t.get("name") == tool_name:
            return t
    return None


def _schema_allows_null(schema: dict | None) -> bool:
    if not isinstance(schema, dict):
        return False
    schema_type = schema.get("type")
    if schema_type == "null":
        return True
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    if schema.get("nullable") is True:
        return True
    for union_key in ("anyOf", "oneOf"):
        variants = schema.get(union_key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, dict) and variant.get("type") == "null":
                return True
    return False


def _coerce_value(value: str, expected_type, schema: dict | None = None):
    if _schema_allows_null(schema) and value.strip().lower() == "null":
        return None

    if isinstance(expected_type, list):
        for t in expected_type:
            result = _coerce_value(value, t, schema=schema)
            if result is not value:
                return result
        return value

    if expected_type in {"integer", "number"}:
        return _coerce_number(value, integer_only=(expected_type == "integer"))
    if expected_type == "boolean":
        return _coerce_boolean(value)
    if expected_type == "array":
        return _coerce_json(value, list)
    if expected_type == "object":
        return _coerce_json(value, dict)
    if expected_type == "null" and value.strip().lower() == "null":
        return None
    return value


def _coerce_number(value: str, integer_only: bool = False):
    try:
        f = float(value)
    except (ValueError, OverflowError):
        return value
    if f != f or f == float("inf") or f == float("-inf"):
        return value
    if f == int(f):
        return int(f)
    if integer_only:
        return value
    return f


def _coerce_boolean(value: str):
    low = value.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return value


def _coerce_json(value: str, expected_python_type: type):
    import json as _json
    try:
        parsed = _json.loads(value)
    except (ValueError, TypeError):
        return value
    if isinstance(parsed, expected_python_type):
        return parsed
    return value
