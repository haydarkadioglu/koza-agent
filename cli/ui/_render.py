"""Markdown → ANSI renderer."""
import re
import shutil
from ._colors import _C

try:
    from pygments import highlight as _pygments_highlight
    from pygments.lexers import get_lexer_by_name, ClassNotFound
    from pygments.formatters import Terminal256Formatter
    _HAS_PYGMENTS = True
except ImportError:
    _HAS_PYGMENTS = False


def _highlight_code(code: str, lang: str) -> str:
    """Apply Pygments syntax highlighting or fall back to cyan."""
    if _HAS_PYGMENTS and lang:
        try:
            lexer = get_lexer_by_name(lang, stripall=False)
            formatter = Terminal256Formatter()
            highlighted = _pygments_highlight(code, lexer, formatter)
            # Pygments always appends exactly one trailing newline; remove it
            if highlighted.endswith("\n"):
                highlighted = highlighted[:-1]
            # Pygments may normalize trailing newlines in the input,
            # so ensure the output has the same number of lines as the input
            input_line_count = code.count("\n") + 1
            output_line_count = highlighted.count("\n") + 1
            if output_line_count < input_line_count:
                highlighted += "\n" * (input_line_count - output_line_count)
            return highlighted
        except ClassNotFound:
            pass
    # Fallback: plain cyan
    lines = code.split("\n")
    return "\n".join(_C(line, "cyan") for line in lines)


def _render_md(text: str) -> str:
    """Convert Markdown to ANSI-styled plain text."""
    tw = shutil.get_terminal_size((100, 24)).columns - 6

    def _inline(s: str) -> str:
        s = re.sub(r"\*\*(.+?)\*\*", lambda m: _C(m.group(1), "white", "bold"), s)
        s = re.sub(r"\*(.+?)\*",     lambda m: _C(m.group(1), "white"), s)
        s = re.sub(r"`([^`]+)`",     lambda m: _C(m.group(1), "cyan"), s)
        return s

    lines = text.splitlines()
    out = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code blocks: ```lang ... ```
        fence_match = re.match(r"^(`{3,})(\w*)$", stripped)
        if fence_match:
            fence_marker = fence_match.group(1)
            lang = fence_match.group(2)
            code_lines = []
            i += 1
            while i < len(lines):
                if lines[i].strip() == fence_marker:
                    i += 1
                    break
                code_lines.append(lines[i])
                i += 1
            code = "\n".join(code_lines)
            highlighted = _highlight_code(code, lang)
            out.append(highlighted)
            continue

        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))
            title = _inline(m.group(2))
            if level == 1:
                out.append(_C(title, "yellow", "bold"))
                out.append(_C("─" * min(len(m.group(2)) + 2, tw), "gold"))
            elif level == 2:
                out.append(_C("  " + title, "yellow", "bold"))
            else:
                out.append(_C("    " + title, "cyan", "bold"))
            i += 1
            continue

        if re.match(r"^[-=]{3,}\s*$", stripped):
            out.append(_C("─" * tw, "grey"))
            i += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            data_rows = [r for r in table_lines if not re.match(r"^\|[-| :]+\|$", r)]
            if data_rows:
                rows = [[c.strip() for c in r.strip("|").split("|")] for r in data_rows]
                n_cols = max(len(r) for r in rows)
                rows = [r + [""] * (n_cols - len(r)) for r in rows]
                col_w = [max(len(re.sub(r"\x1b\[[^m]*m", "", c)) for c in col) for col in zip(*rows)]
                sep = _C("  " + "┼".join("─" * (w + 2) for w in col_w), "grey")
                for ri, row in enumerate(rows):
                    cells = []
                    for ci, cell in enumerate(row):
                        plain = re.sub(r"\x1b\[[^m]*m", "", cell)
                        pad = col_w[ci] - len(plain)
                        cells.append(" " + _inline(cell) + " " * (pad + 1))
                    styled_row = _C("  │", "grey") + _C("│", "grey").join(cells) + _C("│", "grey")
                    if ri == 0:
                        out.append(_C("  " + "┬".join("─" * (w + 2) for w in col_w), "grey"))
                    out.append(styled_row)
                    if ri == 0:
                        out.append(sep)
                out.append(_C("  " + "┴".join("─" * (w + 2) for w in col_w), "grey"))
            continue

        m = re.match(r"^[-*]\s+(.+)$", stripped)
        if m:
            out.append(_C("  • ", "yellow") + _inline(m.group(1)))
            i += 1
            continue

        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            out.append(_C(f"  {m.group(1)}. ", "yellow") + _inline(m.group(2)))
            i += 1
            continue

        out.append(_inline(stripped) if stripped else "")
        i += 1

    return "\n".join(out)
