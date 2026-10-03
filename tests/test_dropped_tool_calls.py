"""finish_reason="tool_calls" with no buffered call must not deliver the plan text.

A provider can report ``finish_reason="tool_calls"`` and stream no tool-call
chunk at all: the model narrated a plan ("I'll read the file now…") instead of
issuing the call, or an interrupt cut a retry short. Koza used to append that
narration as the final assistant message and end the turn, so the task silently
stopped half-done. It now re-prompts for the real call, bounded to 3
*consecutive* stalls; a round that actually executes a tool clears the budget.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import _DROPPED_TOOLCALL_NUDGE, Agent, ToolLoopGuardrail


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
        yield from self._rounds.pop(0)


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


def _last_assistant(agent):
    return [m for m in agent.messages if m.get("role") == "assistant"][-1]


# ── the stall is re-prompted, not delivered ──────────────────────────────────


def test_narration_only_stall_is_reprompted_until_the_call_arrives():
    agent = _make_agent(
        [
            ["I will read a.py now.", _finish("tool_calls")],  # narration only
            [_tool_chunk(0, "read_file", '{"path": "a.py"}'), _finish("tool_calls")],
            ["Read it.", _finish("stop")],
        ]
    )

    _events(agent)

    assert agent.provider.rounds_started == 3, (
        "a narration-only finish_reason=tool_calls must re-prompt, not end the turn"
    )
    assert [m["content"] for m in _tool_results(agent)] == ["read a.py"], (
        "the re-prompted round must actually execute the call"
    )
    assert _last_assistant(agent)["content"] == "Read it."


def test_a_model_that_only_ever_narrates_still_terminates():
    agent = _make_agent([["thinking out loud", _finish("tool_calls")]] * 6)

    _events(agent)

    assert agent.provider.rounds_started == 4, (
        "1 round + at most 3 re-prompts, then the narration is delivered"
    )
    assert _last_assistant(agent)["content"] == "thinking out loud"


def test_a_real_tool_batch_resets_the_stall_budget():
    agent = _make_agent(
        [
            ["narrating 1", _finish("tool_calls")],  # stall 1
            ["narrating 2", _finish("tool_calls")],  # stall 2
            [_tool_chunk(0, "read_file", '{"path": "a.py"}'), _finish("tool_calls")],  # progress
            ["narrating 3", _finish("tool_calls")],  # stall 1 again
            ["narrating 4", _finish("tool_calls")],  # stall 2
            ["narrating 5", _finish("tool_calls")],  # stall 3
            ["narrating 6", _finish("tool_calls")],  # budget spent → deliver
        ]
    )

    _events(agent)

    assert agent.provider.rounds_started == 7, (
        "a round that really executed a tool must clear the consecutive-stall budget"
    )


# ── regressions: normal turns are untouched ─────────────────────────────────


def test_plain_stop_response_is_returned_without_a_re_prompt():
    agent = _make_agent([["the answer", _finish("stop")]])

    _events(agent)

    assert agent.provider.rounds_started == 1
    assert _last_assistant(agent)["content"] == "the answer"


def test_text_response_without_a_finish_reason_is_returned_immediately():
    # gemini/anthropic only emit __finish_reason__ on truncation, so a normal
    # completion leaves it None — that must never be mistaken for a stall.
    agent = _make_agent([["just text"]])

    _events(agent)

    assert agent.provider.rounds_started == 1
    assert _last_assistant(agent)["content"] == "just text"


def test_retry_scaffolding_is_not_left_in_history():
    agent = _make_agent(
        [
            ["narrating", _finish("tool_calls")],
            ["done", _finish("stop")],
        ]
    )

    _events(agent)

    assert all(m.get("content") != _DROPPED_TOOLCALL_NUDGE for m in agent.messages)
    assert all(not m.get("_dropped_toolcall_nudge") for m in agent.messages)
    assert [m["content"] for m in agent.messages] == ["test", "do something", "done"]
