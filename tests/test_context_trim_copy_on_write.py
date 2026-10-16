"""``ContextWindow.trim()`` must not rewrite the stored conversation.

``trim()`` is a per-call projection: it slices the window, truncates long tool
results and merges consecutive user turns. Every one of those passes used to edit
the *stored* message dicts in place, so the first trim permanently truncated a
12 KB tool result to 4 KB (and re-truncated the already-truncated text on every
following turn) and permanently welded two consecutive user turns into one
message. The stored history is the only record of the conversation, so that loss
was unrecoverable. Trimming is now copy-on-write.
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core_context import MAX_TOOL_RESULT_CHARS, ContextWindow

BIG_TOOL_RESULT = "x" * 12_000


class _StubProvider:
    name = "stub"
    model = "stub-model"


def _history() -> list[dict]:
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "first question"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "name": "read_file", "arguments": {"path": "a.py"}}
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "read_file",
            "content": BIG_TOOL_RESULT,
        },
        {"role": "assistant", "content": "done with that"},
        {"role": "user", "content": "second question"},
        {"role": "user", "content": "third question"},
    ]


def _window() -> ContextWindow:
    ctx = ContextWindow(_StubProvider())
    ctx.messages = _history()
    return ctx


def _tool_contents(messages: list[dict]) -> list[str]:
    return [
        m["content"] for m in messages if m.get("role") == "tool"
    ]


def test_trim_leaves_stored_history_untouched():
    ctx = _window()
    before = copy.deepcopy(ctx.messages)

    ctx.trim()
    ctx.trim()  # a second turn used to re-truncate the already-truncated text

    assert ctx.messages == before


def test_stored_tool_result_keeps_full_length():
    ctx = _window()

    window = ctx.trim()

    assert len(ctx.messages[3]["content"]) == len(BIG_TOOL_RESULT)
    assert ctx.messages[3]["content"] == BIG_TOOL_RESULT
    # ...while the window handed to the provider is truncated.
    assert len(_tool_contents(window)[0]) < MAX_TOOL_RESULT_CHARS + 100
    assert "truncated" in _tool_contents(window)[0]


def test_repeated_trims_return_the_same_window():
    ctx = _window()

    first = ctx.trim()
    second = ctx.trim()

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_consecutive_user_turns_merge_per_call_only():
    ctx = _window()

    window = ctx.trim()

    users = [m["content"] for m in window if m.get("role") == "user"]
    assert users == ["first question", "second question\n\nthird question"]
    # Stored history still has the two turns as separate messages.
    stored_users = [m["content"] for m in ctx.messages if m.get("role") == "user"]
    assert stored_users == ["first question", "second question", "third question"]


def test_window_does_not_alias_stored_dicts():
    ctx = _window()

    window = ctx.trim()

    stored_ids = {id(m) for m in ctx.messages}
    assert not (stored_ids & {id(m) for m in window})
    # Mutating a returned message cannot reach the stored history.
    window[1]["content"] = "OVERWRITTEN"
    assert ctx.messages[1]["content"] == "first question"


def test_nested_lists_are_copied_too():
    ctx = ContextWindow(_StubProvider())
    ctx.messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": [{"type": "text", "text": "look at this"}]},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {}}],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "ok"},
    ]
    stored_content_list = ctx.messages[1]["content"]
    stored_tool_calls = ctx.messages[2]["tool_calls"]

    window = ctx.trim(provider_supports_vision=False)

    assert ctx.messages[1]["content"] is stored_content_list
    assert ctx.messages[2]["tool_calls"] is stored_tool_calls
    tool_msg = next(m for m in window if m.get("role") == "tool")
    assert tool_msg["content"] == "ok"
