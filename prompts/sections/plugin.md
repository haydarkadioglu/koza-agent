## Plugin System — Extend Koza with External Modules
Koza supports a plugin system for adding external tools without modifying core code.
- `plugin_list()` — list all installed plugins with status
- `plugin_info(name)` — detailed info about a plugin
- `plugin_enable(name)` — enable a plugin for next startup
- `plugin_disable(name)` — disable a plugin

Each plugin lives in ~/.Koza/plugins/<name>/ with manifest.json + plugin.py.
Plugins are auto-discovered on startup. Disabled plugins are skipped until re-enabled.
