"""Deterministic tool-call id uniquification.

Providers occasionally reuse one tool-call id — or omit the id entirely — for
several calls inside a single assistant turn. The id is the pairing key for
every tool *result*, so a collision silently drops one tool's result and
repeats the other's, and strict providers reject the duplicate outright (400).
"""
import logging

logger = logging.getLogger(__name__)


def uniquify_tool_call_ids(tool_calls: list) -> int:
    """Give every call in one round a distinct, deterministic id.

    Mutates each entry's ``"id"`` in place. Later collisions get an
    ``<id>_d<n>`` suffix (n counted from 2, first occurrence wins) —
    deterministic on purpose: these ids ride the prompt-cache prefix, so a
    random suffix would break caching. Returns the number of entries renamed.

    Blank / non-string ids are skipped: the caller has already coalesced them
    to the tool name and there is nothing stable to suffix.
    """
    seen: set[str] = set()
    renamed = 0
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        cid = call.get("id")
        cid = cid.strip() if isinstance(cid, str) else ""
        if not cid:
            continue
        if cid not in seen:
            seen.add(cid)
            continue
        # Bounded: at most len(seen) suffixes can already be taken.
        new_id = next(
            f"{cid}_d{n}" for n in range(2, len(seen) + 3) if f"{cid}_d{n}" not in seen
        )
        seen.add(new_id)
        call["id"] = new_id
        renamed += 1
        logger.warning(
            "Model reused tool-call id %s in one round; renamed the duplicate to %s "
            "(tool=%s) so every tool result stays paired.",
            cid,
            new_id,
            call.get("name", "?"),
        )
    return renamed
