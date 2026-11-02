"""Tests for the bounded user-profile block and unique note keys (K-17)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills import shared_memory, user_profile
from skills.user_profile import ProfileLimits


@pytest.fixture(autouse=True)
def _profile_db(tmp_path, monkeypatch):
    monkeypatch.setattr(user_profile, "_load_limits", lambda: ProfileLimits())
    shared_memory.init_db(str(tmp_path / "k17.db"))
    yield
    shared_memory._db_path = ""


def _store(kind: str, n: int, value: str) -> None:
    # Explicit keys + increasing timestamps keep the ordering deterministic.
    shared_memory.memory_store(f"user.{kind}.{n:04d}", value, tags=f"user,{kind}", source="user")
    with shared_memory._conn() as conn:
        conn.execute("UPDATE shared_memory SET updated_at=? WHERE key=?", (1000.0 + n, f"user.{kind}.{n:04d}"))


def _lines(block: str, prefix: str) -> list[str]:
    return [line for line in block.splitlines() if line.startswith(prefix)]


def test_empty_db_returns_empty_string():
    assert user_profile.get_user_context() == ""


def test_fifty_notes_capped_with_omitted_marker():
    for i in range(50):
        _store("note", i, f"note {i}")
    block = user_profile.get_user_context()
    notes = [line for line in _lines(block, "- note ")]
    assert len(notes) == 20
    assert notes[0] == "- note 49"  # newest first
    assert "- (… 30 older notes omitted)" in block


def test_singular_marker():
    for i in range(3):
        _store("rule", i, f"rule {i}")
    block = user_profile.get_user_context(limits=ProfileLimits(max_rules=2))
    assert "- (… 1 older rule omitted)" in block


def test_entry_truncation():
    _store("note", 1, "x" * 1000)
    block = user_profile.get_user_context(limits=ProfileLimits(max_entry_chars=50))
    line = _lines(block, "- x")[0]
    assert line == "- " + "x" * 49 + "…"


def test_duplicate_rules_collapse():
    _store("rule", 1, "Always answer in Turkish")
    _store("rule", 2, "  always   answer in TURKISH ")
    _store("rule", 3, "Use metric units")
    block = user_profile.get_user_context()
    assert len(_lines(block, "- ")) == 2
    assert "omitted" not in block


def test_max_chars_budget_respected():
    for i in range(20):
        _store("rule", i, f"rule {i} " + "r" * 200)
    for i in range(20):
        _store("note", i, f"note {i} " + "n" * 200)
    limits = ProfileLimits(max_chars=1000)
    block = user_profile.get_user_context(limits=limits)
    assert len(block) <= limits.max_chars  # marker overhead is budgeted too
    assert block.startswith("## User Rules")
    assert "older rules omitted" in block
    assert "older notes omitted" in block


def test_degenerate_budget_emits_no_empty_header():
    _store("note", 1, "note one")
    # Too small for the header, one entry and the marker: nothing is injected.
    assert user_profile.get_user_context(limits=ProfileLimits(max_chars=5)) == ""


def test_rules_fill_before_notes():
    _store("note", 1, "a note")
    _store("rule", 0, "a rule")
    block = user_profile.get_user_context()
    assert block.index("- a rule") < block.index("- a note")


def test_injected_limits_override_config(monkeypatch):
    monkeypatch.setattr(user_profile, "_load_limits", lambda: ProfileLimits(max_notes=50))
    for i in range(10):
        _store("note", i, f"note {i}")
    assert len(_lines(user_profile.get_user_context(), "- note ")) == 10
    block = user_profile.get_user_context(limits=ProfileLimits(max_notes=3))
    assert len(_lines(block, "- note ")) == 3
    assert "- (… 7 older notes omitted)" in block


def test_profile_limits_from_config():
    default = ProfileLimits()
    assert ProfileLimits.from_config({}) == default
    assert ProfileLimits.from_config({"memory": {"user_profile": None}}) == default
    limits = ProfileLimits.from_config(
        {"memory": {"user_profile": {"max_rules": "5", "max_notes": 0, "max_chars": 500}}}
    )
    assert limits == ProfileLimits(max_rules=20, max_notes=1, max_chars=500)


def test_same_second_notes_get_unique_keys(monkeypatch):
    monkeypatch.setattr(user_profile.time, "time", lambda: 1_700_000_000.0)
    user_profile.user_note_add("first")
    user_profile.user_note_add("second")
    user_profile.user_rule_add("rule one")
    user_profile.user_rule_add("rule two")
    with shared_memory._conn() as conn:
        keys = [r["key"] for r in conn.execute("SELECT key FROM shared_memory ORDER BY id")]
    assert keys == [
        "user.note.1700000000000",
        "user.note.1700000000000-2",
        "user.rule.1700000000000",
        "user.rule.1700000000000-2",
    ]


def test_thirty_rapid_notes_all_survive():
    for i in range(30):
        user_profile.user_note_add(f"observation {i}")
    with shared_memory._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM shared_memory").fetchone()[0] == 30


def test_profile_list_newest_first():
    _store("note", 1, "older")
    _store("note", 2, "newer")
    out = user_profile.user_profile_list()
    assert out.index("newer") < out.index("older")
