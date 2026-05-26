"""
System Agents — built-in services that run alongside Koza.

These are NOT user-spawnable sub-agents. They are persistent background services
managed automatically by koza_daemon.py and cli/daemon.py.

The LLM must NEVER use spawn_subagent() for these. Each has its own dedicated tool.
"""

SYSTEM_AGENTS = {
    "telegram": {
        "name": "Telegram Bot",
        "description": "Polls Telegram for messages and processes them with an Agent instance.",
        "implementation": "bots/telegram.py",
        "start_tool": "start_telegram_daemon",
        "status_tool": "telegram_status",
        "config_keys": ["telegram_token", "messaging.telegram.chat_id"],
        "locked": True,  # Cannot be modified or replaced by user sub-agents
    },
    "cron": {
        "name": "Cron Scheduler",
        "description": "APScheduler-based task scheduler for periodic/scheduled jobs.",
        "implementation": "skills/cron_scheduler.py",
        "start_tool": None,  # auto-starts on import
        "status_tool": "list_crons",
        "config_keys": [],
        "locked": True,
    },
    "sync": {
        "name": "Multi-Host Sync",
        "description": "Bidirectional database sync between Koza hosts.",
        "implementation": "skills/sync/",
        "start_tool": "sync_now",
        "status_tool": "sync_status",
        "config_keys": ["multi_host.mode", "multi_host.master_url", "multi_host.sync_token"],
        "locked": True,
    },
}


def list_system_agents() -> str:
    """Return a human-readable list of built-in system agents."""
    lines = ["Built-in system services (cannot be replaced by sub-agents):\n"]
    for key, info in SYSTEM_AGENTS.items():
        lines.append(
            f"  {key:12s} — {info['description']}\n"
            f"              Tool: {info['start_tool'] or 'auto-start'}"
        )
    return "\n".join(lines)
