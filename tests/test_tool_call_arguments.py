"""Tool-call arguments: an unparseable payload must never be executed.

An argument payload that cannot be parsed used to be silently replaced with
``{}`` and the tool ran anyway, acting on missing parameters. The conversation
loop must instead refuse the whole round, feed the parse error back to the
model, and end the turn if the model keeps emitting broken JSON — bounded, so
it cannot spin forever.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Agent, ToolLoopGuardrail
from utils.json_utils import (
    parse_tool_call_arguments,
    tool_call_arguments_look_truncated,
)

# ── argument parsing ─────────────────────────────────────────────────────────

def test_empty_payload_is_a_parameterless_call():
    assert parse_tool_call_arguments("") == ({}, None)
    assert parse_tool_call_arguments("   ") == ({}, None)
    assert parse_tool_call_arguments(None) == ({}, None)


def test_repairable_payload_still_parses():
    args, error = parse_tool_call_arguments('{"path": "a.py", "content": "x",}')
    assert error is None
    assert args == {"path": "a.py", "content": "x"}


def test_truncated_payload_is_reported_not_repaired():
    raw = '{"command": "rm -rf /tmp'
    assert tool_call_arguments_look_truncated(raw)
    args, error = parse_tool_call_arguments(raw, tool_name="run_terminal")
    assert args == {}
    assert error and "truncated" in error


def test_unparseable_payload_is_reported():
    args, error = parse_tool_call_arguments("this is not json", tool_name="read_file")
    assert args == {}
    assert error


def test_non_object_payload_is_rejected():
    args, error = parse_tool_call_arguments('["a", "b"]', tool_name="read_file")
    assert args == {}
    assert error and "object" in error


def test_complete_payloads_are_not_flagged_as_truncated():
    assert not tool_call_arguments_look_truncated('{"a": 1}')
    assert not tool_call_arguments_look_truncated('{"a": 1}  ')
    assert not tool_call_arguments_look_truncated("[]")


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
        yield from (self._rounds.pop(0) if self._rounds else [])


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


def _make_agent(rounds, executed):
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

    def execute(name, args):
        executed.append((name, args))
        return "ran"

    agent._execute_tool = execute
    return agent


def _events(agent, text="do something"):
    return list(agent._run_conversation_loop(text))


def _tool_results(agent):
    return [m for m in agent.messages if m.get("role") == "tool"]


def test_truncated_arguments_are_not_executed_and_model_is_told_why():
    executed = []
    agent = _make_agent(
        [
            [_tool_chunk(0, "run_terminal", '{"command": "rm -rf /tmp'), _finish()],
            ["all good now"],
        ],
        executed,
    )

    events = _events(agent)

    assert executed == [], "a truncated argument payload must never reach the tool"
    results = _tool_results(agent)
    assert len(results) == 1
    assert results[0]["tool_call_id"] == "run_terminal-0"
    assert "invalid JSON" in results[0]["content"]
    assert "NOT executed" in results[0]["content"]
    assert "truncated" in results[0]["content"]
    assert any(e.get("type") == "text" and "all good now" in e.get("token", "") for e in events)


def test_valid_sibling_call_is_skipped_when_one_call_has_broken_json():
    executed = []
    agent = _make_agent(
        [
            [
                _tool_chunk(0, "run_terminal", '{"command": "ls"}', "call-a"),
                _tool_chunk(1, "read_file", '{"path": ', "call-b"),
                _finish(),
            ],
            ["done"],
        ],
        executed,
    )

    _events(agent)

    assert executed == [], "no call in a broken round may execute"
    results = {m["tool_call_id"]: m["content"] for m in _tool_results(agent)}
    assert set(results) == {"call-a", "call-b"}
    assert "invalid JSON" in results["call-b"]
    assert "Skipped" in results["call-a"]


def test_turn_ends_after_repeated_broken_json_instead_of_looping():
    executed = []
    broken_round = [_tool_chunk(0, "run_terminal", '{"command": "ls'), _finish()]
    agent = _make_agent([broken_round, broken_round, broken_round, broken_round], executed)

    events = _events(agent)

    assert executed == []
    assert agent.provider.rounds_started == 4, "3 retries, then the turn must end"
    assert any(
        m.get("role") == "assistant" and "I stopped instead of guessing" in (m.get("content") or "")
        for m in agent.messages
    )
    assert any(e.get("type") == "tool_done" for e in events)


def test_repairable_arguments_still_execute():
    executed = []
    agent = _make_agent(
        [
            [_tool_chunk(0, "run_terminal", '{"command": "ls",}'), _finish()],
            ["finished"],
        ],
        executed,
    )

    _events(agent)

    assert executed == [("run_terminal", {"command": "ls"})]
