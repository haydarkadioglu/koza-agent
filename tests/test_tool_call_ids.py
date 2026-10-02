"""Tool-call id collisions: every tool result must keep its own pairing id.

A provider that reuses one id — or omits it — for several calls in a batch used
to lose results: the id keys the result maps in the parallel dispatch path, so
the second call's result overwrote the first's and both tool messages were
written with the same ``tool_call_id``. The round is now uniquified before
dispatch, and the 400 "dangling tool_calls" recovery only fires when the
history actually has something dangling to repair.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Agent, ToolLoopGuardrail
from utils.tool_ids import uniquify_tool_call_ids

# ── id uniquification ────────────────────────────────────────────────────────


def test_distinct_ids_are_left_alone():
    calls = [{"id": "a", "name": "read_file"}, {"id": "b", "name": "list_dir"}]
    assert uniquify_tool_call_ids(calls) == 0
    assert [c["id"] for c in calls] == ["a", "b"]


def test_duplicate_id_gets_a_deterministic_suffix():
    calls = [{"id": "call_1", "name": "read_file"}, {"id": "call_1", "name": "list_dir"}]
    assert uniquify_tool_call_ids(calls) == 1
    assert [c["id"] for c in calls] == ["call_1", "call_1_d2"]


def test_third_collision_gets_the_next_suffix():
    calls = [{"id": "x", "name": "a"}, {"id": "x", "name": "b"}, {"id": "x", "name": "c"}]
    assert uniquify_tool_call_ids(calls) == 2
    assert [c["id"] for c in calls] == ["x", "x_d2", "x_d3"]


def test_renaming_never_produces_a_collision():
    calls = [{"id": "x", "name": "a"}, {"id": "x", "name": "b"}, {"id": "x_d2", "name": "c"}]
    renamed = uniquify_tool_call_ids(calls)
    ids = [c["id"] for c in calls]
    assert renamed == 2
    assert len(set(ids)) == 3, "every call must end up with a distinct id"
    assert ids[0] == "x", "the first call keeps the id the model sent"


def test_blank_ids_are_skipped():
    calls = [{"id": "", "name": "a"}, {"id": None, "name": "a"}, {"id": "  ", "name": "a"}]
    assert uniquify_tool_call_ids(calls) == 0
    assert [c["id"] for c in calls] == ["", None, "  "]


def test_renaming_is_deterministic():
    def run():
        calls = [{"id": "c", "name": "a"}, {"id": "c", "name": "b"}]
        uniquify_tool_call_ids(calls)
        return [c["id"] for c in calls]

    assert run() == run(), "ids ride the prompt-cache prefix — renaming must not be random"


# ── the conversation loop ────────────────────────────────────────────────────


class _FakeProvider:
    name = "fake"
    supports_vision = False
    supports_thinking = False
    _model = "fake-model"

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.rounds_started = 0

    def stream_chat(self, messages, tools=None, cancel_event=None):
        self.rounds_started += 1
        if not self._rounds:
            return
        item = self._rounds.pop(0)
        if isinstance(item, BaseException):
            raise item
        yield from item


def _tool_chunk(index, name, args_chunk, call_id=None):
    return {
        "__tool_chunk__": True,
        "index": index,
        "id": call_id or f"{name}-{index}",
        "name": name,
        "args_chunk": args_chunk,
    }


def _finish(reason="tool_calls"):
    return {"__finish_reason__": reason}


def _make_agent(rounds):
    """Agent with only the attributes the conversation loop actually reads."""
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(rounds)
    agent.messages = [{"role": "system", "content": "test"}]
    agent._cancel = threading.Event()
    agent._busy = False
    agent._router = None
    agent._guardrail = ToolLoopGuardrail()
    agent.permission_callback = None
    agent.tool_progress_callback = None
    agent._pre_fetch_links = lambda user_input: iter(())
    agent._refresh_memory_context = lambda *a, **k: None
    agent._resolve_available_tools = lambda *a, **k: []
    # Echo the path back so each result is attributable to its own call.
    agent._execute_tool = lambda name, args: f"read {args.get('path')}"
    return agent


def _events(agent, text="do something"):
    return list(agent._run_conversation_loop(text))


def _tool_results(agent):
    return [m for m in agent.messages if m.get("role") == "tool"]


def test_colliding_ids_keep_every_tool_result():
    agent = _make_agent(
        [
            [
                _tool_chunk(0, "read_file", '{"path": "a.py"}', call_id="call_dup"),
                _tool_chunk(1, "read_file", '{"path": "b.py"}', call_id="call_dup"),
                _finish(),
            ],
            ["done"],
        ]
    )

    _events(agent)

    results = _tool_results(agent)
    assert len(results) == 2, "both calls ran, so both results must be in the history"
    ids = [m["tool_call_id"] for m in results]
    assert len(set(ids)) == 2, "each tool result must keep its own pairing id"

    # Not just present — paired with the *right* call. Under the collision the
    # second result overwrote the first and was replayed for both calls.
    paired = {m["tool_call_id"]: m["content"] for m in results}
    assert paired[ids[0]] == "read a.py"
    assert paired[ids[1]] == "read b.py"

    assistant = [
        m for m in agent.messages
        if m.get("role") == "assistant" and m.get("tool_calls")
    ][-1]
    assert [tc["id"] for tc in assistant["tool_calls"]] == ids


def test_unrelated_400_does_not_retry_a_history_with_nothing_dangling():
    agent = _make_agent([RuntimeError("HTTP 400: maximum context length is 4000 tokens")])

    events = _events(agent)

    assert agent.provider.rounds_started == 1, (
        "a 400 whose text merely contains '400' has nothing to repair — it must "
        "not consume the recovery and re-request"
    )
    assert any(e.get("type") == "error" for e in events)


def test_dangling_round_is_repaired_and_the_request_retried():
    agent = _make_agent(
        [
            RuntimeError(
                "400 An assistant message with 'tool_calls' must be followed by "
                "tool messages responding to each 'tool_call_id'"
            ),
            ["recovered"],
        ]
    )
    agent.messages += [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "stale", "name": "read_file", "arguments": {}}],
        },
    ]

    events = _events(agent)

    assert agent.provider.rounds_started == 2, "a genuine dangling 400 must still recover"
    assert not [
        m for m in agent.messages
        if m.get("role") == "assistant" and m.get("tool_calls") and m["tool_calls"][0]["id"] == "stale"
    ], "the dangling round must be dropped before the retry"
    text = "".join(e.get("token", "") for e in events if e.get("type") == "text")
    assert "recovered" in text
