"""ask_user asks structured questions and reports how the wait ended.

Before this, a model facing an ambiguous request either guessed or ended the
turn with prose questions. utils.clarify holds the channel-agnostic half — the
question shape, the surface handler registry and the bounded wait — while the
CLI and the Telegram bot only render a handler. These tests pin the parts the
agent loop depends on: what the model gets back when nobody answers (a usable
JSON result, never a hang or an exception), and how answers are cleaned.
"""
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core
from tools.registry import ALL_HANDLERS, ALL_TOOLS
from utils.clarify import (
    GATEWAY,
    MAX_CHOICE_CHARS,
    MAX_CHOICES,
    MAX_QUESTIONS,
    ClarifyPolicy,
    ClarifyReply,
    build_result,
    mark_recommended,
    normalize_questions,
    strip_recommended,
)


@pytest.fixture(autouse=True)
def _clean_gateway():
    """No state leaks between tests: fresh handler registry and pending map."""
    GATEWAY.reset()
    yield
    GATEWAY.reset()


# ─── Normalization ────────────────────────────────────────────────────────────

def test_normalize_assigns_qids_and_marks_first_choice():
    normalized, error = normalize_questions([
        {"question": "Which database?", "choices": [" SQLite ", "Postgres"]},
        {"question": "Why?"},
    ])
    assert error is None
    assert [q["qid"] for q in normalized] == ["q0", "q1"]
    assert normalized[0]["choices"] == ["SQLite (Recommended)", "Postgres"]
    assert normalized[0]["choices_offered"] == ["SQLite", "Postgres"]
    assert normalized[0]["multi_select"] is False
    assert normalized[1]["choices"] is None


def test_multi_select_needs_choices_to_be_true():
    normalized, _ = normalize_questions([{"question": "Pick", "multi_select": True}])
    assert normalized[0]["multi_select"] is False
    normalized, _ = normalize_questions([
        {"question": "Pick", "choices": ["a", "b"], "multi_select": True},
    ])
    assert normalized[0]["multi_select"] is True


def test_choices_are_capped_and_blanks_dropped():
    normalized, _ = normalize_questions([
        {"question": "Pick", "choices": [" ", "a", "", "b", "c", "d", "e"]},
    ])
    assert len(normalized[0]["choices_offered"]) == MAX_CHOICES
    assert normalized[0]["choices_offered"] == ["a", "b", "c", "d"]


@pytest.mark.parametrize("questions", [
    [],
    "not a list",
    [{"question": "ok"}, {"question": "  "}],
    [{"question": "x", "choices": "a,b"}],
    [{"question": "x", "choices": [1, 2]}],
    ["bare string"],
])
def test_normalize_rejects_bad_input(questions):
    normalized, error = normalize_questions(questions)
    assert normalized is None
    assert error and isinstance(error, str)


def test_normalize_rejects_too_many_questions():
    _, error = normalize_questions([{"question": f"q{i}"} for i in range(MAX_QUESTIONS + 1)])
    assert str(MAX_QUESTIONS) in error


def test_normalize_rejects_all_blank_choices():
    _, error = normalize_questions([{"question": "x", "choices": ["", " "]}])
    assert "blank" in error


def test_normalize_rejects_over_long_choice_with_index_and_limit():
    _, error = normalize_questions([
        {"question": "x", "choices": ["fine", "y" * (MAX_CHOICE_CHARS + 1)]},
    ])
    assert "choices[1]" in error and str(MAX_CHOICE_CHARS) in error


# ─── Labels ───────────────────────────────────────────────────────────────────

def test_recommended_label_is_idempotent_and_needs_two_choices():
    assert mark_recommended(["only"]) == ["only"]
    marked = mark_recommended(["a", "b"])
    assert marked == ["a (Recommended)", "b"]
    assert mark_recommended(marked) == marked
    assert strip_recommended("a (Recommended)") == "a"
    assert strip_recommended(strip_recommended("a (Recommended)")) == "a"


# ─── Gateway ──────────────────────────────────────────────────────────────────

def _result(text):
    payload = json.loads(text)
    assert "responses" in payload or "error" in payload
    return payload


def test_no_handler_is_undelivered_not_an_error():
    payload = _result(GATEWAY.ask([{"question": "Continue?", "choices": ["yes", "no"]}]))
    assert payload["outcome"] == "undelivered"
    assert payload["notice"]
    assert [r["status"] for r in payload["responses"]] == ["unanswered"]
    assert payload["responses"][0]["user_response"] is None


def test_invalid_questions_report_the_shape():
    payload = _result(GATEWAY.ask([]))
    assert payload["outcome"] == "invalid"
    assert "questions" in payload["error"]


def test_handler_resolving_returns_cleaned_answer():
    def handler(request):
        assert request.questions[0]["qid"] == "q0"
        answered = threading.Timer(
            0.05, GATEWAY.resolve, args=(request.request_id, ClarifyReply.submitted({"q0": "SQLite"}))
        )
        answered.start()

    GATEWAY.set_handler(handler, owner="test")
    payload = _result(GATEWAY.ask(
        [{"question": "Which database?", "choices": ["SQLite", "Postgres"]}],
        policy=ClarifyPolicy(timeout_seconds=5),
    ))
    assert payload["outcome"] == "submitted"
    assert payload["responses"][0]["status"] == "answered"
    assert payload["responses"][0]["user_response"] == "SQLite"  # label stripped
    assert GATEWAY.pending_count() == 0


def test_handler_returning_a_reply_resolves_immediately():
    GATEWAY.set_handler(lambda request: ClarifyReply.submitted({"q0": "a"}))
    payload = _result(GATEWAY.ask(
        [{"question": "Pick", "choices": ["a", "b"]}],
        policy=ClarifyPolicy(timeout_seconds=5),
    ))
    assert payload["outcome"] == "submitted"
    assert payload["responses"][0]["user_response"] == "a"


def test_silent_handler_times_out_fast():
    GATEWAY.set_handler(lambda request: None)
    started = time.monotonic()
    payload = _result(GATEWAY.ask([{"question": "Hi?"}], policy=ClarifyPolicy(timeout_seconds=0.3)))
    elapsed = time.monotonic() - started
    assert payload["outcome"] == "timed_out"
    assert elapsed < 2.0
    assert GATEWAY.pending_count() == 0


def test_cancel_check_ends_the_wait():
    GATEWAY.set_handler(lambda request: None)
    payload = _result(GATEWAY.ask(
        [{"question": "Hi?"}],
        policy=ClarifyPolicy(timeout_seconds=30),
        cancel_check=lambda: True,
    ))
    assert payload["outcome"] == "cancelled"


def test_raising_handler_is_undelivered():
    def handler(request):
        raise RuntimeError("surface exploded")

    GATEWAY.set_handler(handler)
    payload = _result(GATEWAY.ask([{"question": "Hi?"}], policy=ClarifyPolicy(timeout_seconds=5)))
    assert payload["outcome"] == "undelivered"
    assert "surface exploded" in payload["notice"] or payload["notice"]


def test_disabled_policy_never_asks():
    calls = []
    GATEWAY.set_handler(lambda request: calls.append(request))

    payload = _result(GATEWAY.ask([{"question": "Hi?"}], policy=ClarifyPolicy(enabled=False)))
    assert payload["outcome"] == "undelivered"
    assert calls == []


def test_resolve_unknown_request_returns_false():
    assert GATEWAY.resolve("nope", ClarifyReply.submitted({"q0": "x"})) is False


def test_clear_handler_is_owner_scoped():
    GATEWAY.set_handler(lambda request: None, owner="cli")
    assert GATEWAY.clear_handler("telegram:1") is False
    assert GATEWAY.has_handler() is True
    assert GATEWAY.clear_handler("cli") is True
    assert GATEWAY.has_handler() is False


# ─── Statuses ─────────────────────────────────────────────────────────────────

def test_skipped_vs_unanswered():
    normalized, _ = normalize_questions([
        {"question": "one", "choices": ["a", "b"]},
        {"question": "two"},
        {"question": "three"},
    ])
    payload = json.loads(build_result(normalized, ClarifyReply.submitted({"q0": "", "q1": "because"})))
    statuses = [r["status"] for r in payload["responses"]]
    assert statuses == ["skipped", "answered", "unanswered"]
    assert payload["responses"][1]["user_response"] == "because"


def test_multi_select_accepts_json_array_and_plain_string():
    normalized, _ = normalize_questions([
        {"question": "pick", "choices": ["a", "b", "c"], "multi_select": True},
    ])
    from_array = json.loads(build_result(normalized, ClarifyReply.submitted(
        {"q0": '["a", "c (Recommended)"]'})))
    assert from_array["responses"][0]["user_response"] == ["a", "c"]

    from_string = json.loads(build_result(normalized, ClarifyReply.submitted({"q0": "b"})))
    assert from_string["responses"][0]["user_response"] == ["b"]


# ─── Policy ───────────────────────────────────────────────────────────────────

def test_policy_defaults_and_garbage_config():
    default = ClarifyPolicy()
    assert (default.enabled, default.timeout_seconds, default.allow_other) == (True, 300.0, True)
    assert ClarifyPolicy.from_config({}) == default
    assert ClarifyPolicy.from_config(None) == default
    garbage = ClarifyPolicy.from_config({"clarify": {"timeout_seconds": "nonsense", "enabled": "no"}})
    assert garbage.timeout_seconds == 300.0
    assert garbage.enabled is False


# ─── Tool registration ────────────────────────────────────────────────────────

def test_ask_user_is_registered_and_requires_questions():
    from skills.clarify import HANDLERS, TOOL_DEFINITIONS, ask_user

    definition = next(d for d in TOOL_DEFINITIONS if d["name"] == "ask_user")
    assert definition["parameters"]["required"] == ["questions"]
    assert HANDLERS["ask_user"] is ask_user
    assert "ask_user" in ALL_HANDLERS
    assert any(t["function"]["name"] == "ask_user" for t in ALL_TOOLS)


def test_ask_user_is_a_core_tool():
    assert "ask_user" in core._CORE_TOOL_NAMES


def test_ask_user_tool_call_returns_json_without_a_surface():
    from skills.clarify import ask_user

    payload = json.loads(ask_user([{"question": "Continue?", "choices": ["yes", "no"]}]))
    assert payload["outcome"] == "undelivered"


# ─── Telegram surface (import + resolution path, no network) ──────────────────

def test_telegram_callback_resolution_maps_the_offered_choice():
    from bots import telegram_clarify

    telegram_clarify._reset_for_tests()
    seen = {}

    def _capture(req):
        seen["request"] = req

    GATEWAY.set_handler(_capture, owner="test")
    box = {}

    def _ask():
        box["payload"] = GATEWAY.ask(
            [{"question": "Ship it?", "choices": ["yes", "no"]}],
            policy=ClarifyPolicy(timeout_seconds=5),
        )

    thread = threading.Thread(target=_ask, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while "request" not in seen and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "request" in seen

    request = seen["request"]
    entry = request.questions[0]
    telegram_clarify._pending[request.request_id] = telegram_clarify._PendingAsk(
        chat_id=1, question=entry, other_count=0, bot=None, loop=None,
    )

    text = telegram_clarify.resolve_from_callback(request.request_id, entry["qid"], "0")
    assert text and "yes" in text
    assert telegram_clarify._pending == {}

    thread.join(timeout=5)
    payload = json.loads(box["payload"])
    assert payload["outcome"] == "submitted"
    assert payload["responses"][0]["user_response"] == "yes"


def test_telegram_callback_for_expired_request_returns_none():
    from bots import telegram_clarify

    telegram_clarify._reset_for_tests()
    assert telegram_clarify.resolve_from_callback("gone", "q0", "0") is None


# ─── CLI surface (import only; the terminal itself is not scriptable) ─────────

def test_cli_handler_install_and_owner():
    from cli.clarify_cli import install_clarify_handler

    install_clarify_handler()
    assert GATEWAY.has_handler()
    assert GATEWAY.owner() == "cli"
