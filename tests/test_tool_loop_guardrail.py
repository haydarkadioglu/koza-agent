"""The tool-loop guardrail must stop a bad loop, not just comment on it.

Before this, every guardrail action was advisory: a blocked call was answered
with a synthetic error and the loop simply carried on to MAX_ROUNDS, counters
were wiped at the start of every turn (so a loop replayed from a later user
message was invisible), and a call the executor had already abandoned on its
deadline was never observed by the guardrail at all.

The guardrail now escalates warn -> block -> halt; a halt ends the turn with a
user-facing explanation, failure counters survive `start_turn()` (decayed), and
the executor reports its own failures explicitly instead of the guardrail
guessing them from result text.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
    Agent,
    ToolLoopGuardrail,
    _guardrail_halt_response,
    _guardrail_settings,
    _tool_result_looks_failed,
)


def _g(**settings):
    return ToolLoopGuardrail(settings or None)


# ── escalation: block, then halt ─────────────────────────────────────────────


def test_a_blocked_call_reissued_halts_the_turn():
    guard = _g()

    for _ in range(4):
        guard.after_call("read_file", {"path": "a.py"}, "ERROR: no such file")

    blocked, message = guard.before_call("read_file", {"path": "a.py"})
    assert blocked and "Tool call blocked" in message
    assert guard.halt_decision is None, "the first refusal is still only a block"

    blocked, _ = guard.before_call("read_file", {"path": "a.py"})
    assert blocked
    halt = guard.halt_decision
    assert halt is not None and halt.action == "halt"
    assert halt.code == "repeated_exact_failure_halt"
    assert halt.tool_name == "read_file"


def test_hard_stop_can_be_disabled_so_blocks_stay_advisory():
    guard = _g(hard_stop_enabled=False)

    for _ in range(4):
        guard.after_call("read_file", {"path": "a.py"}, "ERROR: no such file")

    for _ in range(5):
        assert guard.before_call("read_file", {"path": "a.py"})[0] is True
    assert guard.halt_decision is None, "hard_stop_enabled=false must never end a turn"


def test_one_tool_failing_with_different_arguments_halts_the_turn():
    guard = _g()

    for i in range(7):
        assert guard.halt_decision is None
        guard.after_call("send_message", {"to": f"user{i}"}, "ERROR: not configured")

    guard.after_call("send_message", {"to": "user7"}, "ERROR: not configured")
    halt = guard.halt_decision
    assert halt is not None and halt.code == "same_tool_failure_halt"
    assert halt.count == 8


def test_failure_tolerant_tools_never_halt_on_distinct_arguments():
    # A run of different red commands is diagnosis, not a loop.
    guard = _g()

    for i in range(12):
        guard.after_call("run_command", {"command": f"probe {i}"}, "Exit code: 1\nboom")

    assert guard.halt_decision is None


# ── cross-turn: a replayed loop is still caught ──────────────────────────────


def test_failure_counters_survive_a_new_turn():
    guard = _g()

    for _ in range(4):
        guard.after_call("read_file", {"path": "a.py"}, "ERROR: no such file")

    guard.start_turn()
    assert guard.before_call("read_file", {"path": "a.py"})[0] is True, (
        "a call blocked last turn must still be blocked when the model replays it"
    )
    assert guard.halt_decision is None, "the halt decision itself is per-turn"


def test_per_tool_counters_decay_by_half_each_turn():
    guard = _g()
    for i in range(8):
        guard.after_call("run_command", {"command": f"probe {i}"}, "Exit code: 1")

    guard.start_turn()

    assert guard._total_failures_by_tool["run_command"] == 4, (
        "only a dense loop may accumulate to a halt across turns"
    )


# ── structured failure reporting beats string sniffing ───────────────────────


def test_a_handler_failure_is_counted_even_when_the_text_looks_fine():
    guard = _g()
    clean = "wrote 3 rows"

    assert _tool_result_looks_failed(clean) is False, "the text alone is not a failure"

    for _ in range(4):
        guard.after_call("send_message", {"to": "x"}, clean, failed=True)

    assert guard.before_call("send_message", {"to": "x"})[0] is True, (
        "failed=True from the executor must count without any prose marker"
    )


def test_a_successful_call_clears_the_failure_streak():
    guard = _g()

    for _ in range(4):
        guard.after_call("read_file", {"path": "a.py"}, "ERROR: no such file")
    assert guard.before_call("read_file", {"path": "a.py"})[0] is True

    guard.after_call("read_file", {"path": "a.py"}, "file contents")
    assert guard.before_call("read_file", {"path": "a.py"})[0] is False, (
        "progress must clear the block as well"
    )


def test_identical_read_only_results_still_block_then_halt():
    guard = _g()

    for _ in range(5):
        guard.after_call("read_file", {"path": "a.py"}, "same contents")

    assert guard.before_call("read_file", {"path": "a.py"})[0] is True
    guard.before_call("read_file", {"path": "a.py"})
    assert guard.halt_decision is not None


# ── config plumbing ──────────────────────────────────────────────────────────


def test_settings_come_from_the_config_section_and_ignore_garbage():
    settings = _guardrail_settings({
        "tool_loop_guardrails": {
            "exact_failure_block_after": 2,
            "hard_stop_enabled": False,
            "nonsense_key": 5,
        }
    })

    assert settings["exact_failure_block_after"] == 2
    assert settings["hard_stop_enabled"] is False
    assert "nonsense_key" not in settings

    invalid = _guardrail_settings({"tool_loop_guardrails": {"exact_failure_block_after": "banana"}})
    assert invalid["exact_failure_block_after"] == 4, "a typo must never disable the guardrail"

    assert _guardrail_settings(None) == _guardrail_settings({})


def test_warnings_can_be_switched_off_without_disabling_the_counters():
    guard = _g(warnings_enabled=False)

    first = guard.after_call("read_file", {"path": "a.py"}, "ERROR: no such file")
    second = guard.after_call("read_file", {"path": "a.py"}, "ERROR: no such file")

    assert first == "ERROR: no such file" and second == "ERROR: no such file"
    assert guard.before_call("read_file", {"path": "a.py"})[0] is False, "2 failures is not yet a block"

    for _ in range(2):
        guard.after_call("read_file", {"path": "a.py"}, "ERROR: no such file")
    assert guard.before_call("read_file", {"path": "a.py"})[0] is True


def test_halt_response_names_the_tool_without_internal_codes():
    guard = _g()
    for i in range(8):
        guard.after_call("send_message", {"to": f"u{i}"}, "ERROR: not configured")

    text = _guardrail_halt_response(guard.halt_decision)

    assert "send_message" in text and "8" in text
    assert "same_tool_failure_halt" not in text, "codes stay in the logs, not in the reply"


# ── the loop itself: a halt ends the turn ────────────────────────────────────


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


def _make_agent(rounds, tool_result):
    """Agent with only the attributes the conversation loop actually reads."""
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(rounds)
    agent.messages = [{"role": "system", "content": "test"}]
    agent._cancel = threading.Event()
    agent._busy = False
    agent._router = None
    agent.cfg = {}
    agent._guardrail = ToolLoopGuardrail()
    agent.permission_callback = None
    agent.tool_progress_callback = None
    agent._pre_fetch_links = lambda user_input: iter(())
    agent._refresh_memory_context = lambda *a, **k: None
    agent._resolve_available_tools = lambda *a, **k: []
    agent._execute_tool = lambda name, args: tool_result
    return agent


def test_a_looping_turn_is_halted_instead_of_burning_every_round():
    rounds = [
        [_tool_chunk(0, "read_file", '{"path": "a.py"}', call_id=f"call-{n}"), _finish("tool_calls")]
        for n in range(10)
    ]
    agent = _make_agent(rounds, "ERROR: no such file")

    events = list(agent._run_conversation_loop("read a.py"))

    assert agent.provider.rounds_started <= 7, (
        f"the turn must stop shortly after the second refusal, "
        f"not run to MAX_ROUNDS (started {agent.provider.rounds_started})"
    )
    final = [m for m in agent.messages if m.get("role") == "assistant"][-1]["content"]
    assert final.startswith("I stopped instead of looping"), final
    assert "read_file" in final
    assert events[-1]["type"] == "text"


def test_every_call_in_a_halted_batch_still_gets_a_result():
    # Four identical failing calls in one batch of a non-parallel-safe tool: the
    # first re-run is refused, the second refusal halts the turn mid-batch, and the
    # calls after it never run — they still need a result, or the transcript has
    # dangling tool_call_ids.
    rounds = [
        [
            _tool_chunk(0, "patch_file", '{"path": "a.py"}', call_id="call-0"),
            _tool_chunk(1, "patch_file", '{"path": "a.py"}', call_id="call-1"),
            _tool_chunk(2, "patch_file", '{"path": "a.py"}', call_id="call-2"),
            _tool_chunk(3, "patch_file", '{"path": "a.py"}', call_id="call-3"),
            _finish("tool_calls"),
        ],
        [
            _tool_chunk(0, "patch_file", '{"path": "a.py"}', call_id="call-4"),
            _tool_chunk(1, "patch_file", '{"path": "a.py"}', call_id="call-5"),
            _tool_chunk(2, "patch_file", '{"path": "a.py"}', call_id="call-6"),
            _tool_chunk(3, "patch_file", '{"path": "a.py"}', call_id="call-7"),
            _finish("tool_calls"),
        ],
    ]
    agent = _make_agent(rounds, "ERROR: no such file")

    list(agent._run_conversation_loop("read a.py"))

    results = {
        m["tool_call_id"]: m["content"]
        for m in agent.messages
        if m.get("role") == "tool"
    }
    issued = [f"call-{n}" for n in range(8)]
    assert set(results) == set(issued), (
        f"every issued tool call needs exactly one result: {sorted(results)}"
    )
    skipped = [cid for cid in issued if results[cid].startswith("Skipped:")]
    assert skipped == ["call-6", "call-7"], (
        f"the calls after the halt must be marked skipped, got {skipped}"
    )


def test_a_clean_turn_is_not_halted():
    agent = _make_agent(
        [
            [_tool_chunk(0, "read_file", '{"path": "a.py"}'), _finish("tool_calls")],
            ["the answer", _finish("stop")],
        ],
        "file contents",
    )

    list(agent._run_conversation_loop("read a.py"))

    assert agent._guardrail.halt_decision is None
    assert agent.provider.rounds_started == 2
    assert [m for m in agent.messages if m.get("role") == "assistant"][-1]["content"] == "the answer"
