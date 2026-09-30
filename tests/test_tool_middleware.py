"""Tests for the tool middleware pipeline (tools/middleware.py).

The pipeline must call the tool handler exactly once per tool call and must not
replay the downstream chain when something already executed. Guards that reject
a call before delegating are vetoes, not retries.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.middleware import (
    DEFAULT_MIDDLEWARES,
    MiddlewareChain,
    logging_middleware,
    ssrf_guard_middleware,
)


class _Agent:
    """Minimal agent stub — the chain only forwards it to middlewares."""

    def auto_save(self, title: str = "", summary: str = "") -> str:
        return "saved"


def test_raising_handler_runs_exactly_once():
    runs = []

    def terminal(args):
        runs.append(args)
        raise RuntimeError("handler blew up")

    chain = MiddlewareChain(list(DEFAULT_MIDDLEWARES))
    with pytest.raises(RuntimeError, match="handler blew up"):
        chain.execute(_Agent(), "run_terminal", {"command": "ls"}, terminal)

    assert len(runs) == 1


@pytest.mark.parametrize("depth", [0, 1, 4, 8])
def test_handler_runs_once_regardless_of_chain_depth(depth):
    """Regression: 2**depth invocations came from replaying the chain on error."""
    runs = []

    def passthrough(agent, name, args, next_call):
        return next_call(args)

    def terminal(args):
        runs.append(args)
        raise ValueError("boom")

    chain = MiddlewareChain([passthrough] * depth)
    with pytest.raises(ValueError, match="boom"):
        chain.execute(_Agent(), "run_terminal", {}, terminal)

    assert len(runs) == 1


def test_guard_veto_never_reaches_the_handler():
    runs = []

    def guard(agent, name, args, next_call):
        raise ValueError("blocked by policy")

    def terminal(args):
        runs.append(args)
        return "handler ran"

    chain = MiddlewareChain([guard, logging_middleware])
    with pytest.raises(ValueError, match="blocked by policy"):
        chain.execute(_Agent(), "web_fetch", {"url": "http://127.0.0.1/"}, terminal)

    assert runs == []


def test_ssrf_guard_blocks_private_url_without_running_the_handler():
    runs = []

    def terminal(args):
        runs.append(args)
        return "leaked"

    chain = MiddlewareChain([ssrf_guard_middleware])
    with pytest.raises(ValueError, match="SSRF violation"):
        chain.execute(_Agent(), "web_fetch", {"url": "http://127.0.0.1:8080/admin"}, terminal)

    assert runs == []


def test_late_middleware_failure_does_not_replay_earlier_layers():
    runs = []

    def first(agent, name, args, next_call):
        runs.append("first")
        return next_call(args)

    def second(agent, name, args, next_call):
        runs.append("second")
        raise ValueError("second failed")

    def terminal(args):
        runs.append("handler")
        return "ok"

    chain = MiddlewareChain([first, second])
    with pytest.raises(ValueError, match="second failed"):
        chain.execute(_Agent(), "run_terminal", {}, terminal)

    assert runs == ["first", "second"]


def test_middleware_can_recover_from_a_downstream_failure():
    """Error-handling middleware keeps working: catching downstream is allowed."""

    def rescue(agent, name, args, next_call):
        try:
            return next_call(args)
        except RuntimeError:
            return "recovered"

    def terminal(args):
        raise RuntimeError("tool failed")

    chain = MiddlewareChain([rescue])
    assert chain.execute(_Agent(), "run_terminal", {}, terminal) == "recovered"


def test_arguments_flow_through_each_layer_once():
    seen = []

    def add_flag(agent, name, args, next_call):
        seen.append("flag")
        return next_call({**args, "flag": True})

    def observe(agent, name, args, next_call):
        seen.append(("observe", dict(args)))
        return next_call(args)

    def terminal(args):
        seen.append(("terminal", dict(args)))
        return args

    chain = MiddlewareChain([add_flag, observe])
    result = chain.execute(_Agent(), "run_terminal", {"a": 1}, terminal)

    assert result == {"a": 1, "flag": True}
    assert seen == [
        "flag",
        ("observe", {"a": 1, "flag": True}),
        ("terminal", {"a": 1, "flag": True}),
    ]


def test_failed_tool_is_logged_to_working_memory_exactly_once(monkeypatch):
    from skills import working_memory

    entries = []
    monkeypatch.setattr(
        working_memory, "wm_add", lambda **kwargs: entries.append(kwargs) or "ok"
    )

    def terminal(args):
        raise RuntimeError("tool failed")

    chain = MiddlewareChain(list(DEFAULT_MIDDLEWARES))
    with pytest.raises(RuntimeError, match="tool failed"):
        chain.execute(_Agent(), "run_terminal", {"command": "ls"}, terminal)

    assert len(entries) == 1
    assert entries[0]["event_type"] == "error"
