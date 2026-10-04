"""A tool call must run under a deadline and stay interruptible.

Koza used to call the tool handler inline in the conversation loop: a tool that
never returned (a wedged subprocess, a socket read with no timeout) blocked the
whole loop forever, and ``interrupt()`` — which only sets ``self._cancel`` —
could not break it, because nothing was polled while the tool ran. Every call now
runs on a daemon worker that the loop polls, so an overrunning or interrupted
call is abandoned with a visible result instead of hanging the turn.
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
    _DEFAULT_TOOL_TIMEOUT_SECONDS,
    Agent,
    ToolLoopGuardrail,
    _resolve_tool_timeout,
)

# ── unit: _run_tool_with_deadline ────────────────────────────────────────────


def _agent(cfg=None, tool_fn=None):
    agent = Agent.__new__(Agent)
    agent._cancel = threading.Event()
    agent.cfg = cfg or {}
    agent._execute_tool = tool_fn or (lambda name, args: f"ran {name}")
    return agent


def test_normal_call_returns_done_with_its_result():
    agent = _agent(tool_fn=lambda name, args: f"ran {name}")

    result, _elapsed, outcome = agent._run_tool_with_deadline("read_file", {"path": "a"})

    assert outcome == "done"
    assert result == "ran read_file"


def test_wedged_tool_is_abandoned_at_the_deadline():
    never = threading.Event()
    agent = _agent(cfg={"tool_timeout_seconds": 0.3}, tool_fn=lambda name, args: never.wait())

    t0 = time.monotonic()
    result, elapsed, outcome = agent._run_tool_with_deadline("run_command", {"command": "sleep"})
    wall = time.monotonic() - t0

    assert outcome == "timeout", "an overrunning call must be abandoned, not awaited"
    assert wall < 5, "the call must not hang the caller past its deadline"
    assert "timed out after 0.3s" in result
    assert abs(elapsed - 0.3) < 0.1


def test_interrupt_abandons_a_wedged_tool():
    never = threading.Event()
    agent = _agent(cfg={"tool_timeout_seconds": 30}, tool_fn=lambda name, args: never.wait())

    def _interrupt_soon():
        time.sleep(0.2)
        agent._cancel.set()

    threading.Thread(target=_interrupt_soon, daemon=True).start()

    result, _elapsed, outcome = agent._run_tool_with_deadline("run_command", {"command": "sleep"})

    assert outcome == "interrupted", "an interrupt must break a tool that never returns"
    assert "interrupted by the user" in result


def test_exempt_tools_have_no_deadline():
    agent = _agent(
        cfg={"tool_timeout_seconds": 0.2},
        tool_fn=lambda name, args: (time.sleep(0.5), "batch-done")[1],
    )

    result, _elapsed, outcome = agent._run_tool_with_deadline("delegate_task", {})

    assert outcome == "done"
    assert result == "batch-done"


def test_zero_config_disables_the_deadline_but_keeps_interruptibility():
    agent = _agent(
        cfg={"tool_timeout_seconds": 0},
        tool_fn=lambda name, args: (time.sleep(0.35), "slow-ok")[1],
    )

    result, _elapsed, outcome = agent._run_tool_with_deadline("run_command", {})

    assert outcome == "done"
    assert result == "slow-ok"


def test_resolve_tool_timeout_reads_config_with_a_safe_fallback():
    assert _resolve_tool_timeout(_agent(cfg={})) == _DEFAULT_TOOL_TIMEOUT_SECONDS
    assert _resolve_tool_timeout(_agent(cfg={"tool_timeout_seconds": 42})) == 42.0
    assert _resolve_tool_timeout(_agent(cfg={"tool_timeout_seconds": 0})) is None
    assert _resolve_tool_timeout(_agent(cfg={"tool_timeout_seconds": -5})) is None
    assert _resolve_tool_timeout(_agent(cfg={"tool_timeout_seconds": "bad"})) == _DEFAULT_TOOL_TIMEOUT_SECONDS


# ── end to end: the conversation loop keeps moving ───────────────────────────


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


def _make_agent(rounds, tool_fn=None, cfg=None):
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(rounds)
    agent.messages = [{"role": "system", "content": "test"}]
    agent._cancel = threading.Event()
    agent._busy = False
    agent.cfg = cfg or {}
    agent._router = None
    agent._guardrail = ToolLoopGuardrail()
    agent.permission_callback = None
    agent.tool_progress_callback = None
    agent._pre_fetch_links = lambda user_input: iter(())
    agent._refresh_memory_context = lambda *a, **k: None
    agent._resolve_available_tools = lambda *a, **k: []
    agent._execute_tool = tool_fn or (lambda name, args: f"ran {name}")
    return agent


def _events(agent, text="do something"):
    return list(agent._run_conversation_loop(text))


def _tool_results(agent):
    return [m for m in agent.messages if m.get("role") == "tool"]


def _last_assistant(agent):
    return [m for m in agent.messages if m.get("role") == "assistant"][-1]


def test_loop_does_not_hang_when_a_sequential_tool_wedges():
    never = threading.Event()

    def tool(name, args):
        never.wait()  # never returns
        return "never"

    agent = _make_agent(
        [
            [_tool_chunk(0, "run_command", '{"command": "sleep"}'), _finish("tool_calls")],
            ["recovered", _finish("stop")],
        ],
        tool_fn=tool,
        cfg={"tool_timeout_seconds": 0.3},
    )

    t0 = time.monotonic()
    _events(agent)
    wall = time.monotonic() - t0

    assert wall < 5, "the turn must not hang on a wedged tool"
    tool_msgs = _tool_results(agent)
    assert len(tool_msgs) == 1
    assert "timed out after" in tool_msgs[0]["content"]
    assert agent.provider.rounds_started == 2, "the loop must continue after a timeout"
    assert _last_assistant(agent)["content"] == "recovered"


def test_loop_stops_when_an_interrupt_abandons_a_tool():
    ref = {}

    def tool(name, args):
        ref["agent"]._cancel.set()
        threading.Event().wait()  # never returns
        return "never"

    agent = _make_agent(
        [[_tool_chunk(0, "run_command", '{"command": "sleep"}'), _finish("tool_calls")]],
        tool_fn=tool,
        cfg={"tool_timeout_seconds": 30},
    )
    ref["agent"] = agent

    events = _events(agent)

    assert {"type": "interrupted"} in events
    assert agent.provider.rounds_started == 1, "an interrupted turn must not start a new round"
    tool_msgs = _tool_results(agent)
    assert len(tool_msgs) == 1
    assert "interrupted by the user" in tool_msgs[0]["content"]


def test_parallel_batch_abandons_a_wedged_call_at_the_deadline():
    never = threading.Event()

    def tool(name, args):
        if name == "web_search":
            never.wait()  # only the search wedges
        return f"ok:{name}"

    agent = _make_agent(
        [
            [
                _tool_chunk(0, "read_file", '{"path": "a.py"}'),
                _tool_chunk(1, "web_search", '{"query": "q"}'),
                _finish("tool_calls"),
            ],
            ["done", _finish("stop")],
        ],
        tool_fn=tool,
        cfg={"tool_timeout_seconds": 0.4},
    )

    t0 = time.monotonic()
    _events(agent)
    wall = time.monotonic() - t0

    assert wall < 5, "one wedged parallel call must not freeze the batch"
    by_name = {m["name"]: m["content"] for m in _tool_results(agent)}
    assert by_name["read_file"] == "ok:read_file"
    assert "timed out after" in by_name["web_search"]
    assert agent.provider.rounds_started == 2
    assert _last_assistant(agent)["content"] == "done"
