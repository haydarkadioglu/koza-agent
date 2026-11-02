"""Tests for secret redaction at the working-memory write choke point (K-25).

Working memory is injected into the system prompt every turn, so a secret stored
here would be resent to the model provider and saved with sessions.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import default_config
from skills import working_memory
from tools.middleware import logging_middleware
from utils import redact

OPENAI_KEY = "sk-" + "abcdefghijklmnopqrstuvwxyz0123456789"
BEARER_TOKEN = "opaque9token8value7with6no5known4prefix"
MASKED_OPENAI_KEY = "sk-abc...6789"


@pytest.fixture(autouse=True)
def _memory_db():
    working_memory.init_db(":memory:")
    working_memory.wm_clear()
    working_memory.set_redaction_enabled(True)
    yield
    working_memory.set_redaction_enabled(True)
    working_memory.wm_clear()


def _newest_row():
    with working_memory._conn() as conn:
        return conn.execute(
            "SELECT summary, detail FROM working_memory ORDER BY id DESC LIMIT 1"
        ).fetchone()


def test_openai_key_in_summary_is_masked():
    working_memory.wm_add(summary=f"call(key {OPENAI_KEY})")

    row = _newest_row()
    assert OPENAI_KEY not in row["summary"]
    assert MASKED_OPENAI_KEY in row["summary"]


def test_bearer_token_in_detail_is_masked():
    # Build the header by concatenation so no tool-side redactor rewrites the literal.
    detail = "Authorization: Bearer " + BEARER_TOKEN
    working_memory.wm_add(summary="request", detail=detail)

    row = _newest_row()
    assert BEARER_TOKEN not in row["detail"]
    assert row["detail"] == "Authorization: Bearer " + BEARER_TOKEN[:6] + "..." + BEARER_TOKEN[-4:]


def test_plain_text_round_trips_unchanged():
    working_memory.wm_add(summary="read_file(path=/root/x.py)", detail="token_count=42")

    row = _newest_row()
    assert row["summary"] == "read_file(path=/root/x.py)"
    assert row["detail"] == "token_count=42"


def test_logging_middleware_stores_no_raw_secret(monkeypatch):
    # Wrap rather than replace wm_add: redaction lives inside it, so a stub would
    # only ever see the unredacted arguments.
    entries = []
    real_wm_add = working_memory.wm_add

    def spy(**kwargs):
        entries.append(kwargs)
        return real_wm_add(**kwargs)

    monkeypatch.setattr(working_memory, "wm_add", spy)

    args = {"url": "https://api.example.com/v1", "api_key": OPENAI_KEY}
    result = logging_middleware(None, "http_request", args, lambda a: f"echo {OPENAI_KEY}")

    assert result == f"echo {OPENAI_KEY}"
    assert OPENAI_KEY[:12] in entries[0]["summary"]
    assert OPENAI_KEY in entries[0]["detail"]

    row = _newest_row()
    assert OPENAI_KEY[:12] not in row["summary"]
    assert OPENAI_KEY not in row["detail"]
    assert MASKED_OPENAI_KEY in row["detail"]


def test_opt_out_stores_raw_text():
    working_memory.set_redaction_enabled(False)

    working_memory.wm_add(summary=f"call(key {OPENAI_KEY})", detail=OPENAI_KEY)

    row = _newest_row()
    assert OPENAI_KEY in row["summary"]
    assert row["detail"] == OPENAI_KEY


def test_redactor_failure_still_writes_the_row(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("redactor bug")

    monkeypatch.setattr(working_memory, "redact_sensitive_text", boom)

    assert working_memory.wm_add(summary="kept", detail="also kept") == "Working memory event added."

    row = _newest_row()
    assert row["summary"] == "kept"
    assert row["detail"] == "also kept"


def test_secret_is_masked_before_truncation():
    # The raw key straddles the 200-char cut; sliced first, too little would remain to match.
    working_memory.wm_add(summary="x" * 188 + " " + OPENAI_KEY)

    summary = _newest_row()["summary"]
    assert len(summary) <= 200
    assert OPENAI_KEY[:11] not in summary


def test_logging_env_switch_does_not_disable_redaction(monkeypatch):
    monkeypatch.setattr(redact, "_REDACT_ENABLED", False)

    working_memory.wm_add(summary=f"call(key {OPENAI_KEY})")

    assert OPENAI_KEY not in _newest_row()["summary"]


def test_config_default_is_on():
    assert default_config()["security"]["redact_secrets"] is True
