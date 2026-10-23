"""Deterministically trim old chat history after a provider rejects its size.

Unlike proactive context compression, overflow recovery must work offline and
must not depend on another model call succeeding.
"""

from dataclasses import dataclass
from typing import Any

DEFAULT_KEEP_RECENT_MESSAGES = 12


@dataclass(frozen=True)
class OverflowRecoveryPolicy:
    enabled: bool = True
    max_retries: int = 1
    keep_recent_messages: int = DEFAULT_KEEP_RECENT_MESSAGES

    @classmethod
    def from_config(cls, cfg: dict | None) -> "OverflowRecoveryPolicy":
        """Build a validated policy, using defaults for missing or invalid values."""
        section = cfg.get("context_overflow") if isinstance(cfg, dict) else None
        if not isinstance(section, dict):
            section = {}

        enabled = section.get("enabled", True)
        if type(enabled) is not bool:
            enabled = True

        max_retries = section.get("max_retries", 1)
        if type(max_retries) is not int or max_retries < 0:
            max_retries = 1

        keep_recent = section.get(
            "keep_recent_messages", DEFAULT_KEEP_RECENT_MESSAGES
        )
        if type(keep_recent) is not int or keep_recent < 0:
            keep_recent = DEFAULT_KEEP_RECENT_MESSAGES

        if not enabled:
            max_retries = 0
        return cls(enabled, max_retries, keep_recent)


def _copy_structure(value: Any) -> Any:
    """Copy mutable message containers while reusing immutable payloads."""
    if isinstance(value, dict):
        return {key: _copy_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_structure(item) for item in value]
    return value


def _copy_message(message: dict) -> dict:
    return _copy_structure(message)


def _tool_call_id(call: Any) -> str:
    if isinstance(call, dict):
        return str(call.get("id") or "")
    return str(getattr(call, "id", "") or "")


def _append_note(message: dict, note: str, *, prepend: bool = False) -> bool:
    """Attach the recovery note to a message, refusing to flatten rich content.

    Multimodal ``content`` is a list of parts; stringifying it would replace an
    image with its repr, so such a message is left alone and the caller falls
    back to inserting the note as its own message.
    """
    content = message.get("content")
    if content is None or content == "":
        message["content"] = note
        return True
    if not isinstance(content, str):
        return False
    message["content"] = f"{note}\n{content}" if prepend else f"{content}\n{note}"
    return True


def shrink_messages(
    messages: list[dict],
    *,
    keep_recent_messages: int = DEFAULT_KEEP_RECENT_MESSAGES,
) -> tuple[list, bool]:
    """Remove older non-system messages while preserving valid tool-call pairs."""
    keep_recent_messages = (
        keep_recent_messages
        if type(keep_recent_messages) is int and keep_recent_messages >= 0
        else DEFAULT_KEEP_RECENT_MESSAGES
    )
    non_system_indices = [
        index
        for index, message in enumerate(messages)
        if not isinstance(message, dict) or message.get("role") != "system"
    ]
    elide_count = max(0, len(non_system_indices) - keep_recent_messages)
    if not elide_count:
        return messages, False

    elided_indices = set(non_system_indices[:elide_count])
    kept_indices = set(range(len(messages))) - elided_indices
    retained = [
        (index, _copy_message(message))
        for index, message in enumerate(messages)
        if index in kept_indices and isinstance(message, dict)
    ]

    kept_tool_ids = {
        str(message.get("tool_call_id") or "")
        for _, message in retained
        if message.get("role") == "tool" and message.get("tool_call_id")
    }
    kept_call_ids = {
        _tool_call_id(call)
        for _, message in retained
        if message.get("role") == "assistant"
        and isinstance(message.get("tool_calls"), list)
        for call in message["tool_calls"]
        if _tool_call_id(call)
    }
    matched_ids = kept_tool_ids & kept_call_ids

    cleaned = []
    for index, message in retained:
        role = message.get("role")
        if role == "tool":
            if str(message.get("tool_call_id") or "") not in matched_ids:
                continue
        elif role == "assistant" and isinstance(message.get("tool_calls"), list):
            calls = [
                call
                for call in message["tool_calls"]
                if _tool_call_id(call) in matched_ids
            ]
            if calls:
                message["tool_calls"] = calls
            else:
                message.pop("tool_calls", None)
                if not message.get("content"):
                    continue
        cleaned.append((index, message))

    first_elided_index = next(
        index for index in non_system_indices if index in elided_indices
    )
    note = (
        f"[context recovery] {elide_count} earlier messages were removed "
        "to fit the model's context window."
    )

    # Place the note where the removed history began. Merge into a neighboring
    # assistant message when needed to avoid consecutive assistant messages.
    insertion = next(
        (position for position, (index, _) in enumerate(cleaned)
         if index > first_elided_index),
        len(cleaned),
    )
    previous_assistant = next(
        (message for _, message in reversed(cleaned[:insertion])
         if message.get("role") != "system"),
        None,
    )
    next_assistant = next(
        (message for _, message in cleaned[insertion:]
         if message.get("role") != "system"),
        None,
    )
    note_attached = False
    if previous_assistant and previous_assistant.get("role") == "assistant":
        note_attached = _append_note(previous_assistant, note)
    elif next_assistant and next_assistant.get("role") == "assistant":
        note_attached = _append_note(next_assistant, note, prepend=True)
    if not note_attached:
        # A rich (multimodal) neighbour refuses the note, so it becomes its own
        # message; pick a role that does not repeat the next kept message's role.
        following = cleaned[insertion][1] if insertion < len(cleaned) else {}
        note_role = "user" if following.get("role") == "assistant" else "assistant"
        cleaned.insert(insertion, (first_elided_index, {
            "role": note_role,
            "content": note,
        }))

    return [message for _, message in cleaned], True
