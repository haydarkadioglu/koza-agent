"""koza_edit matches drifting anchors and applies multi-hunk edits all-or-nothing.

patch_file only did an exact str.replace: an anchor with different indentation,
collapsed spaces, an escaped \\n or a typographic dash returned "Pattern not
found" and burned a turn, and an anchor present twice silently edited the first
hit. utils.fuzzy_edit.apply_edit now tries a strategy chain that maps every hit
back to original offsets, refuses ambiguous fuzzy matches, and hints the closest
lines on a miss; koza_edit applies several hunks with one read and one write.
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills.code_tools import HANDLERS, TOOL_DEFINITIONS, koza_edit
from utils.fuzzy_edit import apply_edit


def _write(tmp_path, text, name="mod.py"):
    p = tmp_path / name
    p.write_bytes(text.encode("utf-8"))
    return p


# ─── apply_edit strategies ────────────────────────────────────────────────────

def test_exact_match_reports_exact():
    r = apply_edit("a = 1\nb = 2\n", "b = 2", "b = 3")
    assert r.ok and r.strategy == "exact" and r.replacements == 1
    assert r.content == "a = 1\nb = 3\n"


def test_indentation_drift_keeps_file_indentation():
    content = (
        "class A:\n"
        "    def f(self):\n"
        "        x = 1\n"
        "        return x\n"
        "\n"
        "    def g(self):\n"
        "        return 2\n"
    )
    old = "    x = 1\n    return x"
    new = "    x = 10\n    return x * 2"
    r = apply_edit(content, old, new)
    assert r.ok and r.strategy != "exact"
    assert r.content == (
        "class A:\n"
        "    def f(self):\n"
        "        x = 10\n"
        "        return x * 2\n"
        "\n"
        "    def g(self):\n"
        "        return 2\n"
    )


def test_escaped_newline_literal_matches_real_newlines():
    content = "def f():\n    return 1\n"
    r = apply_edit(content, "def f():\\n    return 1", "def f():\\n    return 2")
    assert r.ok and r.strategy == "escaped_literal"
    assert r.content == "def f():\n    return 2\n"


def test_whitespace_collapse_matches():
    content = "x = foo(a,  b)\ny = 2\n"
    r = apply_edit(content, "x = foo(a, b)", "x = foo(a, c)")
    assert r.ok and r.strategy == "whitespace_collapsed"
    assert r.content == "x = foo(a, c)\ny = 2\n"


def test_unicode_dash_matches_without_shifting_rest_of_file():
    content = "# header — keep\nmsg = 'a — b'\ntail = 'x — y'\n"
    r = apply_edit(content, "msg = 'a -- b'", "msg = 'changed'")
    assert r.ok and r.strategy == "unicode_normalized"
    assert r.content == "# header — keep\nmsg = 'changed'\ntail = 'x — y'\n"


def test_block_anchor_matches_drifted_middle_only():
    content = (
        "def compute(values):\n"
        "    total = 0\n"
        "    for v in values:\n"
        "        total += v * 2\n"
        "    return total\n"
    )
    old = (
        "def compute(values):\n"
        "    total = 0\n"
        "    for v in values:\n"
        "        total += v * 3\n"
        "    return total"
    )
    r = apply_edit(content, old, "def compute(values):\n    return sum(values)")
    assert r.ok and r.strategy == "block_anchor"
    assert r.content == "def compute(values):\n    return sum(values)\n"

    unrelated = (
        "def compute(values):\n"
        "    import socket\n"
        "    conn = socket.create_connection(('h', 1))\n"
        "    conn.sendall(b'payload bytes here')\n"
        "    return total"
    )
    r2 = apply_edit(content, unrelated, "pass")
    assert not r2.ok and r2.content == content


def test_ambiguous_anchor_names_lines_and_leaves_file(tmp_path):
    text = "x = 1\ny = 2\nx = 1\n"
    p = _write(tmp_path, text)
    out = koza_edit(str(p), [{"old_string": "x = 1", "new_string": "x = 9"}])
    assert out.startswith("❌ Edit failed at hunk 1")
    assert "1" in out and "3" in out and "lines 1, 3" in out
    assert p.read_bytes() == text.encode("utf-8")


def test_replace_all_refused_for_similarity_strategy():
    content = "a  =  1\nb = 2\na  =  1\n"
    r = apply_edit(content, "a = 1", "a = 2", replace_all=True)
    assert not r.ok and "replace_all" in r.error and "whitespace_collapsed" in r.error
    assert r.content == content


def test_replace_all_exact_replaces_every_occurrence():
    r = apply_edit("x\ny\nx\n", "x", "z", replace_all=True)
    assert r.ok and r.replacements == 2 and r.content == "z\ny\nz\n"


def test_miss_returns_closest_line_hint():
    content = "alpha = 1\nbeta_value = compute(2)\ngamma = 3\n"
    r = apply_edit(content, "beta_valu = compte(2, 3)", "x")
    assert not r.ok
    assert "Closest lines" in r.error and "L2" in r.error


def test_bad_inputs_are_actionable_and_do_not_modify(tmp_path):
    text = "keep = True\n"
    p = _write(tmp_path, text)
    for old, new in (("", "x"), ("   \n\t", "x"), ("keep = True", "keep = True")):
        r = apply_edit(text, old, new)
        assert not r.ok and r.error and r.content == text
        out = koza_edit(str(p), [{"old_string": old, "new_string": new}])
        assert out.startswith("❌ Edit failed at hunk 1") and "No changes written." in out
        assert p.read_bytes() == text.encode("utf-8")


def test_non_utf8_is_rejected(tmp_path):
    p = tmp_path / "bin.dat"
    p.write_bytes(b"\xff\xfe abc")
    out = koza_edit(str(p), [{"old_string": "abc", "new_string": "def"}])
    assert out.startswith("❌") and "UTF-8" in out
    assert p.read_bytes() == b"\xff\xfe abc"
    assert not apply_edit(b"\xff\xfe", "a", "b").ok


# ─── koza_edit tool ───────────────────────────────────────────────────────────

def test_koza_edit_multi_hunk_single_write(tmp_path):
    p = _write(tmp_path, "def a():\n    return 1\n\ndef b():\n    return 2\n")
    writes = []
    orig_bytes, orig_text = pathlib.Path.write_bytes, pathlib.Path.write_text

    def count_bytes(self, data):
        writes.append(self)
        return orig_bytes(self, data)

    def count_text(self, *a, **k):
        writes.append(self)
        return orig_text(self, *a, **k)

    pathlib.Path.write_bytes, pathlib.Path.write_text = count_bytes, count_text
    try:
        out = koza_edit(str(p), [
            {"old_string": "return 1", "new_string": "return 10"},
            # Sees hunk 1's output and drifts in indentation.
            {"old_string": "  def a():\n      return 10", "new_string": "  def a():\n      return 11"},
            {"old_string": "return 2", "new_string": "return 20"},
        ])
    finally:
        pathlib.Path.write_bytes, pathlib.Path.write_text = orig_bytes, orig_text

    assert out.startswith("✅ Edited mod.py: 3 hunk(s), 3 replacement(s)")
    assert "hunk 2: line_trimmed" in out and "hunk 1:" not in out
    assert len(writes) == 1
    assert p.read_text(encoding="utf-8") == "def a():\n    return 11\n\ndef b():\n    return 20\n"


def test_koza_edit_all_or_nothing(tmp_path):
    text = "one = 1\ntwo = 2\n"
    p = _write(tmp_path, text)
    out = koza_edit(str(p), [
        {"old_string": "one = 1", "new_string": "one = 100"},
        {"old_string": "three = 3", "new_string": "three = 300"},
    ])
    assert out.startswith("❌ Edit failed at hunk 2")
    assert "No changes written." in out
    assert p.read_bytes() == text.encode("utf-8")


def test_koza_edit_dry_run_previews_without_writing(tmp_path):
    text = "value = 'old'\n"
    p = _write(tmp_path, text)
    out = koza_edit(str(p), [{"old_string": "'old'", "new_string": "'new'"}], dry_run=True)
    assert out.startswith("✅ Dry run")
    assert "-value = 'old'" in out and "+value = 'new'" in out
    assert p.read_bytes() == text.encode("utf-8")


def test_koza_edit_missing_file_and_bad_edits(tmp_path):
    out = koza_edit(str(tmp_path / "nope.py"), [{"old_string": "a", "new_string": "b"}])
    assert out.startswith("❌ File not found")
    p = _write(tmp_path, "a\n")
    assert koza_edit(str(p), []).startswith("❌")
    assert koza_edit(str(p), ["not a dict"]).startswith("❌ Edit failed at hunk 1")
    assert p.read_text(encoding="utf-8") == "a\n"


def test_koza_edit_preserves_crlf(tmp_path):
    p = tmp_path / "win.txt"
    p.write_bytes(b"first\r\n    second\r\nthird\r\n")
    out = koza_edit(str(p), [{"old_string": "second\nthird", "new_string": "second\nTHIRD"}])
    assert out.startswith("✅")
    assert p.read_bytes() == b"first\r\n    second\r\nTHIRD\r\n"


def test_koza_edit_registered_and_handler_works(tmp_path):
    assert any(t["name"] == "koza_edit" for t in TOOL_DEFINITIONS)
    p = _write(tmp_path, "k = 1\n")
    out = HANDLERS["koza_edit"](path=str(p), edits=[{"old_string": "k = 1", "new_string": "k = 2"}], dry_run="false")
    assert out.startswith("✅ Edited") and p.read_text(encoding="utf-8") == "k = 2\n"

    from tools.registry import ALL_HANDLERS, ALL_TOOLS
    assert "koza_edit" in ALL_HANDLERS
    assert any(t["function"]["name"] == "koza_edit" for t in ALL_TOOLS)
