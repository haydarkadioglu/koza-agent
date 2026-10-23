"""Behavioral coverage for deterministic recovery from provider context overflows."""

import os
import sys
import threading
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Agent, ToolLoopGuardrail
from providers.error_classifier import (
    FailoverReason,
    classify_api_error,
    is_context_overflow,
)
from utils.overflow_recovery import (
    DEFAULT_KEEP_RECENT_MESSAGES,
    OverflowRecoveryPolicy,
    shrink_messages,
)


def _assert_tool_pairs_are_complete(messages):
    call_ids = set()
    result_ids = set()
    for message in messages:
        if message.get("role") == "assistant":
            call_ids.update(
                call["id"] for call in message.get("tool_calls", [])
            )
        elif message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            assert call_id in call_ids
            result_ids.add(call_id)
    assert result_ids <= call_ids
    assert call_ids <= result_ids


def test_shrink_elides_middle_preserves_system_and_tail_without_mutating_input():
    messages = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "old answer"},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}}
            ],
        },
        {"role": "assistant", "content": "recent answer"},
    ]
    original = deepcopy(messages)

    shortened, changed = shrink_messages(messages, keep_recent_messages=2)

    assert changed is True
    assert messages == original
    assert shortened[0] == original[0]
    assert shortened[-2:] == original[-2:]
    assert any(
        message.get("role") == "assistant"
        and "[context recovery]" in message.get("content", "")
        for message in shortened
    )
    shortened[0]["content"] = "edited"
    shortened[-2]["content"][0]["image_url"]["url"] = "edited"
    assert messages == original


def test_short_history_is_returned_unchanged():
    messages = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "hello"},
    ]

    shortened, changed = shrink_messages(messages, keep_recent_messages=2)

    assert changed is False
    assert shortened is messages
    assert shortened == messages


def test_shrink_drops_unpaired_tool_calls_and_results():
    cases = [
        [
            {"role": "system", "content": "policy"},
            {"role": "user", "content": "request"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-old", "type": "function"}],
            },
            {"role": "tool", "tool_call_id": "call-old", "content": "result"},
        ],
        [
            {"role": "system", "content": "policy"},
            {"role": "tool", "tool_call_id": "call-old", "content": "result"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-old", "type": "function"}],
            },
        ],
    ]

    for messages in cases:
        shortened, changed = shrink_messages(messages, keep_recent_messages=1)
        assert changed is True
        _assert_tool_pairs_are_complete(shortened)


def test_classifier_distinguishes_context_overflow_from_max_tokens_validation():
    invalid_setting = classify_api_error(
        ValueError("max_tokens must be greater than 0")
    )
    overflow = classify_api_error(
        RuntimeError("This model's maximum context length is 128000 tokens")
    )

    assert invalid_setting.reason != FailoverReason.context_overflow
    assert overflow.reason == FailoverReason.context_overflow
    assert overflow.retryable is False
    assert not is_context_overflow(
        ValueError("max_tokens must be greater than 0")
    )
    assert is_context_overflow(
        RuntimeError("This model's maximum context length is 128000 tokens")
    )


class _OverflowProvider:
    name = "test"
    _model = "test-model"
    supports_vision = False
    supports_thinking = False

    def __init__(self):
        self.calls = 0

    def stream_chat(self, messages, tools=None, cancel_event=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(
                "This model's maximum context length is 128000 tokens"
            )
        yield "Recovered answer"


def _overflow_agent():
    agent = Agent.__new__(Agent)
    agent.provider = _OverflowProvider()
    agent.messages = [
        {"role": "system", "content": "policy"},
        *[
            {"role": role, "content": f"history {index}"}
            for index in range(10)
            for role in ("user", "assistant")
        ],
    ]
    agent._cancel = threading.Event()
    agent._busy = False
    agent._router = None
    agent._guardrail = ToolLoopGuardrail()
    agent.permission_callback = None
    agent.tool_progress_callback = None
    agent._pre_fetch_links = lambda _user_input: iter(())
    agent._refresh_memory_context = lambda *_args, **_kwargs: None
    agent._resolve_available_tools = lambda *_args, **_kwargs: []
    agent._maybe_compress_context = lambda: None
    return agent


def test_conversation_loop_shortens_and_retries_after_overflow():
    agent = _overflow_agent()

    events = list(agent._run_conversation_loop("hi"))

    assert agent.provider.calls == 2
    assert sum(event.get("type") == "status" for event in events) == 1
    assert "".join(
        event.get("token", "") for event in events if event.get("type") == "text"
    ) == "Recovered answer"
    assert not any(event.get("type") == "error" for event in events)


def test_conversation_loop_reports_actionable_error_after_retry_is_rejected():
    agent = _overflow_agent()
    agent.provider.stream_chat = lambda *_args, **_kwargs: _overflow_forever()

    events = list(agent._run_conversation_loop("hi"))

    errors = [event for event in events if event.get("type") == "error"]
    assert len(errors) == 1
    assert errors[0]["message"].startswith(
        "The conversation no longer fits the model's context window"
    )
    assert errors[0]["message"].endswith(
        "This model's maximum context length is 128000 tokens"
    )


def _overflow_forever():
    raise RuntimeError("This model's maximum context length is 128000 tokens")
    yield  # Make this a generator so the provider call raises during iteration.


def test_policy_defaults_disable_and_rejects_invalid_types():
    default = OverflowRecoveryPolicy.from_config({})
    disabled = OverflowRecoveryPolicy.from_config(
        {"context_overflow": {"enabled": False}}
    )
    invalid = OverflowRecoveryPolicy.from_config(
        {
            "context_overflow": {
                "enabled": "false",
                "max_retries": "many",
                "keep_recent_messages": None,
            }
        }
    )

    assert default.enabled is True
    assert default.max_retries == 1
    assert default.keep_recent_messages == DEFAULT_KEEP_RECENT_MESSAGES
    assert disabled.enabled is False
    assert disabled.max_retries == 0
    assert invalid == default


def test_shrink_never_flattens_multimodal_content_of_a_neighbour():
    messages = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "old answer"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "recent"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}},
            ],
        },
        {"role": "user", "content": "last"},
    ]
    original = deepcopy(messages)

    shortened, changed = shrink_messages(messages, keep_recent_messages=2)

    assert changed is True
    assert messages == original
    rich = next(
        message
        for message in shortened
        if isinstance(message.get("content"), list)
    )
    assert rich == original[3], "rich content must survive untouched"
    note_index = next(
        index
        for index, message in enumerate(shortened)
        if "[context recovery]" in str(message.get("content", ""))
    )
    # The note is its own message and does not repeat the neighbour's role.
    assert shortened[note_index]["role"] == "user"
    assert shortened[note_index + 1]["role"] == "assistant"
