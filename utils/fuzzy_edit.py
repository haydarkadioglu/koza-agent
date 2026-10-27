"""Fuzzy-anchor text replacement for the ``koza_edit`` tool.

``patch_file`` only does an exact ``str.replace``: an anchor that differs from
the file by indentation, collapsed spaces, an escaped ``\\n`` or a typographic
dash simply misses, and an anchor that occurs twice silently edits the first
hit. Each miss costs the model a turn and tool-loop budget.

``apply_edit`` tries a fixed chain of matching strategies, from strict to
loose, and stops at the first one that finds the anchor. Every strategy
returns spans in the *original* content, so bytes outside the replaced region
are never touched. Non-exact hits are only applied when they are unambiguous,
and a miss returns the closest lines so the model can correct its anchor.

Stdlib only.
"""
import difflib
import re
from dataclasses import dataclass
from itertools import pairwise

Span = tuple[int, int]

# Strategies that may be combined with replace_all. Everything looser than a
# per-line strip is too easy to over-apply across a file.
_REPLACE_ALL_STRATEGIES = frozenset({"exact", "line_trimmed"})

# Middle-of-block similarity needed by block_anchor. Lower values start
# matching unrelated blocks that merely share a first and last line.
_BLOCK_ANCHOR_THRESHOLD = 0.75

_MAX_LISTED_CANDIDATES = 5
_HINT_LINES = 3

_HSPACE_RE = re.compile(r"[ \t]+")

_UNICODE_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2032": "'", "\u2033": '"',
    "\u2014": "--", "\u2013": "-", "\u2012": "-", "\u2010": "-", "\u2011": "-",
    "\u2212": "-",
    "\u2026": "...",
    "\u00a0": " ", "\u2002": " ", "\u2003": " ", "\u2007": " ", "\u2009": " ",
    "\u200a": " ", "\u202f": " ", "\u3000": " ",
    "\u200b": "", "\ufeff": "",
}
_UNICODE_RE = re.compile("[" + "".join(_UNICODE_MAP) + "]")

_ESCAPES = {"\\n": "\n", "\\t": "\t", "\\r": "\r"}
_ESCAPE_RE = re.compile(r"\\[ntr]")


@dataclass
class EditResult:
    content: str            # new content (== input content on failure)
    ok: bool
    strategy: str = ""      # "exact" | "line_trimmed" | ... | ""
    replacements: int = 0
    error: str = ""         # actionable, model-facing, English


# ─── Normalization with offset maps ───────────────────────────────────────────

def _mapped_sub(text: str, rx: re.Pattern, repl) -> tuple[str, list[int], list[int]]:
    """Substitute ``rx`` matches and keep, for every output char, the span of
    original text it came from. Offsets always refer to ``text``."""
    parts: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    pos = 0
    for m in rx.finditer(text):
        a, b = m.span()
        parts.append(text[pos:a])
        starts.extend(range(pos, a))
        ends.extend(range(pos + 1, a + 1))
        r = repl(m)
        parts.append(r)
        starts.extend([a] * len(r))
        ends.extend([b] * len(r))
        pos = b
    parts.append(text[pos:])
    starts.extend(range(pos, len(text)))
    ends.extend(range(pos + 1, len(text) + 1))
    return "".join(parts), starts, ends


def _collapse_ws(text: str) -> str:
    return _HSPACE_RE.sub(" ", text)


def _unicode_ascii(text: str) -> str:
    return _UNICODE_RE.sub(lambda m: _UNICODE_MAP[m.group()], text)


def _norm_line(line: str) -> str:
    """Line normalization used by block_anchor comparisons."""
    return _collapse_ws(_unicode_ascii(line)).strip()


def _non_overlapping(spans: list[Span]) -> list[Span]:
    out: list[Span] = []
    last_end = -1
    for s, e in sorted(spans):
        if s >= last_end:
            out.append((s, e))
            last_end = e
    return out


def _normalized_search(content: str, pattern: str, rx: re.Pattern, repl) -> list[Span]:
    norm_content, starts, ends = _mapped_sub(content, rx, repl)
    norm_pattern = rx.sub(repl, pattern)
    if not norm_pattern or (norm_content == content and norm_pattern == pattern):
        return []
    spans = []
    for m in re.finditer(re.escape(norm_pattern), norm_content):
        ns, ne = m.span()
        spans.append((starts[ns], ends[ne - 1]))
    return _non_overlapping(spans)


# ─── Line helpers ─────────────────────────────────────────────────────────────

def _split_lines(content: str) -> tuple[list[str], list[int]]:
    lines = content.split("\n")
    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    return lines, offsets


def _pattern_lines(pattern: str) -> tuple[list[str], bool]:
    lines = pattern.split("\n")
    trailing_nl = len(lines) > 1 and lines[-1] == ""
    if trailing_nl:
        lines = lines[:-1]
    return lines, trailing_nl


def _window_span(content: str, lines: list[str], offsets: list[int],
                 first: int, last: int, trailing_nl: bool) -> Span:
    start = offsets[first]
    end = offsets[last] + len(lines[last])
    if trailing_nl and end < len(content) and content[end] == "\n":
        end += 1
    return start, end


def _line_window_search(content: str, pattern: str, key) -> list[Span]:
    plines, trailing_nl = _pattern_lines(pattern)
    want = [key(p) for p in plines]
    if not any(want):
        return []
    lines, offsets = _split_lines(content)
    keyed = [key(line) for line in lines]
    n = len(want)
    spans = []
    i = 0
    while i + n <= len(lines):
        if keyed[i:i + n] == want:
            spans.append(_window_span(content, lines, offsets, i, i + n - 1, trailing_nl))
            i += n
        else:
            i += 1
    return spans


# ─── Strategies ───────────────────────────────────────────────────────────────

def _exact(content: str, pattern: str) -> list[Span]:
    return [m.span() for m in re.finditer(re.escape(pattern), content)]


def _line_trimmed(content: str, pattern: str) -> list[Span]:
    return _line_window_search(content, pattern, str.strip)


def _whitespace_collapsed(content: str, pattern: str) -> list[Span]:
    return _normalized_search(content, pattern, _HSPACE_RE, lambda m: " ")


def _indentation_flexible(content: str, pattern: str) -> list[Span]:
    return _line_window_search(content, pattern, str.lstrip)


def _unescape(text: str) -> str:
    return _ESCAPE_RE.sub(lambda m: _ESCAPES[m.group()], text)


def _escaped_literal(content: str, pattern: str) -> list[Span]:
    unescaped = _unescape(pattern)
    if unescaped == pattern:
        return []
    return _exact(content, unescaped)


def _unicode_normalized(content: str, pattern: str) -> list[Span]:
    return _normalized_search(content, pattern, _UNICODE_RE, lambda m: _UNICODE_MAP[m.group()])


def _block_anchor(content: str, pattern: str) -> list[Span]:
    plines, trailing_nl = _pattern_lines(pattern)
    if len(plines) < 2:
        return []
    first, last = _norm_line(plines[0]), _norm_line(plines[-1])
    if not first or not last:
        return []
    middle = "\n".join(_norm_line(p) for p in plines[1:-1])
    lines, offsets = _split_lines(content)
    normed = [_norm_line(line) for line in lines]
    # Let the drifted middle grow or shrink a little, but not unboundedly.
    max_len = len(plines) * 2 + 2
    spans = []
    i = 0
    while i < len(lines):
        if normed[i] != first:
            i += 1
            continue
        hit = None
        for j in range(i + 1, min(len(lines), i + max_len)):
            if normed[j] != last:
                continue
            got = "\n".join(normed[i + 1:j])
            ratio = difflib.SequenceMatcher(None, got, middle, autojunk=False).ratio()
            if ratio >= _BLOCK_ANCHOR_THRESHOLD:
                hit = j
            break  # only the nearest closing anchor is considered
        if hit is None:
            i += 1
            continue
        spans.append(_window_span(content, lines, offsets, i, hit, trailing_nl))
        i = hit + 1
    return spans


_STRATEGIES = (
    ("exact", _exact),
    ("line_trimmed", _line_trimmed),
    ("whitespace_collapsed", _whitespace_collapsed),
    ("indentation_flexible", _indentation_flexible),
    ("escaped_literal", _escaped_literal),
    ("unicode_normalized", _unicode_normalized),
    ("block_anchor", _block_anchor),
)


# ─── Replacement helpers ──────────────────────────────────────────────────────

def _leading_ws(text: str) -> str:
    return text[:len(text) - len(text.lstrip(" \t"))]


def _uniform_shift(old_string: str, matched: str, old_indent: str, match_indent: str) -> bool:
    """True when every anchor line differs from its matched file line by the
    same indentation change as the first line (a whole block that drifted)."""
    a_lines, m_lines = old_string.split("\n"), matched.split("\n")
    if len(a_lines) != len(m_lines):
        return True  # no line correspondence (block_anchor); trust the first line
    for a, m in zip(a_lines[1:], m_lines[1:]):
        if not a.strip() or not m.strip():
            continue
        a_ws = _leading_ws(a)
        if not a_ws.startswith(old_indent) or _leading_ws(m) != match_indent + a_ws[len(old_indent):]:
            return False
    return True


def _reindent(new_string: str, old_string: str, content: str, start: int, end: int) -> str:
    """Shift ``new_string`` to the indentation of the matched region when the
    anchor's first line was indented differently from the file.

    If the anchor's other lines did not drift by the same amount (e.g. only the
    first line lost its indent), only the first line is adjusted."""
    line_start = content.rfind("\n", 0, start) + 1
    lead = content[line_start:start]
    if lead.strip(" \t"):
        return new_string  # match begins mid-line; indentation is not ours to fix
    line_end = content.find("\n", start)
    match_indent = _leading_ws(content[line_start:line_end if line_end != -1 else len(content)])
    old_indent = _leading_ws(old_string.split("\n", 1)[0])
    if old_indent == match_indent:
        return new_string
    shift_all = _uniform_shift(old_string, lead + content[start:end], old_indent, match_indent)
    out = []
    for k, line in enumerate(new_string.split("\n")):
        if k == 0:
            if line.startswith(old_indent):
                line = match_indent + line[len(old_indent):]
            # The file already supplies ``lead`` in front of the span.
            out.append(line.removeprefix(lead))
        elif not shift_all or not line.strip():
            out.append(line)
        elif line.startswith(old_indent):
            out.append(match_indent + line[len(old_indent):])
        else:
            out.append(line)
    return "\n".join(out)


def _line_no(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _closest_lines_hint(content: str, old_string: str) -> str:
    probe = next((p.strip() for p in old_string.split("\n") if p.strip()), "")
    if not content.strip():
        return "The file is empty."
    scored = []
    for no, line in enumerate(content.split("\n"), 1):
        if not line.strip():
            continue
        ratio = difflib.SequenceMatcher(None, probe, line.strip(), autojunk=False).ratio()
        scored.append((ratio, no, line))
    scored.sort(key=lambda t: (-t[0], t[1]))
    rows = []
    for ratio, no, line in scored[:_HINT_LINES]:
        shown = line if len(line) <= 120 else line[:117] + "..."
        rows.append(f"  L{no} ({ratio:.0%}): {shown}")
    return "Closest lines to the first line of old_string:\n" + "\n".join(rows)


def _fail(content: str, error: str) -> EditResult:
    return EditResult(content=content, ok=False, error=error)


# ─── Public API ───────────────────────────────────────────────────────────────

def apply_edit(content, old_string: str, new_string: str,
               replace_all: bool = False) -> EditResult:
    """Replace ``old_string`` with ``new_string`` in ``content`` using the
    first matching strategy. Never raises for bad input; check ``ok``."""
    if isinstance(content, (bytes, bytearray)):
        try:
            content = bytes(content).decode("utf-8")
        except UnicodeDecodeError as e:
            return _fail("", f"File is not valid UTF-8 (byte {e.start}); "
                             "koza_edit only edits UTF-8 text files.")
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return _fail(content, "old_string and new_string must both be strings.")
    if old_string == "":
        return _fail(content, "old_string is empty. Pass the exact text to replace, with "
                              "a line or two of context so it is unique; use write_file "
                              "to create a new file.")
    if not old_string.strip():
        return _fail(content, "old_string is only whitespace, which cannot be located "
                              "reliably. Include a neighbouring line of real text.")
    if old_string == new_string:
        return _fail(content, "old_string and new_string are identical, so the edit "
                              "would change nothing. Pass the replacement text in new_string.")

    for name, finder in _STRATEGIES:
        spans = finder(content, old_string)
        if not spans:
            continue

        if len(spans) > 1 and not replace_all:
            nums = [_line_no(content, s) for s, _ in spans]
            listed = ", ".join(str(n) for n in nums[:_MAX_LISTED_CANDIDATES])
            more = len(nums) - _MAX_LISTED_CANDIDATES
            if more > 0:
                listed += f" (and {more} more)"
            return _fail(content, f"old_string matches {len(spans)} places ({name} match) "
                                  f"at lines {listed}. Add surrounding lines to make it "
                                  "unique, or set replace_all=true for an exact match.")
        if replace_all and name not in _REPLACE_ALL_STRATEGIES:
            return _fail(content, f"replace_all is only allowed for exact or line_trimmed "
                                  f"matches, but old_string was only found via the looser "
                                  f"'{name}' strategy. Copy the anchor text exactly from the "
                                  "file, or edit each occurrence separately.")

        replacement = new_string
        if name == "escaped_literal" and "\n" not in new_string:
            # The model escaped both sides; keep them consistent.
            replacement = _unescape(new_string)

        spans = sorted(spans)
        for (_, prev_end), (nxt_start, _) in pairwise(spans):
            if nxt_start < prev_end:
                return _fail(content, "Internal error: overlapping match spans; "
                                      "no changes made. Use a more specific old_string.")

        out = content
        for s, e in reversed(spans):
            rep = replacement if name == "exact" else _reindent(replacement, old_string, content, s, e)
            out = out[:s] + rep + out[e:]

        if out == content:
            return _fail(content, f"The matched text ({name} match at line "
                                  f"{_line_no(content, spans[0][0])}) already equals "
                                  "new_string; nothing would change.")
        return EditResult(content=out, ok=True, strategy=name, replacements=len(spans))

    tried = ", ".join(n for n, _ in _STRATEGIES)
    return _fail(content, f"old_string was not found (tried: {tried}). "
                          f"{_closest_lines_hint(content, old_string)}\n"
                          "Re-read that region with read_file_range and copy the text exactly.")
