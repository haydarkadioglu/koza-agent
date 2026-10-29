"""read_document: stdlib text extraction for DOCX / XLSX / PPTX / ODT / EPUB (K-37).

Before this, ``read_file`` only special-cased PDF; every Office document or EPUB
fell through to ``read_text(encoding="utf-8")`` and came back as a
UnicodeDecodeError. Fixtures are built here as minimal zip+XML packages.
"""
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import document_extract
from utils.document_extract import (
    DocumentExtractionError,
    extract_document,
    extract_document_kind,
    is_supported_document,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _write_zip(path: str, parts: dict) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return path


DOCX_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    <w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>
      <w:r><w:t>First paragraph</w:t></w:r></w:p>
    <w:p/>
    <w:p/>
    <w:p><w:r><w:t>Name</w:t></w:r><w:r><w:tab/><w:t>Value</w:t></w:r></w:p>
    <w:p><w:r><w:ruby><w:rt><w:r><w:t>kanji-reading</w:t></w:r></w:rt>
      <w:rubyBase><w:r><w:t>Kanji</w:t></w:r></w:rubyBase></w:ruby></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>b</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>c</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>d</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    <w:sectPr><w:pgSz w:w="12240"/></w:sectPr>
  </w:body>
</w:document>"""


def make_docx(path: str) -> str:
    return _write_zip(path, {"word/document.xml": DOCX_XML})


def make_xlsx(path: str) -> str:
    workbook = f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="{S_NS}" xmlns:r="{R_NS}"><sheets>
  <sheet name="Data" sheetId="1" r:id="rId1"/>
  <sheet name="Secret" sheetId="2" state="hidden" r:id="rId2"/>
  <sheet name="Ghost" sheetId="3" r:id="rId3"/>
</sheets></workbook>"""
    rels = f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{PKG_REL_NS}">
  <Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="ws"/>
  <Relationship Id="rId2" Target="/xl/worksheets/sheet2.xml" Type="ws"/>
  <Relationship Id="rId3" Target="worksheets/missing.xml" Type="ws"/>
</Relationships>"""
    shared = f"""<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="{S_NS}"><si><t>Header</t></si><si><r><t>Rich </t></r><r><t>text</t></r></si></sst>"""
    sheet1 = f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="{S_NS}"><sheetData>
  <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>inline</t></is></c></row>
  <row r="2"><c r="A2" t="b"><v>1</v></c><c r="B2" t="b"><v>0</v></c><c r="C2"><v>3.5</v></c></row>
  <row r="3"><c r="A3" t="s"><v>1</v></c><c r="C3"><v>42</v></c></row>
  <row r="4"><c r="A4" t="e"><v>#DIV/0!</v></c></row>
  <row r="5"/>
</sheetData></worksheet>"""
    sheet2 = f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="{S_NS}"><sheetData>
  <row r="1"><c r="A1" t="inlineStr"><is><t>hidden-value</t></is></c></row>
</sheetData></worksheet>"""
    return _write_zip(path, {
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": rels,
        "xl/sharedStrings.xml": shared,
        "xl/worksheets/sheet1.xml": sheet1,
        "xl/worksheets/sheet2.xml": sheet2,
    })


def _slide(*paragraphs: str) -> str:
    body = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="{P_NS}" xmlns:a="{A_NS}"><p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"""


def make_pptx(path: str) -> str:
    return _write_zip(path, {
        # Written out of order: slide10 must sort after slide2 numerically.
        "ppt/slides/slide10.xml": _slide("Tenth"),
        "ppt/slides/slide2.xml": _slide("Second title", "Second body"),
        "ppt/slides/slide1.xml": _slide("Opening slide"),
        "ppt/notesSlides/notesSlide1.xml": _slide("speaker notes"),
    })


def make_odt(path: str) -> str:
    content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body><office:text>
    <text:sequence-decls><text:sequence-decl text:name="Table"/></text:sequence-decls>
    <text:h text:outline-level="2">Chapter Heading</text:h>
    <text:p>Hello<text:s text:c="3"/>world<text:tab/>tabbed<text:line-break/>next line</text:p>
    <table:table><table:table-row>
      <table:table-cell><text:p>x</text:p></table:table-cell>
      <table:table-cell><text:p>y</text:p></table:table-cell>
    </table:table-row></table:table>
  </office:text></office:body>
</office:document-content>"""
    return _write_zip(path, {"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})


def make_epub(path: str) -> str:
    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test Book</dc:title></metadata>
  <manifest>
    <item id="c1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="text/ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>"""
    ch1 = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ignored head title</title>
<style>p { color: red; }</style></head>
<body><h1>Chapter One</h1><p>Fish &amp; chips,
   wrapped across source lines.</p></body></html>"""
    ch2 = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>Second <b>chapter</b> text.</p>
<table><tr><td>k1</td><td>v1</td></tr></table>
</body></html>"""
    return _write_zip(path, {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": container,
        "OEBPS/content.opf": opf,
        "OEBPS/text/ch1.xhtml": ch1,
        "OEBPS/text/ch2.xhtml": ch2,
    })


class _TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)


class TestDocx(_TmpDirCase):
    def test_paragraphs_tab_and_table(self):
        text = extract_document(make_docx(self.path("a.docx")))
        lines = text.splitlines()
        self.assertIn("First paragraph", lines)
        self.assertIn("Name\tValue", lines)
        self.assertIn("a | b", lines)
        self.assertIn("c | d", lines)
        self.assertIn("Kanji", lines)

    def test_phonetic_ruby_text_is_skipped(self):
        text = extract_document(make_docx(self.path("a.docx")))
        self.assertNotIn("kanji-reading", text)

    def test_blank_paragraph_runs_collapse(self):
        text = extract_document(make_docx(self.path("a.docx")))
        self.assertNotIn("\n\n\n", text)
        self.assertEqual(text, text.strip())

    def test_kind_label(self):
        self.assertEqual(extract_document_kind("x.DOCX"), "DOCX")


class TestXlsx(_TmpDirCase):
    def setUp(self):
        super().setUp()
        self.text = extract_document(make_xlsx(self.path("b.xlsx")))
        self.lines = self.text.splitlines()

    def test_sheet_header_and_values(self):
        self.assertEqual(self.lines[0], "# Sheet: Data")
        self.assertEqual(self.lines[1], "Header\tinline")
        self.assertEqual(self.lines[2], "TRUE\tFALSE\t3.5")

    def test_gap_column_becomes_empty_cell(self):
        self.assertEqual(self.lines[3], "Rich text\t\t42")

    def test_error_cell_and_trailing_empty_row(self):
        self.assertEqual(self.lines[4], "#ERROR")
        self.assertEqual(len(self.lines), 5)

    def test_hidden_and_missing_sheets_are_skipped(self):
        self.assertNotIn("hidden-value", self.text)
        self.assertNotIn("Secret", self.text)
        self.assertNotIn("Ghost", self.text)

    def test_row_cap_appends_marker(self):
        with mock.patch.object(document_extract, "_MAX_SHEET_ROWS", 2):
            text = extract_document(self.path("b.xlsx"))
        self.assertTrue(text.endswith("... [sheet truncated]"))
        self.assertNotIn("Rich text", text)


class TestPptx(_TmpDirCase):
    def test_slides_in_numeric_order(self):
        text = extract_document(make_pptx(self.path("c.pptx")))
        i1, i2, i10 = text.index("# Slide 1"), text.index("# Slide 2"), text.index("# Slide 10")
        self.assertLess(i1, i2)
        self.assertLess(i2, i10)
        self.assertIn("Opening slide", text)
        self.assertIn("Second title\nSecond body", text)
        self.assertNotIn("speaker notes", text)


class TestOdt(_TmpDirCase):
    def test_heading_paragraph_and_table(self):
        text = extract_document(make_odt(self.path("d.odt")))
        lines = text.splitlines()
        self.assertEqual(lines[0], "## Chapter Heading")
        self.assertIn("Hello   world\ttabbed", lines)
        self.assertIn("next line", lines)
        self.assertIn("x | y", lines)


class TestEpub(_TmpDirCase):
    def test_spine_text_title_and_entities(self):
        text = extract_document(make_epub(self.path("e.epub")))
        lines = text.splitlines()
        self.assertEqual(lines[0], "# Test Book")
        self.assertIn("Chapter One", lines)
        self.assertIn("Fish & chips, wrapped across source lines.", lines)
        self.assertIn("Second chapter text.", lines)
        self.assertIn("k1 | v1", lines)
        self.assertNotIn("<", text)
        self.assertNotIn("&amp;", text)
        self.assertNotIn("Ignored head title", text)
        self.assertNotIn("color: red", text)
        self.assertLess(text.index("Chapter One"), text.index("Second chapter"))


class TestErrors(_TmpDirCase):
    def test_bad_zip_mentions_format(self):
        p = self.path("bad.docx")
        with open(p, "wb") as fh:
            fh.write(b"this is not a zip archive")
        with self.assertRaises(DocumentExtractionError) as ctx:
            extract_document(p)
        self.assertIn("DOCX", str(ctx.exception))
        self.assertIn("not a zip archive", str(ctx.exception))

    def test_missing_document_part(self):
        p = _write_zip(self.path("empty.docx"), {"docProps/app.xml": "<x/>"})
        with self.assertRaises(DocumentExtractionError) as ctx:
            extract_document(p)
        self.assertIn("word/document.xml", str(ctx.exception))

    def test_malformed_xml(self):
        p = _write_zip(self.path("broken.pptx"), {"ppt/slides/slide1.xml": "<p:sld"})
        with self.assertRaises(DocumentExtractionError) as ctx:
            extract_document(p)
        self.assertIn("PPTX", str(ctx.exception))

    def test_encrypted_ooxml_package(self):
        p = self.path("locked.xlsx")
        with open(p, "wb") as fh:
            fh.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        with self.assertRaises(DocumentExtractionError) as ctx:
            extract_document(p)
        self.assertIn("password-protected", str(ctx.exception))

    def test_size_cap(self):
        p = make_docx(self.path("a.docx"))
        with (
            mock.patch.object(document_extract, "MAX_DOCUMENT_BYTES", 10),
            self.assertRaises(DocumentExtractionError) as ctx,
        ):
            extract_document(p)
        self.assertIn("Document extraction refused", str(ctx.exception))

    def test_unsupported_extension(self):
        self.assertFalse(is_supported_document("x.txt"))
        self.assertTrue(is_supported_document("Report.XLSX"))
        p = self.path("notes.txt")
        with open(p, "w") as fh:
            fh.write("plain")
        with self.assertRaises(DocumentExtractionError):
            extract_document(p)


class TestTruncation(_TmpDirCase):
    def test_output_cap_marker(self):
        p = make_docx(self.path("a.docx"))
        with mock.patch.object(document_extract, "MAX_EXTRACT_CHARS", 10):
            text = extract_document(p)
        self.assertTrue(text.startswith("First para"))
        self.assertTrue(text.endswith("\n... [truncated: document is longer than 10 characters]"))


class TestToolSurface(_TmpDirCase):
    def test_registered_in_registry(self):
        from tools.registry import ALL_HANDLERS, ALL_TOOLS

        names = {t["function"]["name"] for t in ALL_TOOLS}
        self.assertIn("read_document", names)
        self.assertIn("read_document", ALL_HANDLERS)

    def test_read_file_routes_docx(self):
        from skills.filesystem import read_file

        p = make_docx(self.path("a.docx"))
        out = read_file(p)
        self.assertTrue(out.startswith("DOCX:"), out[:200])
        self.assertIn("a | b", out)

    def test_read_document_handler(self):
        from skills.filesystem import read_document

        out = read_document(make_xlsx(self.path("b.xlsx")))
        self.assertTrue(out.startswith("XLSX:"), out[:200])
        self.assertIn("# Sheet: Data", out)

        bad = self.path("bad.epub")
        with open(bad, "wb") as fh:
            fh.write(b"nope")
        self.assertTrue(read_document(bad).startswith("ERROR reading EPUB:"))

        txt = self.path("notes.txt")
        with open(txt, "w") as fh:
            fh.write("plain")
        self.assertTrue(read_document(txt).startswith("ERROR: unsupported document type '.txt'"))


if __name__ == "__main__":
    unittest.main()
