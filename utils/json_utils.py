import re
import json
import logging

def _escape_invalid_chars_in_json_strings(raw: str) -> str:
    """Escape unescaped control chars inside JSON string values."""
    out: list[str] = []
    in_string = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(raw[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
            elif ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
        i += 1
    return "".join(out)




def _repair_tool_call_arguments(raw_args: str, tool_name: str = "?") -> str:
    """Attempt to repair malformed tool_call argument JSON.

    Adopts the Hermes JSON repair taxonomy (trailing commas, control chars, unclosed braces).
    """
    import json
    import re

    raw_stripped = raw_args.strip() if isinstance(raw_args, str) else ""
    if not raw_stripped:
        return "{}"

    if raw_stripped == "None":
        return "{}"

    # Repair pass 0: strict=False json load/dump
    try:
        parsed = json.loads(raw_stripped, strict=False)
        return json.dumps(parsed, separators=(",", ":"))
    except Exception:
        pass

    # Attempt common JSON repairs
    fixed = raw_stripped
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)

    open_curly = fixed.count('{') - fixed.count('}')
    open_bracket = fixed.count('[') - fixed.count(']')
    if open_curly > 0:
        fixed += '}' * open_curly
    if open_bracket > 0:
        fixed += ']' * open_bracket

    for _ in range(50):
        try:
            json.loads(fixed)
            break
        except json.JSONDecodeError:
            if fixed.endswith('}') and fixed.count('}') > fixed.count('{'):
                fixed = fixed[:-1]
            elif fixed.endswith(']') and fixed.count(']') > fixed.count('['):
                fixed = fixed[:-1]
            else:
                break

    try:
        json.loads(fixed)
        return fixed
    except json.JSONDecodeError:
        pass

    # Repair pass 4: escape control chars and retry
    try:
        escaped = _escape_invalid_chars_in_json_strings(fixed)
        if escaped != fixed:
            json.loads(escaped)
            return escaped
    except Exception:
        pass

    return "{}"


def tool_call_arguments_look_truncated(raw_args: str) -> bool:
    """True when a tool-call payload was cut off before its JSON object closed.

    A complete object/array always ends in ``}`` or ``]``. Anything else was
    cut by the output-length limit or by a stream that died mid-call, and a
    truncation must never be executed as if it were a full argument set.
    """
    text = raw_args.strip() if isinstance(raw_args, str) else ""
    if not text:
        return False
    return not text.endswith(("}", "]"))


def parse_tool_call_arguments(raw_args: str | None, tool_name: str = "?") -> tuple[dict, str | None]:
    """Parse one tool call's argument JSON, repairing minor malformations.

    Returns ``(arguments, error)``. ``error`` is ``None`` when the payload was
    usable; otherwise ``arguments`` is empty and the caller MUST NOT execute the
    tool. Handing a silently emptied ``{}`` to a tool makes it act on missing
    parameters — which looks like a tool bug and hides the real cause — while
    reporting the parse failure back to the model lets it re-issue the call.
    """
    if raw_args is None:
        return {}, None
    if not isinstance(raw_args, str):
        raw_args = str(raw_args)

    stripped = raw_args.strip()
    # Empty payloads are a common model quirk for parameterless tools.
    if not stripped or stripped == "None":
        return {}, None

    try:
        parsed = json.loads(stripped)
    except Exception as exc:
        # Refuse a cut-off payload before repair: closing its braces would turn
        # a half-streamed call (e.g. {"command": "rm -rf /tmp) into a valid,
        # executable one.
        if tool_call_arguments_look_truncated(stripped):
            return {}, (
                "truncated JSON — the payload was cut off before closing its "
                f"object: {stripped[:120]!r}"
            )
        repaired = _repair_tool_call_arguments(stripped, tool_name=tool_name)
        # A non-empty payload repaired into "{}" means the repair gave up and
        # returned its failure sentinel — treat that as unparseable.
        if repaired == "{}" and re.sub(r"\s+", "", stripped) != "{}":
            parsed = None
        else:
            try:
                parsed = json.loads(repaired)
            except Exception:
                parsed = None
        if parsed is None:
            return {}, f"{exc}: {stripped[:120]!r}"

    if not isinstance(parsed, dict):
        return {}, (
            f"expected a JSON object, got {type(parsed).__name__}: {stripped[:120]!r}"
        )
    return parsed, None



