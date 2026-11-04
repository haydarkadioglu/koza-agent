"""Tests for relevance-ranked shared-memory recall (K-17)."""
import os
import re
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills import shared_memory
from utils.memory_retrieval import (
    RecallPolicy,
    build_fts_query,
    build_like_patterns,
    rank_memories,
    score_memory,
    tokenize_query,
)

NL_QUERY = "what are my preferences for code comments?"


@pytest.fixture(autouse=True)
def _memory_db(tmp_path, monkeypatch):
    monkeypatch.setattr(shared_memory, "_recall_policy", lambda: RecallPolicy())
    shared_memory.init_db(str(tmp_path / "k17.db"))
    shared_memory.memory_store("deploy.host", "Production deploys go to 10.0.0.5", tags="ops", source="user")
    shared_memory.memory_store(
        "pref.comments", "User prefers docstring comments in Python, no inline noise",
        tags="code", source="agent",
    )
    shared_memory.memory_store("misc.todo", "Buy milk", tags="random", source="agent")
    yield
    shared_memory._db_path = ""


def _keys(block: str) -> list[str]:
    return re.findall(r"^- \[([^\]]+)\]", block, re.MULTILINE)


def test_natural_language_query_surfaces_on_topic_row_first():
    block = shared_memory.get_relevant_context(NL_QUERY, limit=5)
    keys = _keys(block)
    assert keys[0] == "pref.comments"
    assert "misc.todo" not in keys


def test_zero_overlap_query_injects_nothing():
    assert shared_memory.get_relevant_context("kubernetes cluster upgrade", limit=5) == ""


def test_keyword_query_ranks_exact_key_hit_first():
    shared_memory.memory_store("notes.misc", "the deploy pipeline is slow", tags="", source="agent")
    keys = _keys(shared_memory.get_relevant_context("deploy host", limit=5))
    assert keys[0] == "deploy.host"


def test_stopword_only_query_falls_back_to_recency():
    block = shared_memory.get_relevant_context("what is the", limit=5)
    assert _keys(block)[0] == "misc.todo"


def test_build_fts_query_is_quoted_ored_and_safe():
    terms = tokenize_query('deploy? "host" -cluster (upgrade) OR NOT')
    query = build_fts_query(terms)
    assert query == '"deploy"* OR "host"* OR "cluster"* OR "upgrade"*'
    # Must be valid FTS5 syntax.
    with shared_memory._conn() as conn:
        conn.execute("SELECT rowid FROM shared_memory_fts WHERE shared_memory_fts MATCH ?", (query,)).fetchall()
    # Unsafe terms are never emitted, even if passed directly.
    assert build_fts_query(['a"b', "x OR y", "(z)", ""]) == ""
    assert build_like_patterns(["deploy", "bad%"]) == ["%deploy%"]


def test_tokenize_query_handles_turkish_and_empty():
    assert tokenize_query(None) == []
    assert tokenize_query("") == []
    assert tokenize_query("bu ne için benim") == []
    assert tokenize_query("Kod yorumları için tercihim nedir?") == ["kod", "yorumları", "tercihim"]
    assert len(tokenize_query(" ".join(f"word{i}" for i in range(30)), max_terms=12)) == 12


def test_score_and_rank_are_deterministic():
    assert score_memory("pref.comments", "x", "", ["comments"]) == 6.0
    assert score_memory("k", "comment comment comment comment", "", ["comment"]) == 6.0
    rows = [
        {"key": "b", "value": "alpha", "tags": "", "updated_at": 1.0},
        {"key": "a", "value": "alpha", "tags": "", "updated_at": 1.0},
        {"key": "c", "value": "beta", "tags": "", "updated_at": 9.0},
    ]
    assert [r["key"] for r in rank_memories(rows, ["alpha"], 5)] == ["a", "b"]
    assert [r["key"] for r in rank_memories(rows, [], 2)] == ["b", "a"]


def test_memory_search_finds_natural_language_question():
    out = shared_memory.memory_search(NL_QUERY, limit=5)
    assert out.startswith(f"Found 1 memory for '{NL_QUERY}':\n\n")
    assert "🧠 [pref.comments] (code) [" in out
    assert "misc.todo" not in out


def test_memory_search_no_match_keeps_message():
    q = "kubernetes cluster upgrade"
    assert shared_memory.memory_search(q) == f"No memories found matching '{q}'."


def test_memory_search_short_keyword_still_works():
    shared_memory.memory_store("db.path", "sqlite file", tags="", source="user")
    assert "[db.path]" in shared_memory.memory_search("db")


def test_like_fallback_when_fts_unavailable():
    with shared_memory._conn() as conn:
        conn.execute("DROP TABLE shared_memory_fts")
    keys = _keys(shared_memory.get_relevant_context(NL_QUERY, limit=5))
    assert keys == ["pref.comments"]


def test_recall_policy_from_broken_config_yields_defaults():
    default = RecallPolicy()
    assert RecallPolicy.from_config({}) == default
    assert RecallPolicy.from_config(None) == default
    assert RecallPolicy.from_config({"memory": None}) == default
    assert RecallPolicy.from_config({"memory": {"recall": "yes"}}) == default
    assert RecallPolicy.from_config(
        {"memory": {"recall": {"enabled": "no", "limit": "8", "max_terms": True}}}
    ) == default
    assert RecallPolicy.from_config({"memory": {"recall": {"limit": 0}}}).limit == 8
    assert RecallPolicy.from_config({"memory": {"recall": {"limit": 3}}}).limit == 3


def test_recall_disabled_returns_empty(monkeypatch):
    policy = RecallPolicy.from_config({"memory": {"recall": {"enabled": False}}})
    monkeypatch.setattr(shared_memory, "_recall_policy", lambda: policy)
    assert shared_memory.get_relevant_context(NL_QUERY) == ""


def test_policy_limit_caps_injection(monkeypatch):
    monkeypatch.setattr(shared_memory, "_recall_policy", lambda: RecallPolicy(limit=1))
    assert len(_keys(shared_memory.get_relevant_context("what is the", limit=8))) == 1


def test_recall_snippets_are_redacted():
    secret = "sk-" + "abcdefghijklmnopqrstuvwxyz0123456789"
    shared_memory.memory_store("openai.setup", f"openai key is {secret}", tags="", source="user")
    block = shared_memory.get_relevant_context("openai setup", limit=5)
    assert "[openai.setup]" in block
    assert secret not in block
    assert "[REDACTED]" in block


def test_db_error_fails_open(monkeypatch):
    def boom():
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(shared_memory, "_conn", boom)
    assert shared_memory.get_relevant_context(NL_QUERY) == ""
