"""
Plugin Loader — auto-discovers and dynamically loads plugins from ~/.Koza/plugins/.

Each plugin is a directory under ~/.Koza/plugins/<plugin-name>/ with:
  manifest.json  — metadata: name, version, description, author, requires
  plugin.py      — exports TOOL_DEFINITIONS (list[dict]) + HANDLERS (dict[str, callable])

At startup, `load_all_plugins()` scans the plugins directory, imports each plugin,
and registers its tools into the global tool registry via `registry.register_plugin_tools()`.

Enable/disable state is tracked in ~/.Koza/plugins/registry.json.
"""
import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PLUGINS_DIR: Path = Path.home() / ".Koza" / "plugins"
_REGISTRY_FILE: Path = _PLUGINS_DIR / "registry.json"

# Cache of loaded plugin info (name -> {manifest, tools, handlers, enabled})
_loaded_plugins: dict[str, dict[str, Any]] = {}


def _ensure_dirs() -> None:
    _PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    if not _REGISTRY_FILE.exists():
        _REGISTRY_FILE.write_text(json.dumps({}), encoding="utf-8")


def _load_registry_state() -> dict[str, bool]:
    """Load plugin enable/disable state. Returns {plugin_name: enabled}."""
    _ensure_dirs()
    try:
        return json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save_registry_state(state: dict[str, bool]) -> None:
    """Persist plugin enable/disable state."""
    _ensure_dirs()
    _REGISTRY_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _discover_plugin_dirs() -> list[Path]:
    """Return paths to all plugin directories (folders with manifest.json)."""
    _ensure_dirs()
    if not _PLUGINS_DIR.exists():
        return []
    return [
        d for d in _PLUGINS_DIR.iterdir()
        if d.is_dir() and (d / "manifest.json").exists()
    ]


def _load_manifest(plugin_dir: Path) -> dict | None:
    """Load and validate a plugin's manifest.json."""
    manifest_path = plugin_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if "name" not in manifest:
            logger.warning(f"Plugin {plugin_dir.name}: manifest missing 'name' field")
            return None
        return manifest
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Plugin {plugin_dir.name}: cannot read manifest: {e}")
        return None


def _import_plugin_module(plugin_dir: Path) -> object | None:
    """Dynamically import a plugin's plugin.py module."""
    plugin_py = plugin_dir / "plugin.py"
    if not plugin_py.exists():
        logger.warning(f"Plugin {plugin_dir.name}: missing plugin.py")
        return None

    try:
        # Use the directory name as the module name for uniqueness
        module_name = f"koza_plugin_{plugin_dir.name}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_py)
        if spec is None or spec.loader is None:
            logger.warning(f"Plugin {plugin_dir.name}: cannot load spec for plugin.py")
            return None
        module = importlib.util.module_from_spec(spec)
        # Add plugin dir to sys.path so the plugin can do relative imports
        sys.path.insert(0, str(plugin_dir))
        try:
            spec.loader.exec_module(module)
        finally:
            if sys.path and sys.path[0] == str(plugin_dir):
                sys.path.pop(0)
        return module
    except Exception as e:
        logger.error(f"Plugin {plugin_dir.name}: import failed: {e}", exc_info=True)
        return None


def _validate_tools(tools: Any) -> list[dict]:
    """Validate that tools is a list of dicts with 'name' or 'function.name'."""
    if not isinstance(tools, list):
        return []
    valid = []
    for t in tools:
        if isinstance(t, dict):
            if "name" in t or ("function" in t and isinstance(t["function"], dict) and "name" in t["function"]):
                valid.append(t)
    return valid


def _validate_handlers(handlers: Any) -> dict[str, Any]:
    """Validate that handlers is a dict of name -> callable."""
    if not isinstance(handlers, dict):
        return {}
    return {
        k: v for k, v in handlers.items()
        if callable(v)
    }


# ─── Public API ──────────────────────────────────────────────────────────────

def discover_plugins() -> list[dict]:
    """Scan the plugins directory and return metadata for all found plugins.
    
    Returns list of dicts: {name, version, description, author, enabled, tool_count}
    """
    _ensure_dirs()
    state = _load_registry_state()
    results = []

    for plugin_dir in _discover_plugin_dirs():
        manifest = _load_manifest(plugin_dir)
        if manifest is None:
            continue

        name = manifest["name"]
        # Quick tool count without full import
        tool_count = 0
        plugin_py = plugin_dir / "plugin.py"
        if plugin_py.exists():
            try:
                # Count tool definitions by scanning the file for TOOL_DEFINITIONS
                content = plugin_py.read_text(encoding="utf-8")
                # Simple heuristic: count 'name' keys in TOOL_DEFINITIONS
                import ast
                try:
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Assign):
                            for target in node.targets:
                                if isinstance(target, ast.Name) and target.id == "TOOL_DEFINITIONS":
                                    if isinstance(node.value, ast.List):
                                        tool_count = len(node.value.elts)
                except SyntaxError:
                    pass
            except Exception:
                pass

        results.append({
            "name": name,
            "version": manifest.get("version", "0.1.0"),
            "description": manifest.get("description", ""),
            "author": manifest.get("author", ""),
            "enabled": state.get(name, True),  # Default: enabled
            "tool_count": tool_count,
            "path": str(plugin_dir),
        })

    return results


def load_plugin(plugin_name: str, registry_module=None) -> bool:
    """Load a single plugin by name and register its tools.
    
    Args:
        plugin_name: Name of the plugin (directory name under plugins/)
        registry_module: The registry module to call register_plugin_tools on.
                         If None, imports from tools.registry.
    
    Returns:
        True if loaded successfully, False otherwise.
    """
    plugin_dir = _PLUGINS_DIR / plugin_name
    if not plugin_dir.exists() or not (plugin_dir / "manifest.json").exists():
        logger.error(f"Plugin '{plugin_name}' not found at {plugin_dir}")
        return False

    manifest = _load_manifest(plugin_dir)
    if manifest is None:
        return False

    # Check against actual manifest name
    actual_name = manifest.get("name", plugin_dir.name)

    module = _import_plugin_module(plugin_dir)
    if module is None:
        return False

    # Extract tool definitions and handlers
    tools = _validate_tools(getattr(module, "TOOL_DEFINITIONS", []))
    handlers = _validate_handlers(getattr(module, "HANDLERS", {}))

    if not tools:
        logger.warning(f"Plugin '{actual_name}': no valid TOOL_DEFINITIONS found")
        return False

    # Register with the global registry
    if registry_module is None:
        try:
            from tools import registry as registry_module
        except ImportError:
            logger.error("Cannot import tools.registry — plugin tools not registered")
            return False

    registry_module.register_plugin_tools(tools, handlers)

    # Cache
    _loaded_plugins[actual_name] = {
        "manifest": manifest,
        "tools": tools,
        "handlers": handlers,
        "module": module,
    }

    logger.info(f"Plugin '{actual_name}' loaded ({len(tools)} tools)")
    return True


def load_all_plugins(registry_module=None) -> int:
    """Discover and load all enabled plugins.
    
    Returns:
        Number of plugins successfully loaded.
    """
    state = _load_registry_state()
    count = 0

    for plugin_dir in _discover_plugin_dirs():
        manifest = _load_manifest(plugin_dir)
        if manifest is None:
            continue

        name = manifest.get("name", plugin_dir.name)
        if not state.get(name, True):  # Default: enabled
            logger.info(f"Plugin '{name}' is disabled, skipping")
            continue

        if load_plugin(plugin_dir.name, registry_module):
            count += 1

    logger.info(f"Plugin loader: {count} plugin(s) loaded")
    return count


def reload_plugins(registry_module=None) -> int:
    """Reload all plugins (clear cache, re-discover, re-load).
    
    Returns:
        Number of plugins loaded.
    """
    # Clear cached loaded plugins
    _loaded_plugins.clear()
    return load_all_plugins(registry_module)


def plugin_create(name: str, description: str, author: str = "user") -> str:
    """Create a new external plugin boilerplate under ~/.Koza/plugins/<name>/."""
    _ensure_dirs()
    # Normalize name to be safe for directory and module import
    safe_name = name.lower().replace(" ", "_").replace("-", "_")
    safe_name = "".join(c for c in safe_name if c.isalnum() or c == "_")
    
    if not safe_name:
        return "❌ Invalid plugin name."
        
    plugin_dir = _PLUGINS_DIR / safe_name
    if plugin_dir.exists():
        return f"❌ Plugin '{safe_name}' already exists at {plugin_dir}"
        
    try:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        
        # Write manifest.json
        manifest = {
            "name": safe_name,
            "version": "1.0.0",
            "description": description,
            "author": author,
            "requires": []
        }
        manifest_path = plugin_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        
        # Write plugin.py
        plugin_py_content = f'''"""
Plugin: {name}
Description: {description}
Author: {author}
"""

# Define your tools schema following OpenAI/Anthropic tool call format
TOOL_DEFINITIONS = [
    {{
        "name": "{safe_name}_example_tool",
        "description": "An example tool generated for the {name} plugin.",
        "parameters": {{
            "type": "object",
            "properties": {{
                "param1": {{
                    "type": "string",
                    "description": "An example parameter description"
                }}
            }},
            "required": ["param1"]
        }}
    }}
]

# Map tool names to python callable handlers
def example_handler(param1: str) -> str:
    return f"Example tool executed with param1: {{param1}}"

HANDLERS = {{
    "{safe_name}_example_tool": example_handler
}}
'''
        plugin_py = plugin_dir / "plugin.py"
        plugin_py.write_text(plugin_py_content, encoding="utf-8")
        
        # Automatically enable the new plugin in the registry
        state = _load_registry_state()
        state[safe_name] = True
        _save_registry_state(state)
        
        return f"✅ Plugin '{safe_name}' created successfully at {plugin_dir} and auto-enabled."
    except Exception as e:
        return f"❌ Failed to create plugin '{safe_name}': {e}"


def plugin_enable(name: str) -> str:
    """Enable a plugin so it loads on next startup."""
    state = _load_registry_state()
    state[name] = True
    _save_registry_state(state)
    return f"✅ Plugin '{name}' enabled (will load on next restart)"


def plugin_disable(name: str) -> str:
    """Disable a plugin so it won't load on next startup."""
    state = _load_registry_state()
    state[name] = False
    _save_registry_state(state)
    return f"⏹️ Plugin '{name}' disabled"


def plugin_info(name: str) -> str:
    """Show detailed info about a specific plugin."""
    plugins = discover_plugins()
    for p in plugins:
        if p["name"] == name or name in p["name"]:
            lines = [
                f"📦 Plugin: {p['name']}",
                f"   Version: {p['version']}",
                f"   Description: {p['description']}",
                f"   Author: {p['author'] or 'unknown'}",
                f"   Status: {'✅ Enabled' if p['enabled'] else '⏹️ Disabled'}",
                f"   Tools: {p['tool_count']}",
                f"   Path: {p['path']}",
            ]
            return "\n".join(lines)
    return f"❌ Plugin '{name}' not found."


# ─── Tool Definitions ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "plugin_list",
        "description": "List all installed plugins with their status (enabled/disabled), version, and tool count.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "plugin_info",
        "description": "Show detailed information about a specific plugin.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Plugin name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "plugin_enable",
        "description": "Enable a plugin so it loads on the next Koza restart.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Plugin name to enable"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "plugin_disable",
        "description": "Disable a plugin so it won't load on the next Koza restart.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Plugin name to disable"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "plugin_create",
        "description": "Create a new external plugin template/boilerplate in ~/.Koza/plugins/ with boilerplate manifest.json and plugin.py.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The name of the new plugin"},
                "description": {"type": "string", "description": "Short description of what the plugin does"},
                "author": {"type": "string", "description": "Optional author name", "default": "user"}
            },
            "required": ["name", "description"]
        }
    },
]

HANDLERS: dict = {
    "plugin_list":    lambda: plugin_list(),
    "plugin_info":    lambda name: plugin_info(name),
    "plugin_enable":  lambda name: plugin_enable(name),
    "plugin_disable": lambda name: plugin_disable(name),
    "plugin_create":  lambda name, description, author="user": plugin_create(name, description, author),
}


def plugin_list() -> str:
    """List all plugins with their status."""
    plugins = discover_plugins()
    if not plugins:
        return "📭 No plugins installed. Create a directory under ~/.Koza/plugins/<name>/ with manifest.json + plugin.py"
    
    lines = [f"📦 Plugin Registry ({len(plugins)} installed):\n"]
    for p in sorted(plugins, key=lambda x: x["name"]):
        status = "✅" if p["enabled"] else "⏹️"
        lines.append(f"  {status} {p['name']} v{p['version']} — {p['description'][:60]} ({p['tool_count']} tools)")
    
    return "\n".join(lines)
