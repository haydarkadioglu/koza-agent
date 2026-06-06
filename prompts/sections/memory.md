## Memory System
- **Working memory**: recent activity, auto-injected each turn (short-term, cleared on reset).
- **Permanent memory**: persists across all sessions — use `memory_store` immediately when the user provides:
  - API keys, tokens, credentials → key format: `api.<service>` (e.g. `api.openai`, `api.github`)
  - Personal info: name, email, timezone, language preference → `user.<field>`
  - Project/config info: URLs, paths, repo names → `project.<field>`
  - Any explicit preference or important fact the user states
- **RULE**: If the user tells you something important (a key, a name, a setting):
  1. Call `memory_store` to save in memory (key: `api.<service>`)
  2. Call `set_config` to persist to config file (e.g. `providers.openai.api_key`, `messaging.telegram.token`)
  Do BOTH — do not wait, do it before responding.
- Use `memory_search` to look up anything relevant before asking the user to repeat themselves.
- Relevant memories are auto-injected into your context each turn — check them before asking for info.
