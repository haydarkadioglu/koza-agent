"""Small helpers for turning Agent stream events into TUI-friendly text."""
from __future__ import annotations


def summarize_tool_args(args: dict, limit: int = 80) -> str:
    if not args:
        return ""
    hidden = {"content", "text", "body", "code", "script"}
    parts: list[str] = []
    for key, value in list(args.items())[:4]:
        if key in hidden:
            text = str(value).splitlines()[0] if value is not None else ""
            parts.append(f"{key}=<{len(str(value))} chars: {text[:24]}>")
        else:
            parts.append(f"{key}={repr(value)[:limit]}")
    return ", ".join(parts)


def stream_event_to_record(event: dict) -> tuple[str, str]:
    """Return (channel, text) for a stream event.

    channel is one of: status, chat, tool, error, ignore.
    """
    etype = event.get("type", "")
    if etype == "thinking":
        return "status", "Thinking..."
    if etype == "tool_start":
        name = event.get("name", "")
        arg_text = summarize_tool_args(event.get("args", {}))
        suffix = f" ({arg_text})" if arg_text else ""
        return "tool", f"> {name}{suffix}"
    if etype == "tool_done":
        name = event.get("name", "")
        elapsed = float(event.get("elapsed", 0) or 0)
        result = str(event.get("result", ""))
        preview = result.splitlines()[0][:160] if result else ""
        suffix = f" - {preview}" if preview else ""
        return "tool", f"< {name} done in {elapsed:.2f}s{suffix}"
    if etype == "tool_denied":
        return "tool", f"! {event.get('name', '')} denied"
    if etype == "text":
        return "chat", str(event.get("token", ""))
    if etype == "interrupted":
        return "status", "Interrupted"
    if etype == "error":
        return "error", str(event.get("message", "Unknown error"))
    if etype in {"status", "plan", "persona_tool", "error_recorded", "done"}:
        return "tool", str(event)
    if etype == "persona_token":
        return "chat", str(event.get("token", ""))
    return "ignore", ""
