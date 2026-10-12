"""A turn that edited code without running verification gets a verify-on-stop nudge.

Koza used to end the turn on the first text-only response even when the same
turn had just written or patched source files and never ran a test, lint or
build command afterwards. The gate now returns a synthetic nudge (bounded in
attempts) that the conversation loop injects so verification actually happens.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Agent, ToolLoopGuardrail
from utils.verify_on_stop import VerifyOnStopGate, _is_code_path


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


def _make_agent(rounds, cfg=None):
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(rounds)
    agent.cfg = cfg or {}
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
    agent._execute_tool = lambda name, args: f"ran {name}"
    return agent


def test_loop_nudges_unverified_edit_then_ends():
    """Write code, then answer text: the nudge round fires before the answer."""
    rounds = [
        [_tool_chunk(0, "write_file", '{"path": "app.py"}'), _finish()],
        ["All done, fully working."],   # would have been the final answer
        ["I ran pytest and it passed."],  # after the nudge
    ]
    agent = _make_agent(rounds, cfg={"verify_on_stop": {"max_attempts": 1}})
    events = list(agent._run_conversation_loop("fix the bug"))
    final = [e for e in events if e.get("type") == "text"]
    assert "".join(e["token"] for e in final).endswith("I ran pytest and it passed.")
    # The nudged draft never becomes the answer; its scaffolding is stripped.
    answers = [m for m in agent.messages if m.get("role") == "assistant" and not m.get("tool_calls")]
    assert len(answers) == 1
    assert "All done" not in answers[-1]["content"]
    assert not any("_verify_on_stop_nudge" in m for m in agent.messages)


def test_loop_does_not_nudge_verified_edit():
    rounds = [
        [_tool_chunk(0, "write_file", '{"path": "app.py"}'), _finish()],
        [_tool_chunk(0, "run_command", '{"command": "pytest -q"}'), _finish()],
        ["Done: tests pass."],
    ]
    agent = _make_agent(rounds)
    list(agent._run_conversation_loop("fix the bug"))
    answers = [m for m in agent.messages if m.get("role") == "assistant" and not m.get("tool_calls")]
    # Exactly one answer, delivered in the round it was produced — no nudge round.
    assert len(answers) == 1
    assert "Done: tests pass." in answers[-1]["content"]


def test_edit_without_verification_produces_nudge():
    gate = VerifyOnStopGate({})
    gate.observe("write_file", {"path": "app.py", "content": "x = 1"})
    nudge = gate.build_nudge()
    assert nudge is not None
    assert "app.py" in nudge
    assert "verification" in nudge.lower()
    assert gate.attempts == 1


def test_verification_after_edit_clears_the_gate():
    gate = VerifyOnStopGate({})
    gate.observe("write_file", {"path": "app.py", "content": "x = 1"})
    gate.observe("run_command", {"command": "python -m pytest tests -q"})
    assert gate.build_nudge() is None


def test_edit_before_command_does_not_count_later_command():
    # Command first, edit after → the edit is still unverified.
    gate = VerifyOnStopGate({})
    gate.observe("run_command", {"command": "pytest -q"})
    gate.observe("patch_file", {"path": "core.py", "old": "a", "new": "b"})
    assert gate.build_nudge() is not None


def test_lint_tool_name_counts_as_verification():
    gate = VerifyOnStopGate({})
    gate.observe("patch_file", {"path": "src/mod.py"})
    gate.observe("lint_code", {"path": "src/mod.py"})
    assert gate.build_nudge() is None


def test_prose_and_data_files_are_ignored():
    gate = VerifyOnStopGate({})
    gate.observe("write_file", {"path": "README.md"})
    gate.observe("write_file", {"path": "notes.txt"})
    gate.observe("write_file", {"path": "LICENSE"})
    gate.observe("write_file", {"path": "data.json"})
    assert gate.build_nudge() is None


def test_attempts_are_bounded():
    gate = VerifyOnStopGate({"verify_on_stop": {"max_attempts": 2}})
    gate.observe("write_file", {"path": "app.py"})
    assert gate.build_nudge() is not None
    assert gate.build_nudge() is not None
    assert gate.build_nudge() is None
    assert gate.attempts == 2


def test_disabled_gate_never_nudges():
    gate = VerifyOnStopGate({"verify_on_stop": {"enabled": False}})
    gate.observe("write_file", {"path": "app.py"})
    assert gate.build_nudge() is None


def test_invalid_max_attempts_falls_back_to_default():
    gate = VerifyOnStopGate({"verify_on_stop": {"max_attempts": "x"}})
    gate.observe("write_file", {"path": "app.py"})
    # Default budget is 2.
    assert gate.build_nudge() is not None
    assert gate.build_nudge() is not None
    assert gate.build_nudge() is None


def test_is_code_path():
    assert _is_code_path("core.py")
    assert _is_code_path("src/app/main.go")
    assert not _is_code_path("README.md")
    assert not _is_code_path("package-lock.json")
    assert not _is_code_path("logo.png")
    assert not _is_code_path("")
