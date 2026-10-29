"""Plain-text extraction for zip+XML documents: DOCX, XLSX, PPTX, ODT and EPUB.

Every supported format is a zip archive of XML parts, so the parts are read
directly with ``zipfile`` and ``xml.etree.ElementTree`` — no third-party
document library is needed. ``extract_document`` returns the body text only;
callers add their own header (see ``skills/filesystem.py``).
"""
from __future__ import annotations

import os
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".docx", ".xlsx", ".pptx", ".odt", ".epub"})
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
MAX_EXTRACT_CHARS = 200_000

# A single XML part larger than this (uncompressed) is refused, so a small
# zip bomb cannot exhaust memory while being parsed.
_MAX_PART_BYTES = 128 * 1024 * 1024
_MAX_SHEET_ROWS = 2_000
_MAX_SHEET_COLS = 100

# Legacy binary Office files and password-protected OOXML packages are OLE
# compound files, not zip archives.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_OPF = "{http://www.idpf.org/2007/opf}"
_DC = "{http://purl.org/dc/elements/1.1/}"


class DocumentExtractionError(Exception):
    """The document could not be turned into text (bad archive, bad XML, too large, ...)."""


def is_supported_document(path: str | os.PathLike) -> bool:
    """True when the path has a document extension handled by ``extract_document``."""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def extract_document_kind(path: str | os.PathLike) -> str:
    """Upper-case kind label for headers, e.g. ``"DOCX"``."""
    suffix = Path(path).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise DocumentExtractionError(_unsupported_message(suffix))
    return suffix[1:].upper()


def extract_document(path: str | os.PathLike) -> str:
    """Return the body text of a supported document, capped at MAX_EXTRACT_CHARS."""
    kind = extract_document_kind(path)
    extractor = _EXTRACTORS[kind]
    try:
        text = extractor(Path(path))
    except DocumentExtractionError:
        raise
    except zipfile.BadZipFile:
        raise DocumentExtractionError(f"Not a valid {kind}: file is not a zip archive") from None
    except ET.ParseError as e:
        raise DocumentExtractionError(f"Not a valid {kind}: malformed XML ({e})") from None
    except KeyError as e:
        raise DocumentExtractionError(f"Not a valid {kind}: missing part {e}") from None
    except (RuntimeError, NotImplementedError) as e:
        raise DocumentExtractionError(
            f"Cannot read {kind}: archive uses unsupported compression or encryption ({e})"
        ) from None
    except (zlib.error, EOFError, ValueError) as e:
        raise DocumentExtractionError(f"Not a valid {kind}: corrupt archive ({e})") from None
    except OSError as e:
        raise DocumentExtractionError(f"Cannot read {kind}: {e}") from None

    if len(text) > MAX_EXTRACT_CHARS:
        text = (
            text[:MAX_EXTRACT_CHARS]
            + f"\n... [truncated: document is longer than {MAX_EXTRACT_CHARS} characters]"
        )
    return text


# ── Shared helpers ────────────────────────────────────────────────────────────

def _unsupported_message(suffix: str) -> str:
    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    return f"Unsupported document type '{suffix or '(none)'}'; supported types are {supported}"


@contextmanager
def _open_zip(path: Path, kind: str) -> Iterator[zipfile.ZipFile]:
    size = os.path.getsize(path)
    if size > MAX_DOCUMENT_BYTES:
        raise DocumentExtractionError(
            f"Document extraction refused: file is {size / (1024 * 1024):.1f} MB, "
            f"limit is {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB"
        )
    with open(path, "rb") as fh:
        head = fh.read(len(_OLE_MAGIC))
    if head == _OLE_MAGIC:
        raise DocumentExtractionError(
            f"Cannot read {kind}: file is password-protected or a legacy binary Office file; "
            "save it unencrypted in the modern format first"
        )
    if not zipfile.is_zipfile(path):
        raise DocumentExtractionError(f"Not a valid {kind}: file is not a zip archive")
    with zipfile.ZipFile(path) as zf:
        yield zf


def _check_part(zf: zipfile.ZipFile, name: str, kind: str) -> None:
    try:
        info = zf.getinfo(name)
    except KeyError:
        raise DocumentExtractionError(f"Not a valid {kind}: missing required part '{name}'") from None
    if info.file_size > _MAX_PART_BYTES:
        raise DocumentExtractionError(
            f"Document extraction refused: part '{name}' of the {kind} expands to "
            f"{info.file_size / (1024 * 1024):.1f} MB"
        )


def _parse_part(zf: zipfile.ZipFile, name: str, kind: str) -> ET.Element:
    _check_part(zf, name, kind)
    return ET.fromstring(zf.read(name))


def _has_part(zf: zipfile.ZipFile, name: str) -> bool:
    try:
        zf.getinfo(name)
    except KeyError:
        return False
    return True


def _collapse_blank_lines(lines: list[str]) -> str:
    """Join lines, never emitting more than one blank line in a row."""
    out: list[str] = []
    for line in lines:
        line = line.rstrip()
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def _flatten(text: str) -> str:
    """Single-line form of a text fragment, for table cells."""
    return " ".join(text.split())


# ── DOCX ──────────────────────────────────────────────────────────────────────

# Wrappers whose children are ordinary block or row content.
_W_WRAPPERS = {f"{_W}sdt", f"{_W}sdtContent", f"{_W}customXml", f"{_W}smartTag"}
# Subtrees that never contribute visible paragraph text: properties (which hold
# tab-stop definitions named w:tab), ruby phonetic guides, and the duplicate
# fallback branch of markup-compatibility blocks.
_W_SKIP = {f"{_W}pPr", f"{_W}rPr", f"{_W}rt", f"{_MC}Fallback"}


def _w_children(el: ET.Element, tag: str) -> Iterator[ET.Element]:
    """Direct children with ``tag``, looking through content-control wrappers."""
    for child in el:
        if child.tag == tag:
            yield child
        elif child.tag in _W_WRAPPERS:
            yield from _w_children(child, tag)


def _docx_paragraph(p: ET.Element) -> str:
    parts: list[str] = []

    def walk(el: ET.Element) -> None:
        for child in el:
            tag = child.tag
            if tag in _W_SKIP:
                continue
            if tag == f"{_W}t":
                parts.append(child.text or "")
            elif tag == f"{_W}tab":
                parts.append("\t")
            elif tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
            else:
                walk(child)

    walk(p)
    return "".join(parts)


def _docx_table_rows(tbl: ET.Element, depth: int = 0) -> list[str]:
    rows: list[str] = []
    for tr in _w_children(tbl, f"{_W}tr"):
        cells: list[str] = []
        for tc in _w_children(tr, f"{_W}tc"):
            pieces: list[str] = []
            for block in _w_block_iter(tc):
                if block.tag == f"{_W}p":
                    pieces.append(_flatten(_docx_paragraph(block)))
                elif block.tag == f"{_W}tbl" and depth == 0:
                    pieces.append("; ".join(_docx_table_rows(block, depth + 1)))
            cells.append(" ".join(piece for piece in pieces if piece))
        if any(cells):
            rows.append(" | ".join(cells))
    return rows


def _w_block_iter(el: ET.Element) -> Iterator[ET.Element]:
    for child in el:
        if child.tag in _W_WRAPPERS:
            yield from _w_block_iter(child)
        else:
            yield child


def _extract_docx(path: Path) -> str:
    with _open_zip(path, "DOCX") as zf:
        root = _parse_part(zf, "word/document.xml", "DOCX")
    body = root.find(f"{_W}body")
    if body is None:
        raise DocumentExtractionError("Not a valid DOCX: word/document.xml has no w:body")
    lines: list[str] = []
    for block in _w_block_iter(body):
        if block.tag == f"{_W}p":
            lines.append(_docx_paragraph(block))
        elif block.tag == f"{_W}tbl":
            lines.extend(_docx_table_rows(block))
    text = _collapse_blank_lines(lines)
    if not text.strip():
        raise DocumentExtractionError("DOCX contains no extractable text")
    return text


# ── XLSX ──────────────────────────────────────────────────────────────────────

_CELL_REF = re.compile(r"([A-Za-z]+)(\d+)")


def _xlsx_rich_text(el: ET.Element) -> str:
    """Text of a shared-string ``si`` or inline ``is``, skipping phonetic runs."""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            if child.tag == f"{_S}rPh":
                continue
            if child.tag == f"{_S}t":
                parts.append(child.text or "")
            else:
                walk(child)

    walk(el)
    return "".join(parts)


def _column_index(letters: str) -> int:
    """Bijective base-26 column letters to a 0-based index (A -> 0, AA -> 26)."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _xlsx_cell_value(c: ET.Element, shared: list[str]) -> str:
    t = c.get("t")
    if t == "inlineStr":
        is_el = c.find(f"{_S}is")
        return _xlsx_rich_text(is_el) if is_el is not None else ""
    v = c.find(f"{_S}v")
    raw = v.text if v is not None and v.text is not None else ""
    if t == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if t == "b":
        return "TRUE" if raw.strip() == "1" else "FALSE"
    if t == "e":
        return "#ERROR"
    return raw


def _xlsx_sheet_lines(zf: zipfile.ZipFile, part: str, shared: list[str]) -> list[str]:
    _check_part(zf, part, "XLSX")
    rows: list[list[str]] = []
    truncated = False
    next_row = 0
    with zf.open(part) as fh:
        for _event, el in ET.iterparse(fh, events=("end",)):
            if el.tag != f"{_S}row":
                continue
            try:
                row_idx = int(el.get("r", "")) - 1
            except ValueError:
                row_idx = next_row
            row_idx = max(row_idx, next_row)
            next_row = row_idx + 1
            if row_idx >= _MAX_SHEET_ROWS:
                truncated = True
                break
            cells: list[str] = []
            next_col = 0
            for c in el.iter(f"{_S}c"):
                m = _CELL_REF.fullmatch(c.get("r", ""))
                col = _column_index(m.group(1)) if m else next_col
                next_col = col + 1
                if col >= _MAX_SHEET_COLS:
                    truncated = True
                    continue
                value = _xlsx_cell_value(c, shared).replace("\t", " ").replace("\r", " ").replace("\n", " ")
                if col >= len(cells):
                    cells.extend([""] * (col + 1 - len(cells)))
                cells[col] = value
            while cells and not cells[-1]:
                cells.pop()
            rows.extend([] for _ in range(row_idx - len(rows)))
            rows.append(cells)
            el.clear()
    while rows and not rows[-1]:
        rows.pop()
    lines = ["\t".join(r) for r in rows]
    if truncated:
        lines.append("... [sheet truncated]")
    return lines


def _resolve_target(base_dir: str, target: str) -> str:
    target = unquote(target.split("#", 1)[0])
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join(base_dir, target))


def _extract_xlsx(path: Path) -> str:
    with _open_zip(path, "XLSX") as zf:
        shared: list[str] = []
        if _has_part(zf, "xl/sharedStrings.xml"):
            sst = _parse_part(zf, "xl/sharedStrings.xml", "XLSX")
            shared = [_xlsx_rich_text(si) for si in sst.findall(f"{_S}si")]
        workbook = _parse_part(zf, "xl/workbook.xml", "XLSX")
        rels = _parse_part(zf, "xl/_rels/workbook.xml.rels", "XLSX")
        targets = {
            rel.get("Id"): _resolve_target("xl", rel.get("Target", ""))
            for rel in rels.iter(f"{_PKG_REL}Relationship")
        }
        sections: list[str] = []
        for sheet in workbook.iter(f"{_S}sheet"):
            if sheet.get("state") in ("hidden", "veryHidden"):
                continue
            part = targets.get(sheet.get(f"{_R}id"))
            if not part or not _has_part(zf, part):
                continue
            lines = _xlsx_sheet_lines(zf, part, shared)
            sections.append("\n".join([f"# Sheet: {sheet.get('name', '')}"] + lines))
    if not sections:
        raise DocumentExtractionError("XLSX contains no readable visible sheets")
    return "\n\n".join(sections)


# ── PPTX ──────────────────────────────────────────────────────────────────────

_SLIDE_PART = re.compile(r"ppt/slides/slide(\d+)\.xml")


def _pptx_paragraph(p: ET.Element) -> str:
    parts: list[str] = []
    for el in p.iter():
        if el.tag == f"{_A}t":
            parts.append(el.text or "")
        elif el.tag == f"{_A}br":
            parts.append("\n")
    return "".join(parts)


def _extract_pptx(path: Path) -> str:
    with _open_zip(path, "PPTX") as zf:
        slides = sorted(
            (int(m.group(1)), name)
            for name in zf.namelist()
            if (m := _SLIDE_PART.fullmatch(name))
        )
        if not slides:
            raise DocumentExtractionError("Not a valid PPTX: no ppt/slides/slide<N>.xml parts found")
        sections: list[str] = []
        for number, name in slides:
            root = _parse_part(zf, name, "PPTX")
            lines = [_pptx_paragraph(p) for p in root.iter(f"{_A}p")]
            body = _collapse_blank_lines(lines)
            sections.append(f"# Slide {number}" + (f"\n{body}" if body.strip() else ""))
    return "\n\n".join(sections)


# ── ODT ───────────────────────────────────────────────────────────────────────

# Inline elements whose content is not part of the running text (comments,
# footnote bodies) or which hold deleted tracked-change text.
_ODF_INLINE_SKIP = {f"{_OFFICE}annotation", f"{_OFFICE}annotation-end", f"{_TEXT}note"}
_ODF_BLOCK_SKIP = {
    f"{_TEXT}tracked-changes", f"{_TEXT}sequence-decls", f"{_TEXT}variable-decls",
    f"{_TEXT}user-field-decls", f"{_OFFICE}forms", f"{_TABLE}table-columns",
    f"{_TABLE}table-column", f"{_TEXT}table-of-content-source", f"{_OFFICE}annotation",
}


def _odf_inline(el: ET.Element) -> str:
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in node:
            tag = child.tag
            if tag == f"{_TEXT}s":
                try:
                    count = int(child.get(f"{_TEXT}c", "1"))
                except ValueError:
                    count = 1
                parts.append(" " * max(count, 1))
            elif tag == f"{_TEXT}tab":
                parts.append("\t")
            elif tag == f"{_TEXT}line-break":
                parts.append("\n")
            elif tag not in _ODF_INLINE_SKIP:
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(el)
    return "".join(parts)


def _odf_heading(h: ET.Element) -> str:
    try:
        level = int(h.get(f"{_TEXT}outline-level", "1"))
    except ValueError:
        level = 1
    return "#" * max(level, 1) + " " + _odf_inline(h).strip()


def _odf_table_rows(tbl: ET.Element, depth: int = 0) -> list[str]:
    rows: list[str] = []
    for tr in _odf_rows(tbl):
        cells: list[str] = []
        for tc in tr.findall(f"{_TABLE}table-cell"):
            pieces: list[str] = []
            for block in tc:
                if block.tag in (f"{_TEXT}p", f"{_TEXT}h"):
                    pieces.append(_flatten(_odf_inline(block)))
                elif block.tag == f"{_TEXT}list":
                    pieces.extend(_flatten(_odf_inline(p)) for p in block.iter(f"{_TEXT}p"))
                elif block.tag == f"{_TABLE}table" and depth == 0:
                    pieces.append("; ".join(_odf_table_rows(block, depth + 1)))
            cells.append(" ".join(piece for piece in pieces if piece))
        if any(cells):
            rows.append(" | ".join(cells))
    return rows


_ODF_ROW_GROUPS = {f"{_TABLE}table-header-rows", f"{_TABLE}table-rows", f"{_TABLE}table-row-group"}


def _odf_rows(el: ET.Element) -> Iterator[ET.Element]:
    """Rows of this table only (not of tables nested in its cells)."""
    for child in el:
        if child.tag == f"{_TABLE}table-row":
            yield child
        elif child.tag in _ODF_ROW_GROUPS:
            yield from _odf_rows(child)


def _odf_blocks(el: ET.Element, lines: list[str]) -> None:
    for child in el:
        tag = child.tag
        if tag in _ODF_BLOCK_SKIP:
            continue
        if tag == f"{_TEXT}h":
            lines.append(_odf_heading(child))
        elif tag == f"{_TEXT}p":
            lines.append(_odf_inline(child))
        elif tag == f"{_TABLE}table":
            lines.extend(_odf_table_rows(child))
        else:
            _odf_blocks(child, lines)


def _extract_odt(path: Path) -> str:
    with _open_zip(path, "ODT") as zf:
        if _has_part(zf, "META-INF/manifest.xml"):
            _check_part(zf, "META-INF/manifest.xml", "ODT")
            if b"encryption-data" in zf.read("META-INF/manifest.xml"):
                raise DocumentExtractionError(
                    "Cannot read ODT: file is password-protected; save it without a password first"
                )
        root = _parse_part(zf, "content.xml", "ODT")
    body = root.find(f"{_OFFICE}body")
    if body is None:
        raise DocumentExtractionError("Not a valid ODT: content.xml has no office:body")
    lines: list[str] = []
    _odf_blocks(body, lines)
    text = _collapse_blank_lines(lines)
    if not text.strip():
        raise DocumentExtractionError("ODT contains no extractable text")
    return text


# ── EPUB ──────────────────────────────────────────────────────────────────────

_HTML_BLOCK_TAGS = {
    "p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr",
    "ul", "ol", "dl", "dt", "dd", "table", "blockquote", "pre", "hr",
    "section", "article", "aside", "header", "footer", "nav", "figure", "figcaption",
}
_HTML_SKIP_TAGS = {"head", "script", "style", "title"}


class _XhtmlText(HTMLParser):
    """Collects visible text with block boundaries as newlines and cells as ' | '."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._cells_in_row = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.rsplit(":", 1)[-1]
        if tag in _HTML_SKIP_TAGS:
            self._skip += 1
        elif tag in ("td", "th"):
            if self._cells_in_row:
                self.parts.append(" | ")
            self._cells_in_row += 1
        elif tag in _HTML_BLOCK_TAGS:
            if tag == "tr":
                self._cells_in_row = 0
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.rsplit(":", 1)[-1]
        if tag in _HTML_SKIP_TAGS:
            self._skip = max(self._skip - 1, 0)
        elif tag in _HTML_BLOCK_TAGS and tag != "br":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            # Source line wrapping is not a line break; only block tags are.
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).split("\n"))
        return "\n".join(line for line in lines if line)


def _render_xhtml(data: bytes) -> str:
    parser = _XhtmlText()
    parser.feed(data.decode("utf-8", errors="replace"))
    parser.close()
    return parser.text()


def _extract_epub(path: Path) -> str:
    with _open_zip(path, "EPUB") as zf:
        container = _parse_part(zf, "META-INF/container.xml", "EPUB")
        rootfiles = list(container.iter(f"{_CONTAINER}rootfile"))
        preferred = [
            rf for rf in rootfiles if rf.get("media-type") == "application/oebps-package+xml"
        ] or rootfiles
        opf_path = preferred[0].get("full-path") if preferred else None
        if not opf_path:
            raise DocumentExtractionError("Not a valid EPUB: container.xml names no rootfile")
        opf_path = _resolve_target("", opf_path)
        opf = _parse_part(zf, opf_path, "EPUB")
        opf_dir = posixpath.dirname(opf_path)

        title_el = opf.find(f".//{_DC}title")
        title = " ".join((title_el.text or "").split()) if title_el is not None else ""

        manifest = {
            item.get("id"): item.get("href", "")
            for item in opf.iter(f"{_OPF}item")
        }
        spine = opf.find(f"{_OPF}spine")
        chapters: list[str] = []
        for itemref in spine.iter(f"{_OPF}itemref") if spine is not None else ():
            href = manifest.get(itemref.get("idref"))
            non_linear = itemref.get("linear") == "no"
            try:
                if href is None:
                    raise DocumentExtractionError(
                        f"Not a valid EPUB: spine item '{itemref.get('idref')}' is not in the manifest"
                    )
                part = _resolve_target(opf_dir, href)
                _check_part(zf, part, "EPUB")
                chapter = _render_xhtml(zf.read(part))
            except (DocumentExtractionError, KeyError):
                if non_linear:
                    continue
                raise
            if chapter:
                chapters.append(chapter)
    if not chapters:
        raise DocumentExtractionError("EPUB spine contains no extractable text")
    header = [f"# {title}"] if title else []
    return "\n\n".join(header + chapters)


_EXTRACTORS: dict[str, Callable[[Path], str]] = {
    "DOCX": _extract_docx,
    "XLSX": _extract_xlsx,
    "PPTX": _extract_pptx,
    "ODT": _extract_odt,
    "EPUB": _extract_epub,
}
