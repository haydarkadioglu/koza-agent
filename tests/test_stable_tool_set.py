"""The tool array is stable within a conversation, so the cached prefix survives (K-13).

The keyword router narrows the selection to a slice on a turn that matches nothing
and widens it again on the next turn that matches — so the tool schema was rewritten
mid-conversation. Providers cache on an exact prefix that begins with the tool array
(``providers/prompt_caching.py`` puts its cache breakpoint on the first message), so
every flip invalidated the cache for the whole request.

The array is now append-only for the life of a conversation: a tool that has been
sent stays visible, new tools are appended in registry order, and only tools that
left the registry drop out. ``_expand_tools_for_call`` no longer appends in
set-iteration order (which differs between processes), so the same activations
serialise to the same bytes.
"""
import json
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core as core_module
from core import (
    Agent,
    ToolLoopGuardrail,
    _canonical_tool_order,
    _expand_tools_for_call,
    _tool_name,
)

# Real registry names, so the membership filter behaves as in production.
NARROW = ["read_file", "web_search"]
WIDE = NARROW + ["send_email", "send_message", "vision_analyze"]


def _tool(name: str) -> dict:
    """The live registry definition for `name` (fails loudly if it is renamed)."""
    return dict(core_module._TOOL_BY_NAME[name])


def _names(tools) -> list[str]:
    return [_tool_name(t) for t in tools]


def _bare_agent() -> Agent:
    """Agent with only the state _resolve_available_tools touches."""
    agent = Agent.__new__(Agent)
    agent.cfg = {}
    agent.messages = []
    agent._session_tool_order = []
    agent._sent_tool_names = set()
    return agent


def _selecting(pick):
    """Stand-in for the keyword router: narrow or wide, decided per user input."""
    def _select(user_input, *a, **k):
        return [_tool(n) for n in pick(user_input)]
    return _select


# ── the array is append-only ────────────────────────────────────────────────

def test_narrow_wide_narrow_keeps_the_first_array_as_a_prefix(monkeypatch):
    """Turn 1 narrow, turn 2 wide, turn 3 narrow: turn 3 still carries turn 1."""
    monkeypatch.setattr(core_module, "_select_tools",
                        _selecting(lambda text: WIDE if "@" in text else NARROW))

    agent = _bare_agent()
    first = _names(agent._resolve_available_tools("hello there", None, True))
    second = _names(agent._resolve_available_tools("email it to a@b.com", None, True))
    third = _names(agent._resolve_available_tools("hello there", None, True))

    assert "read_file" in first and "send_email" not in first
    assert "send_email" in second, "the fixture must actually widen the selection"
    # turn 3's selection narrowed again — the array must not
    assert third[: len(first)] == first
    assert set(second) <= set(third)
    assert third == second, "a narrowed re-selection restores the same sticky array"


def test_reselection_is_byte_identical(monkeypatch):
    """Same selection twice → identical JSON, so the cached prefix is untouched."""
    monkeypatch.setattr(core_module, "_select_tools", _selecting(lambda text: NARROW))
    agent = _bare_agent()
    first = agent._resolve_available_tools("hello", None, True)
    second = agent._resolve_available_tools("hello", None, True)
    assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)


def test_two_agents_on_the_same_turn_produce_the_same_array(monkeypatch):
    """Deterministic assembly: no dependence on process hash seed / set order."""
    monkeypatch.setattr(core_module, "_select_tools", _selecting(lambda text: WIDE))
    a = _names(_bare_agent()._resolve_available_tools("hello", None, True))
    b = _names(_bare_agent()._resolve_available_tools("hello", None, True))
    assert a == b


def test_previous_tools_survive_a_narrow_reselection(monkeypatch):
    """Bridge/group activations from the loop are not dropped on the next round."""
    monkeypatch.setattr(core_module, "_select_tools", _selecting(lambda text: NARROW))
    agent = _bare_agent()
    first = agent._resolve_available_tools("hello", None, True)
    grown = _expand_tools_for_call(first, [], extra_names={"vision_analyze"})
    assert "vision_analyze" in _names(grown)
    again = _names(agent._resolve_available_tools("hello", None, True, previous_tools=grown))
    assert "vision_analyze" in again


# ── membership: registry changes only ───────────────────────────────────────

def test_tool_that_left_the_registry_drops_out(monkeypatch):
    keep, gone = _tool("read_file"), _tool("vision_analyze")
    monkeypatch.setattr(core_module, "ALL_TOOLS", [keep, gone])
    monkeypatch.setattr(core_module, "_select_tools",
                        _selecting(lambda text: ["read_file", "vision_analyze"]))
    agent = _bare_agent()
    before = _names(agent._resolve_available_tools("hello", None, True))
    assert "vision_analyze" in before

    monkeypatch.setattr(core_module, "ALL_TOOLS", [keep])  # skill/plugin disabled
    monkeypatch.setattr(core_module, "_select_tools", _selecting(lambda text: ["read_file"]))
    after = _names(agent._resolve_available_tools("hello", None, True))
    assert "vision_analyze" not in after
    assert "read_file" in after


def test_bridge_stays_visible(monkeypatch):
    """tool_search is not in the registry; the membership filter must keep it."""
    monkeypatch.setattr(core_module, "_select_tools", _selecting(lambda text: NARROW))
    agent = _bare_agent()
    first = _names(agent._resolve_available_tools("hello", None, True))
    assert "tool_search" in first
    second = _names(agent._resolve_available_tools("hello", None, True))
    assert second.count("tool_search") == 1


def test_reset_starts_a_fresh_conversation(monkeypatch):
    monkeypatch.setattr("config.save_config", lambda cfg: None)
    agent = _bare_agent()
    agent.channel = "cli"
    agent._ctx = SimpleNamespace(summary="", messages=[])
    agent.auto_save = lambda *a, **k: "saved"
    agent._session_progress = 0.0
    agent._session_tool_order = ["read_file", "web_search"]
    Agent.reset(agent)
    assert agent._session_tool_order == []
    assert agent.messages[0]["role"] == "system"


# ── deterministic expansion order ───────────────────────────────────────────

def test_canonical_order_follows_the_registry_not_the_set():
    names = set(WIDE)
    ordered = _canonical_tool_order(names)
    registry = [_tool_name(t) for t in core_module.ALL_TOOLS]
    assert ordered == [n for n in registry if n in names]
    assert len(ordered) == len(names)


def test_canonical_order_survives_set_insertion_order():
    forward = _canonical_tool_order({"web_search", "send_email", "vision_analyze"})
    reverse = _canonical_tool_order({"vision_analyze", "send_email", "web_search"})
    assert forward == reverse


def test_expand_tools_for_call_is_deterministic():
    base = [_tool("read_file")]
    first = _names(_expand_tools_for_call(base, ["send_email", "send_message"]))
    second = _names(_expand_tools_for_call(base, ["send_message", "send_email"]))
    assert first == second
    registry = [_tool_name(t) for t in core_module.ALL_TOOLS]
    added = [n for n in first if n not in ("read_file", "tool_search")]
    assert added == [n for n in registry if n in set(added)]


# ── end to end: two turns of the real loop ─────────────────────────────────

class _FakeProvider:
    name = "ollama"  # local → the narrow dynamic selection path
    supports_vision = False
    supports_thinking = False
    _model = "fake-model"

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.seen_tools: list[list[str]] = []

    def stream_chat(self, messages, tools=None, cancel_event=None):
        self.seen_tools.append(_names(tools or []))
        if not self._rounds:
            return
        yield from self._rounds.pop(0)


def _loop_agent(rounds):
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(rounds)
    agent.cfg = {}
    agent.channel = "cli"
    agent.messages = [{"role": "system", "content": "test"}]
    agent._cancel = threading.Event()
    agent._busy = False
    agent._router = None
    agent._guardrail = ToolLoopGuardrail()
    agent.permission_callback = None
    agent.tool_progress_callback = None
    agent._activated_tools = set()
    agent._sent_tool_names = set()
    agent._session_tool_order = []
    agent._pre_fetch_links = lambda user_input: iter(())
    agent._refresh_memory_context = lambda *a, **k: None
    agent._execute_tool = lambda name, args: f"ran {name}"
    return agent


def test_loop_keeps_the_prefix_between_turns(monkeypatch):
    """Turn 1 matches no keyword, turn 2 does: the sent array only grows."""
    monkeypatch.setattr(core_module, "_select_tools",
                        _selecting(lambda text: WIDE if "@" in text else NARROW))
    agent = _loop_agent([["ok"], ["ok"]])

    list(agent._run_conversation_loop("hello there"))
    list(agent._run_conversation_loop("email it to a@b.com"))

    sent = agent.provider.seen_tools
    assert len(sent) == 2
    first, second = sent
    assert first and second
    assert second[: len(first)] == first
    assert len(second) > len(first)


def test_loop_repeats_a_turn_byte_identically(monkeypatch):
    """Two turns that select the same tools send the exact same array."""
    monkeypatch.setattr(core_module, "_select_tools", _selecting(lambda text: WIDE))
    agent = _loop_agent([["ok"], ["ok"]])

    list(agent._run_conversation_loop("hello there"))
    list(agent._run_conversation_loop("hello there"))

    first, second = agent.provider.seen_tools
    assert first == second
