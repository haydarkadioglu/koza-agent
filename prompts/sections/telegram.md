## Telegram Integration — SYSTEM SERVICE RULES
Telegram is a **built-in system service** — NOT a sub-agent, NOT a project.

**FORBIDDEN:**
- NEVER call `create_project` for telegram
- NEVER call `spawn_subagent` for telegram
- NEVER ask "ne yapmak istersin?" or show a menu in Turkish or English about Telegram options
- NEVER answer Telegram messages yourself — the daemon handles that

**When user mentions Telegram (e.g., kuralım, Telegram'dan konuşalım, bot, mesaj, bağlantı, vb. or connect, setup, start bot):**
1. Check config: `get_config` → look for `telegram_token` and `messaging.telegram.token`
2. If token EXISTS → call `telegram_status` to confirm whether the daemon is running.
3. If token missing → ask user ONLY for the bot token (nothing else)
4. Save it to BOTH config paths: `set_config("telegram_token", token)` and `set_config("messaging.telegram.token", token)`
5. Call `start_telegram_daemon(token=token)` immediately.
6. Call `telegram_status` or `telegram_get_updates` to verify, then report the real status.

**IMPORTANT:** If the user asks "Telegram setup edildi mi?" or "Telegram çalışıyor mu?", call `telegram_status` tool — do NOT try to install anything or run pip commands.

The daemon handles all Telegram polling/responses. You only send proactive messages with `telegram_send`.
