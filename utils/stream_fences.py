"""
Fence-safe helpers for streaming markdown into chat messages.

A partially streamed answer may stop in the middle of a fenced code block or
an inline code span; rendering that as-is turns the rest of the message into
one giant code block. These helpers close dangling fences and split long
buffers without cutting a fenced block in half.

Pure stdlib — no dependency on any bot framework.
"""
import re

_FENCE = "```"


def ensure_closed_fences(text: str) -> str:
    """Close an unbalanced ``` fence and an unbalanced inline backtick span."""
    if not isinstance(text, str) or not text:
        return text

    if text.count(_FENCE) % 2 == 1:
        text = text.rstrip("\n") + "\n" + _FENCE

    # Count inline backticks only outside fenced regions: backticks that live
    # inside a code block are literal and must not trigger a correction.
    outside = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    outside = re.sub(r"```[^`]*$", "", outside)
    if outside.count("`") % 2 == 1:
        text += "`"
    return text


def _scan_fences(text: str, end: int) -> tuple[int, str]:
    """Scan lines of text[:end]; return (open fence offset or -1, its language)."""
    open_at = -1
    lang = ""
    pos = 0
    for line in text[:end].splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(_FENCE):
            if open_at == -1:
                open_at = pos
                info = stripped[3:].split()
                lang = info[0] if info else ""
            else:
                open_at = -1
                lang = ""
        pos += len(line)
    return open_at, lang


def open_fence_language(text: str) -> str:
    """Return the language of the currently open fence in text, or "" if none."""
    if not isinstance(text, str) or not text:
        return ""
    _, lang = _scan_fences(text, len(text))
    return lang


def split_fenced(text: str, limit: int) -> tuple[str, str]:
    """Split text into (head, tail) with len(head) <= limit where possible,
    never leaving a fenced code block cut between the two halves.

    When the split point falls inside a fenced block, the head is closed with a
    fence and the tail re-opens with the same language, so each half renders as a
    well-formed block and neither half exceeds the message cap.
    """
    if limit <= 0 or len(text) <= limit:
        return text, ""

    # Prefer the last newline that keeps head within limit (newline stays in head).
    nl = text.rfind("\n", 0, limit)
    split = nl + 1 if nl >= 0 else limit

    open_at, lang = _scan_fences(text, split)
    if open_at == -1:
        return text[:split], text[split:]

    # Split lands inside a code block: close the head, re-open the tail.
    # Moving the whole block to the tail would send a message over the cap.
    head = text[:split].rstrip("\n") + "\n" + _FENCE
    tail = _FENCE + lang + "\n" + text[split:]
    return head, tail
