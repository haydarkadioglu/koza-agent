"""Reminder skill — set_reminder tool for scheduling proactive Telegram reminders."""

from datetime import datetime

from dateutil.parser import parse as parse_dt


__all__ = ["TOOL_DEFINITIONS", "HANDLERS", "handle_set_reminder"]


# ── Tool definition (flat format matching project convention) ─────────────────

REMINDER_TOOL = {
    "name": "set_reminder",
    "description": (
        "Set a one-time reminder that will be sent via Telegram at the specified time. "
        "The reminder message will be delivered proactively to the configured chat."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The reminder message text",
            },
            "time": {
                "type": "string",
                "description": (
                    "When to send the reminder. Accepts ISO 8601 datetime "
                    "(e.g. '2024-03-15T14:00:00') or natural language "
                    "(e.g. 'tomorrow at 9am', '2024-12-25 08:00')"
                ),
            },
        },
        "required": ["text", "time"],
    },
}

TOOL_DEFINITIONS = [REMINDER_TOOL]


# ── Handler ──────────────────────────────────────────────────────────────────


def handle_set_reminder(text: str, time: str) -> str:
    """
    Parse the time string and schedule a reminder via ProactiveNotifier.

    Returns a confirmation message on success or an error message on failure.
    """
    try:
        remind_at = parse_dt(time)
    except (ValueError, TypeError):
        return f"Error: could not parse time '{time}'. Please use ISO 8601 format (e.g. '2024-03-15T14:00:00')."

    from bots.telegram_notifier import ProactiveNotifier

    notifier = ProactiveNotifier.get_instance()
    return notifier.schedule_reminder(text, remind_at)


HANDLERS = {
    "set_reminder": lambda text, time: handle_set_reminder(text, time),
}
