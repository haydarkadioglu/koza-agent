"""Explicit outcomes for inline slash commands.

``_handle_inline`` used to return a bare bool, so a command could not ask the
caller to send something other than the typed line. ``SlashResult`` makes every
outcome explicit: handled, exit, not a command, or resubmit a different text.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SlashAction(str, Enum):
    HANDLED = "handled"          # command ran, nothing to send
    EXIT = "exit"                # leave the chat
    NOT_COMMAND = "not_command"  # not a command — forward the typed text verbatim
    RESUBMIT = "resubmit"        # send `text` instead of the typed line


@dataclass(frozen=True)
class SlashResult:
    action: SlashAction
    text: str | None = None

    @classmethod
    def handled(cls) -> SlashResult:
        return cls(SlashAction.HANDLED)

    @classmethod
    def exit_app(cls) -> SlashResult:
        return cls(SlashAction.EXIT)

    @classmethod
    def not_command(cls) -> SlashResult:
        return cls(SlashAction.NOT_COMMAND)

    @classmethod
    def resubmit(cls, text: str) -> SlashResult:
        return cls(SlashAction.RESUBMIT, text)


def outcome_text(result: SlashResult, typed_text: str) -> str | None:
    """Return the text to submit to the agent, or None if nothing should be sent."""
    if result.action is SlashAction.NOT_COMMAND:
        return typed_text
    if result.action is SlashAction.RESUBMIT:
        return result.text or None
    return None


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def retry_last_user_message(messages: list[dict]) -> str | None:
    """Rewind ``messages`` to just before the last user turn and return its text.

    Drops the last non-empty user message and everything after it (assistant
    answer, tool results, nudges). The caller re-submits the returned text once,
    so the history ends up net-identical and the model regenerates the answer.
    Returns None and leaves the list untouched if there is nothing to retry.
    The system message at index 0 is never removed.
    """
    start = 1 if messages and messages[0].get("role") == "system" else 0
    for idx in range(len(messages) - 1, start - 1, -1):
        message = messages[idx]
        if message.get("role") != "user":
            continue
        text = _message_text(message)
        if not text.strip():
            continue
        del messages[idx:]
        return text
    return None
