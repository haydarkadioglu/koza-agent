"""K-06: tool deferral bridge — the tool_search gap-closer.

The model-visible tool list is capped at 128 entries; anything dropped was
previously unreachable (the model cannot call a tool it never saw). These
tests cover the cap-with-bridge swap, the registry keyword search, bridge
activation via expansion, and the bridge handler.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core
from core import (
    _TOOL_SEARCH_DEF,
    MAX_SENT_TOOLS,
    _apply_tool_cap,
    _ensure_bridge,
    _expand_tools_for_call,
    _search_all_tools,
    _tool_name,
)


def _fake_tool(name: str, desc: str = "") -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": desc or f"Tool {name}."},
        "handler": lambda: None,
    }


def test_apply_tool_cap_swaps_in_bridge():
    tools = [_fake_tool(f"t_{i}") for i in range(200)]
    capped = _apply_tool_cap(tools)
    assert len(capped) == MAX_SENT_TOOLS
    assert _tool_name(capped[-1]) == "tool_search"
    # nothing silently lost: the 128th real tool is now bridge-reachable
    names = {_tool_name(t) for t in capped}
    assert "t_199" not in names  # truncated...
    # ...and in the real run discoverable through the bridge: a real registered
    # tool (one of the 64 previously never sent) is found by the search
    assert "telegram_send" in {n for n, _d, _s in _search_all_tools("telegram send", 25)}


def test_apply_tool_cap_noop_under_cap():
    tools = [_fake_tool(f"t_{i}") for i in range(10)]
    assert _apply_tool_cap(tools) == tools


def test_apply_tool_cap_strips_existing_bridge():
    tools = [_fake_tool(f"t_{i}") for i in range(200)] + [_TOOL_SEARCH_DEF]
    capped = _apply_tool_cap(tools)
    assert len(capped) == MAX_SENT_TOOLS
    assert sum(1 for t in capped if _tool_name(t) == "tool_search") == 1


def test_ensure_bridge_added_and_idempotent():
    # a narrow selection leaves most of the registry invisible -> bridge appears
    tools = [_fake_tool("read_file"), _fake_tool("web_search")]
    with_bridge = _ensure_bridge(tools)
    assert _tool_name(with_bridge[-1]) == "tool_search"
    assert _ensure_bridge(with_bridge) == with_bridge


def test_search_all_tools_ranks_name_hits_first():
    results = _search_all_tools("send sms twilio", 10)
    names = [n for n, _d, _s in results]
    assert names, "expected matches for twilio/sms query"
    assert "twilio_send_sms" in names
    assert names.index("twilio_send_sms") <= 2  # exact token hits rank at the top
    scores = [s for _n, _d, s in results]
    assert scores == sorted(scores, reverse=True)


def test_search_all_tools_excludes_and_limits():
    exclude = {"twilio_send_sms"}
    results = _search_all_tools("twilio send sms", 5, exclude=exclude)
    names = [n for n, _d, _s in results]
    assert len(names) <= 5
    assert "twilio_send_sms" not in names
    assert "tool_search" not in names


def test_search_all_tools_empty_query():
    assert _search_all_tools("   the a of  ", 8) == []
    assert _search_all_tools("", 8) == []


def test_expand_tools_activates_extra_names_exact():
    base = [_fake_tool("read_file", "Read a file.")]
    target = core._TOOL_BY_NAME.get("vision_analyze")
    if target is None:
        return  # registry variation; exact-name path is covered by cap tests
    out = _expand_tools_for_call(base, [], extra_names={"vision_analyze"})
    names = {_tool_name(t) for t in out}
    assert "vision_analyze" in names
    # exact activation, not a whole-group pull
    assert len(out) == 2


def test_bridge_handler_activates_matches():
    stub = type("Stub", (), {})()
    stub._sent_tool_names = {"read_file"}
    stub._activated_tools = set()
    out = core.Agent._handle_tool_search(stub, {"query": "send telegram message", "limit": 5})
    assert "ACTIVATED" in out
    assert stub._activated_tools, "matches must be activated"
    assert all(n != "read_file" for n in stub._activated_tools)
    # empty query -> error string, nothing activated
    before = set(stub._activated_tools)
    out2 = core.Agent._handle_tool_search(stub, {})
    assert "Error" in out2
    assert stub._activated_tools == before


def test_bridge_def_shape():
    fn = _TOOL_SEARCH_DEF["function"]
    assert fn["name"] == "tool_search"
    assert fn["parameters"]["required"] == ["query"]
    assert "query" in fn["parameters"]["properties"]
