"""The system message is byte-identical between turns so the prefix cache can hit (K-12).

Koza rebuilt the whole system prompt every turn and spliced the result into
``messages[0]``, mixing in working memory, permanent memory, the rolling summary,
the user profile and the credentials status — all of which change between turns.
Providers cache on an exact prefix (``providers/prompt_caching.py`` puts a
cache_control breakpoint precisely on ``messages[0]``), so the breakpoint was
useless: every turn was a cache miss on a ~40 KB prompt.

The prompt is now rendered once per signature and the volatile tail is injected
as a separate transient message.
"""
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core as core_module
from core import Agent, ToolLoopGuardrail
from prompt import (
    build_system_prompt,
    build_volatile_context,
    match_sections,
    prompt_files_signature,
)


class _FakeProvider:
    name = "fake"
    supports_vision = False
    supports_thinking = False
    _model = "fake-model"

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.seen = []

    def stream_chat(self, messages, tools=None, cancel_event=None):
        # Copy each dict: the agent mutates messages[0] in place on later turns,
        # so a shallow list copy would make turn N's snapshot alias turn N+1's.
        self.seen.append([dict(m) for m in messages])
        if not self._rounds:
            return
        yield from self._rounds.pop(0)


class _FixedRouter:
    """Routes every turn to the same sections — isolates prompt stability from
    the router's per-turn section churn (that is K-13's problem, not K-12's)."""

    def classify(self, text):
        return SimpleNamespace(prompt_sections={"workspace", "code"}, tool_groups=set())


def _make_agent(rounds, router=None):
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(rounds)
    agent.cfg = {}
    agent.channel = "cli"
    agent._system_prompt_cache = {}
    agent._pending_dynamic_context = ""
    agent.messages = [{"role": "system", "content": "placeholder"}]
    agent._cancel = threading.Event()
    agent._busy = False
    agent._router = router
    agent._guardrail = ToolLoopGuardrail()
    agent.permission_callback = None
    agent.tool_progress_callback = None
    agent._activated_tools = set()
    agent._pre_fetch_links = lambda user_input: iter(())
    agent._maybe_build_rolling_summary = lambda: None
    agent._auto_save_credentials = lambda user_input: None
    agent._resolve_available_tools = lambda *a, **k: []
    agent._execute_tool = lambda name, args: f"ran {name}"
    return agent


def test_system_message_is_identical_between_turns(monkeypatch):
    """Two turns, different working memory: messages[0] must not move a byte."""
    memories = iter([
        "## Working Memory\n- created report.pdf",
        "## Working Memory\n- created report.pdf\n- user asked for a summary",
    ])
    monkeypatch.setattr(core_module.working_memory, "wm_get_context",
                        lambda *a, **k: next(memories, ""))
    monkeypatch.setattr(core_module.shared_memory, "get_relevant_context",
                        lambda *a, **k: "")
    monkeypatch.setattr(core_module, "build_volatile_context",
                        lambda: "## User Profile\n- prefers terse replies")

    agent = _make_agent([["first answer"], ["second answer"]], router=_FixedRouter())
    # Same intent on both turns: the section set is identical, so the only thing
    # that changes between them is the volatile context.
    list(agent._run_conversation_loop("write me a report please"))
    list(agent._run_conversation_loop("write me a report please"))

    sent = agent.provider.seen
    assert len(sent) == 2
    first_system = sent[0][0]
    second_system = sent[1][0]
    assert first_system["role"] == "system"
    # Independent snapshots, equal bytes — not the same dict seen twice.
    assert first_system is not second_system
    assert first_system["content"] == second_system["content"]
    # It is the real rendered prompt (environment block included), not a stub.
    assert "**Current working directory:**" in first_system["content"]
    assert first_system["content"] != "placeholder"


def test_dynamic_context_rides_alone_and_is_stripped(monkeypatch):
    """Volatile context ships as its own tagged message and never sticks."""
    monkeypatch.setattr(core_module.working_memory, "wm_get_context",
                        lambda *a, **k: "## Working Memory\n- WORKING-MEMORY-MARKER")
    monkeypatch.setattr(core_module.shared_memory, "get_relevant_context",
                        lambda *a, **k: "## Permanent Memory\n- MEMORY-MARKER")
    monkeypatch.setattr(core_module, "build_volatile_context",
                        lambda: "## User Profile\n- PROFILE-MARKER")

    agent = _make_agent([["done"]])
    list(agent._run_conversation_loop("hello there"))

    sent_system = agent.provider.seen[0][0]["content"]
    for marker in ("WORKING-MEMORY-MARKER", "MEMORY-MARKER", "PROFILE-MARKER"):
        assert marker not in sent_system

    dynamic = [m for m in agent.provider.seen[0] if m.get("_dynamic_context")]
    assert len(dynamic) == 1
    assert dynamic[0]["role"] == "user"
    for marker in ("WORKING-MEMORY-MARKER", "MEMORY-MARKER", "PROFILE-MARKER"):
        assert marker in dynamic[0]["content"]
    # It sits immediately before the turn's user message.
    assert agent.provider.seen[0][-1]["content"] == "hello there"
    assert agent.provider.seen[0][-2].get("_dynamic_context") is True

    # Scaffolding is stripped from the stored transcript.
    assert not any(m.get("_dynamic_context") for m in agent.messages)


def test_static_prompt_is_rendered_once_per_signature(monkeypatch):
    """Repeating a turn must not re-render the prompt; a new section set does."""
    renders = []
    real_render = core_module.build_system_prompt

    def counting_render(*args, **kwargs):
        renders.append(kwargs.get("sections"))
        return real_render(*args, **kwargs)

    monkeypatch.setattr(core_module, "build_system_prompt", counting_render)
    monkeypatch.setattr(core_module, "prompt_files_signature", lambda: ())

    agent = _make_agent([])
    agent._refresh_memory_context("do the thing", None)
    agent._refresh_memory_context("do the thing", None)
    assert len(renders) == 1

    # A turn that pulls in other sections renders once more, then is cached.
    agent._refresh_memory_context("send an email to a@b.com", None)
    agent._refresh_memory_context("send an email to a@b.com", None)
    assert len(renders) == 2


def test_cached_prompt_is_reused_verbatim(monkeypatch):
    """The cached string is returned for the same signature, not re-rendered."""
    agent = _make_agent([])
    mine = match_sections("do the thing", None, "cli")
    first = agent._static_system_prompt(mine)
    second = agent._static_system_prompt(set(mine))
    assert first == second
    assert first is second


def test_volatile_tail_is_not_in_the_cacheable_prompt():
    """include_volatile=False must drop the mutating parts of the prompt."""
    static = build_system_prompt("", "", channel="cli", sections={"code"},
                                 include_volatile=False)
    assert "Active Credentials & Integrations Status" not in static
    assert "## User Profile" not in static

    full = build_system_prompt("", "", channel="cli", sections={"code"})
    assert full.startswith(static)
    assert "Active Credentials & Integrations Status" in full
    assert "Active Credentials & Integrations Status" in build_volatile_context()


def test_section_render_is_order_independent():
    """A set's iteration order must not leak into the prompt bytes."""
    a = build_system_prompt("", "", channel="cli", sections={"code", "email", "web"},
                            include_volatile=False)
    b = build_system_prompt("", "", channel="cli", sections={"web", "email", "code"},
                            include_volatile=False)
    assert a == b


def test_prompt_files_signature_is_stable_and_non_empty():
    first = prompt_files_signature()
    assert first
    assert first == prompt_files_signature()


def test_match_sections_keeps_the_original_keyword_rules():
    matched = match_sections("fix the github repo", None, "cli")
    assert {"workspace", "code"} <= matched
    assert "email" in match_sections("write to a@b.com", None, "cli")
    # When running as the telegram bot the telegram service rules are dropped.
    assert "telegram" not in match_sections("telegram settings", {"telegram", "code"}, "telegram")
