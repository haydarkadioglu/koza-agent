"""One outsider must not serialize a whole batch of independent tool calls.

The loop used to run a batch concurrently only if every call was on a fixed
allowlist. The planner now splits each batch into ordered parallel/sequential
segments, keeping conflicting paths apart, and the loop drives those segments
while still answering every tool_call_id exactly once, in call order.
"""
import itertools
import json
import os
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core
import utils.tool_batch_planner as planner
from config import default_config
from core import _PARALLEL_SAFE_TOOLS, Agent, ToolGuardrailDecision, ToolLoopGuardrail
from utils.tool_batch_planner import (
    DEFAULT_NEVER_PARALLEL_TOOLS,
    DEFAULT_PARALLEL_SAFE_TOOLS,
    batch_is_fully_parallel,
    plan_tool_batch,
    tool_batching_policy,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _call(name, call_id=None, **args):
    return {"id": call_id or f"{name}-{args}", "name": name, "arguments": args}


def _read(path):
    return _call("read_file", path=path)


def _write(path):
    return _call("write_file", path=path, content="x")


def _plan(calls, **kw):
    kw.setdefault("execution_cwd", "/work")
    return plan_tool_batch(calls, **kw)


def _shape(segments):
    return [(kind, [c["id"] for c in segment]) for kind, segment in segments]


def _flatten(segments):
    return [c for _, segment in segments for c in segment]


def _assert_legal(segments, calls):
    assert _flatten(segments) == calls
    for kind, segment in segments:
        assert kind in ("parallel", "sequential")
        assert segment
        if kind == "parallel":
            assert len(segment) >= 2
    for left, right in itertools.pairwise(segments):
        assert not (left[0] == right[0] == "sequential")


class _FakeProvider:
    name = "fake"
    supports_vision = False
    supports_thinking = False
    _model = "fake-model"

    def __init__(self, rounds):
        self._rounds = list(rounds)

    def stream_chat(self, messages, tools=None, cancel_event=None):
        if self._rounds:
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


def _make_agent(rounds, cfg=None, tool_fn=None):
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
    agent._execute_tool = tool_fn or (lambda name, args: f"ran {name}")
    return agent


def _batch_round(*calls):
    chunks = [
        _tool_chunk(i, name, json.dumps(args), call_id=f"c{i}")
        for i, (name, args) in enumerate(calls)
    ]
    return chunks + [_finish()]


def _timed(log, duration=0.2):
    def tool(name, args):
        start = time.monotonic()
        time.sleep(duration)
        log.append((name, args.get("path"), start, time.monotonic()))
        return f"ran {name}"
    return tool


def _tool_ids(agent):
    return [m["tool_call_id"] for m in agent.messages if m.get("role") == "tool"]


def _text(events):
    return "".join(e["token"] for e in events if e.get("type") == "text")


# ── planner: segments ────────────────────────────────────────────────────────


def test_defaults_keep_the_old_allowlist_and_the_core_alias():
    assert _PARALLEL_SAFE_TOOLS is DEFAULT_PARALLEL_SAFE_TOOLS
    assert core._PARALLEL_SAFE_TOOLS >= {"web_search", "read_file", "wm_add"}
    assert not DEFAULT_PARALLEL_SAFE_TOOLS & DEFAULT_NEVER_PARALLEL_TOOLS
    assert {
        "ask_user", "delegate_task", "spawn_subagent", "start_coding_session",
        "start_tracked_coding_task", "browser_task", "run_command", "run_python",
        "run_node", "run_script", "run_jupyter_cell",
    } <= DEFAULT_NEVER_PARALLEL_TOOLS


def test_reads_and_a_write_on_a_third_path_form_one_parallel_segment():
    calls = [_read("a"), _read("b"), _write("c")]
    assert _plan(calls) == [("parallel", calls)]
    assert batch_is_fully_parallel(calls, execution_cwd="/work")


def test_write_on_a_read_path_does_not_join_the_reader():
    calls = [_read("a"), _write("a"), _read("b")]
    assert _plan(calls) == [("sequential", calls[:1]), ("parallel", calls[1:])]
    assert not batch_is_fully_parallel(calls, execution_cwd="/work")


def test_writes_to_different_paths_are_parallel():
    calls = [_write("x"), _write("y")]
    assert _plan(calls) == [("parallel", calls)]


def test_writes_to_one_path_never_overlap():
    calls = [_write("x"), _write("x")]
    assert _plan(calls) == [("sequential", calls)]


def test_readers_may_share_a_path_and_a_subtree():
    calls = [_read("a/b.txt"), _read("a/b.txt"), _call("list_dir", path="a")]
    assert _plan(calls) == [("parallel", calls)]


def test_writer_conflicts_with_an_ancestor_reservation():
    calls = [_call("list_dir", path="pkg"), _write("pkg/mod.py")]
    assert _plan(calls) == [("sequential", calls)]


def test_sibling_with_a_common_name_prefix_is_not_an_overlap():
    calls = [_write("/work/pkg"), _write("/work/pkg2/mod.py")]
    assert _plan(calls) == [("parallel", calls)]


def test_filesystem_root_overlaps_everything():
    calls = [_call("list_dir", path="/"), _write("/etc/x")]
    assert _plan(calls) == [("sequential", calls)]


def test_relative_absolute_and_home_spellings_are_one_path(monkeypatch):
    monkeypatch.setenv("HOME", "/home/me")
    assert _plan([_read("a"), _write("/work/./a")]) == [
        ("sequential", [_read("a"), _write("/work/./a")])
    ]
    calls = [_read("~/notes.md"), _write("/home/me/notes.md")]
    assert _plan(calls) == [("sequential", calls)]


def test_symlink_to_the_same_file_conflicts(tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("x")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    calls = [_read(str(real)), _write(str(link))]
    assert _plan(calls) == [("sequential", calls)]


def test_relative_paths_resolve_against_the_execution_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = [_read("a"), _write(str(tmp_path / "a"))]
    assert plan_tool_batch(calls) == [("sequential", calls)]
    assert plan_tool_batch(calls, execution_cwd="/elsewhere") == [("parallel", calls)]


def test_barrier_is_never_inside_a_parallel_segment():
    calls = [_read("a"), _call("run_command", command="ls"), _read("b")]
    segments = _plan(calls)
    _assert_legal(segments, calls)
    assert segments == [("sequential", calls)]

    calls = [_read("a"), _read("b"), _call("run_command", command="ls"), _read("c"), _read("d")]
    segments = _plan(calls)
    _assert_legal(segments, calls)
    assert _shape(segments) == [
        ("parallel", [calls[0]["id"], calls[1]["id"]]),
        ("sequential", [calls[2]["id"]]),
        ("parallel", [calls[3]["id"], calls[4]["id"]]),
    ]


def test_unknown_tool_is_a_barrier():
    calls = [_read("a"), _call("mcp_something", x=1), _read("b")]
    assert _plan(calls) == [("sequential", calls)]


def test_stateless_allowlisted_tools_join_a_run_unscoped():
    calls = [_call("web_search", query="q"), _write("a"), _call("wm_list")]
    assert _plan(calls) == [("parallel", calls)]


def test_scoped_call_without_a_path_is_a_barrier():
    for bad in ({}, {"path": ""}, {"path": 5}, {"paths": ["a", 5]}, {"path": {"a": 1}}, {"path": "a\0b"}):
        calls = [_read("x"), _call("write_file", call_id="w", **bad), _read("y")]
        assert _plan(calls) == [("sequential", calls)], bad
    # A reader with no path argument reads the tool's own default (cwd), so it keeps
    # its place in the run instead of serializing the batch.
    calls = [_read("x"), _call("read_file", call_id="r"), _read("y")]
    assert _plan(calls) == [("parallel", calls)]
    # That implicit cwd scope still conflicts with a writer that lands inside it.
    calls = [_call("read_file", call_id="r"), _write("x")]
    assert _plan(calls) == [("sequential", calls)]


def test_every_path_argument_key_and_lists_are_reserved():
    for key in ("path", "file", "directory", "dir", "target"):
        calls = [_call("search_files", **{key: "a"}), _write("a/b")]
        assert _plan(calls) == [("sequential", calls)], key
    calls = [_call("read_file", paths=["z", "a"]), _write("a")]
    assert _plan(calls) == [("sequential", calls)]


def test_non_dict_and_json_string_arguments_are_barriers():
    for args in ('{"path": "a"}', None, 7, ["a"]):
        for name in ("read_file", "web_search"):
            calls = [_read("x"), {"id": "bad", "name": name, "arguments": args}, _read("y")]
            assert _plan(calls) == [("sequential", calls)], (name, args)


def test_order_and_coverage_hold_across_batches():
    pool = [
        _read("a"), _write("a"), _read("b"), _write("b/c"), _call("list_dir", path="b"),
        _call("run_command", command="ls"), _call("web_search", query="q"),
        _call("unknown"), {"id": "x", "name": "read_file", "arguments": "{}"},
    ]
    batches = [pool, pool[::-1], pool[:2], pool[1:] + pool[:1], pool + pool, [pool[0]], []]
    for rotation in range(len(pool)):
        batches.append(pool[rotation:] + pool[:rotation])
    for batch in batches:
        _assert_legal(_plan(batch), batch)


def test_single_call_and_empty_batches():
    call = _read("a")
    assert _plan([call]) == [("sequential", [call])]
    assert _plan([]) == []
    assert not batch_is_fully_parallel([])


# ── planner: config and failure ──────────────────────────────────────────────


def test_disabled_runs_everything_sequentially():
    calls = [_read("a"), _read("b")]
    assert _plan(calls, settings={"tool_batching": {"enabled": False}}) == [("sequential", calls)]


def test_config_tool_lists_are_honoured():
    plugin = _call("plugin_lookup", q=1)
    calls = [_read("a"), plugin]
    assert _plan(calls) == [("sequential", calls)]
    assert _plan(calls, settings={"tool_batching": {"parallel_safe_tools": ["plugin_lookup"]}}) == [
        ("parallel", calls)
    ]
    calls = [_read("a"), _read("b")]
    assert _plan(calls, settings={"tool_batching": {"never_parallel_tools": ["read_file"]}}) == [
        ("sequential", calls)
    ]


def test_never_parallel_beats_parallel_safe():
    calls = [_read("a"), _call("run_command", command="ls")]
    settings = {"tool_batching": {"parallel_safe_tools": ["run_command"]}}
    assert _plan(calls, settings=settings) == [("sequential", calls)]


def test_path_scoped_off_falls_back_to_the_allowlist():
    settings = {"tool_batching": {"path_scoped": False}}
    calls = [_read("a"), _read("a")]
    assert _plan(calls, settings=settings) == [("parallel", calls)]
    assert _plan([_write("x"), _write("y")], settings=settings)[0][0] == "sequential"
    # Allowlisting a writer must not let it run unscoped.
    settings["tool_batching"]["parallel_safe_tools"] = ["write_file"]
    assert _plan([_write("x"), _write("x")], settings=settings)[0][0] == "sequential"


def test_extra_path_scoped_tools_from_config():
    settings = {"tool_batching": {"path_scoped_writers": ["plugin_save"]}}
    calls = [_call("plugin_save", path="a"), _read("a")]
    assert _plan(calls, settings=settings) == [("sequential", calls)]
    calls = [_call("plugin_save", path="a"), _read("b")]
    assert _plan(calls, settings=settings) == [("parallel", calls)]


def test_garbage_config_falls_back_to_defaults():
    calls = [_read("a"), _read("b")]
    for settings in (
        None, "nope", [], 3,
        {"tool_batching": "nope"}, {"tool_batching": ["x"]}, {"tool_batching": None},
        {"tool_batching": {"parallel_safe_tools": 5, "never_parallel_tools": {"a": 1}}},
        {"tool_batching": {"parallel_safe_tools": [1, None], "unknown_key": object()}},
        {"tool_batching": {"enabled": None, "path_scoped": []}},
    ):
        policy = tool_batching_policy(settings)
        assert policy["enabled"] is True and policy["path_scoped"] is True
        assert policy["parallel_safe"] == DEFAULT_PARALLEL_SAFE_TOOLS
        assert policy["never_parallel"] == DEFAULT_NEVER_PARALLEL_TOOLS
        assert _plan(calls, settings=settings) == [("parallel", calls)]


def test_a_string_is_read_as_one_tool_name():
    policy = tool_batching_policy({"tool_batching": {"never_parallel_tools": "read_file"}})
    assert "read_file" in policy["never_parallel"]


def test_enabled_accepts_the_string_a_config_tool_may_store():
    assert tool_batching_policy({"tool_batching": {"enabled": "false"}})["enabled"] is False
    assert tool_batching_policy({"tool_batching": {"enabled": "true"}})["enabled"] is True


def test_default_config_ships_the_section():
    section = default_config()["tool_batching"]
    assert section["enabled"] is True and section["path_scoped"] is True
    assert section["parallel_safe_tools"] == [] and section["never_parallel_tools"] == []
    assert tool_batching_policy(default_config())["enabled"] is True


def test_internal_failure_degrades_to_one_sequential_segment(monkeypatch):
    calls = [_read("a"), _read("b")]

    def boom(*a, **k):
        raise RuntimeError("planner bug")

    monkeypatch.setattr(planner, "_admit", boom)
    assert _plan(calls) == [("sequential", calls)]
    monkeypatch.undo()
    monkeypatch.setattr(planner, "tool_batching_policy", boom)
    assert _plan(calls) == [("sequential", calls)]
    assert plan_tool_batch(None) == [("sequential", None)] or plan_tool_batch(None) == []
    assert plan_tool_batch(5) == [("sequential", 5)]


# ── loop: concurrency ────────────────────────────────────────────────────────


def test_reads_run_concurrently_next_to_a_write_on_a_third_path(tmp_path):
    a, b, c = (str(tmp_path / n) for n in "abc")
    log = []
    rounds = [
        _batch_round(("read_file", {"path": a}), ("read_file", {"path": b}),
                     ("write_file", {"path": c, "content": "x"})),
        ["All done."],
    ]
    agent = _make_agent(rounds, tool_fn=_timed(log))
    events = list(agent._run_conversation_loop("go"))

    spans = {path: (start, end) for _, path, start, end in log}
    assert spans[a][0] < spans[b][1] and spans[b][0] < spans[a][1], "the reads must overlap"
    assert _tool_ids(agent) == ["c0", "c1", "c2"]
    assert _text(events) == "All done."


def test_same_path_read_and_write_do_not_overlap(tmp_path):
    a = str(tmp_path / "a")
    log = []
    rounds = [
        _batch_round(("read_file", {"path": a}), ("write_file", {"path": a, "content": "x"})),
        ["All done."],
    ]
    agent = _make_agent(rounds, tool_fn=_timed(log, duration=0.1))
    list(agent._run_conversation_loop("go"))

    (first, _, _, first_end), (second, _, second_start, _) = log
    assert (first, second) == ("read_file", "write_file")
    assert first_end <= second_start


def test_mixed_batch_answers_every_id_in_call_order(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    rounds = [
        _batch_round(("read_file", {"path": a}), ("read_file", {"path": b}),
                     ("run_command", {"command": "ls"}),
                     ("write_file", {"path": a, "content": "x"})),
        ["Finished."],
    ]
    agent = _make_agent(rounds)
    events = list(agent._run_conversation_loop("go"))
    assert _tool_ids(agent) == ["c0", "c1", "c2", "c3"]
    assert _text(events) == "Finished."


def test_slow_first_call_keeps_call_order_in_a_parallel_segment(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")

    def tool(name, args):
        if args["path"] == a:
            time.sleep(0.2)
        return "ok"

    rounds = [_batch_round(("read_file", {"path": a}), ("read_file", {"path": b})), ["Done."]]
    agent = _make_agent(rounds, tool_fn=tool)
    list(agent._run_conversation_loop("go"))
    assert _tool_ids(agent) == ["c0", "c1"]


def test_denied_call_keeps_call_order_in_a_parallel_segment(tmp_path):
    a, b, c = (str(tmp_path / n) for n in "abc")
    rounds = [
        _batch_round(("read_file", {"path": a}), ("read_file", {"path": b}),
                     ("read_file", {"path": c})),
        ["Done."],
    ]
    agent = _make_agent(rounds)
    agent.permission_callback = lambda name, args: args["path"] != b
    list(agent._run_conversation_loop("go"))
    assert _tool_ids(agent) == ["c0", "c1", "c2"]
    assert "Permission denied" in agent.messages[-3]["content"] or any(
        m.get("tool_call_id") == "c1" and "Permission denied" in m["content"] for m in agent.messages
    )


def test_blocked_call_keeps_call_order_in_a_parallel_segment(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    rounds = [_batch_round(("read_file", {"path": a}), ("read_file", {"path": b})), ["Done."]]
    agent = _make_agent(rounds)
    real_before = agent._guardrail.before_call
    agent._guardrail.before_call = lambda name, args: (
        (True, "blocked") if args["path"] == a else real_before(name, args)
    )
    list(agent._run_conversation_loop("go"))
    assert _tool_ids(agent) == ["c0", "c1"]


def test_batching_disabled_keeps_calls_apart(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    log = []
    rounds = [_batch_round(("read_file", {"path": a}), ("read_file", {"path": b})), ["Done."]]
    agent = _make_agent(rounds, cfg={"tool_batching": {"enabled": False}},
                        tool_fn=_timed(log, duration=0.05))
    list(agent._run_conversation_loop("go"))
    assert log[0][3] <= log[1][2]


def test_permanent_failure_in_an_early_segment_survives_later_segments(tmp_path):
    a = str(tmp_path / "a")

    class _Provider(_FakeProvider):
        def chat(self, messages, tools=None):
            return {"content": "Reported the failure."}

    agent = _make_agent([], tool_fn=lambda name, args: (
        "PERMANENT FAILURE: nope" if name == "read_file" else "ok"
    ))
    agent.provider = _Provider([
        _batch_round(("read_file", {"path": a}), ("run_command", {"command": "ls"}),
                     ("web_search", {"query": "x"}), ("wm_list", {})),
        ["never reached"],
    ])
    agent._trim_messages = lambda: agent.messages
    events = list(agent._run_conversation_loop("go"))
    assert _text(events) == "Reported the failure."


# ── loop: halt and interrupt across segments ─────────────────────────────────


def _segmented_round(tmp_path):
    """Sequential, parallel, sequential: three segments for the driver."""
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    return _batch_round(
        ("run_command", {"command": "first"}),
        ("read_file", {"path": a}), ("read_file", {"path": b}),
        ("run_command", {"command": "last"}),
    )


def test_guardrail_halt_answers_the_later_segments(tmp_path):
    ran = []
    agent = _make_agent([_segmented_round(tmp_path), ["never reached"]])

    def tool(name, args):
        ran.append(name)
        agent._guardrail._halt_decision = ToolGuardrailDecision(
            "halt", "test", "stop", name, 3
        )
        return "ok"

    agent._execute_tool = tool
    events = list(agent._run_conversation_loop("go"))

    assert ran == ["run_command"], "the halt raised by the last call of a segment must stop the batch"
    assert _tool_ids(agent) == ["c0", "c1", "c2", "c3"]
    assert "I stopped instead of looping" in _text(events)


def test_guardrail_halt_from_a_parallel_segment_stops_the_next_one(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    ran = []
    agent = _make_agent([
        _batch_round(("read_file", {"path": a}), ("read_file", {"path": b}),
                     ("run_command", {"command": "later"})),
        ["never reached"],
    ])

    def tool(name, args):
        ran.append(name)
        agent._guardrail._halt_decision = ToolGuardrailDecision("halt", "test", "stop", name, 3)
        return "ok"

    agent._execute_tool = tool
    list(agent._run_conversation_loop("go"))
    assert "run_command" not in ran
    assert _tool_ids(agent) == ["c0", "c1", "c2"]


def test_cancel_between_segments_answers_the_rest_with_one_event(tmp_path):
    ran = []
    agent = _make_agent([_segmented_round(tmp_path), ["never reached"]])

    def tool(name, args):
        ran.append(name)
        agent._cancel.set()
        return "ok"

    agent._execute_tool = tool
    events = list(agent._run_conversation_loop("go"))

    assert sum(e.get("type") == "interrupted" for e in events) == 1
    assert ran == ["run_command"]
    assert _tool_ids(agent) == ["c0", "c1", "c2", "c3"]
    assert sum(m.get("content") == "Process interrupted by user." for m in agent.messages) == 3


def test_consumer_that_stops_on_interrupted_leaves_no_orphans(tmp_path):
    """The CLI, TUI dispatcher and daemon all `break` on the interrupted event."""
    agent = _make_agent([_segmented_round(tmp_path), ["never reached"]])

    def tool(name, args):
        agent._cancel.set()
        return "ok"

    agent._execute_tool = tool
    stream = agent._run_conversation_loop("go")
    for event in stream:
        if event.get("type") == "interrupted":
            break
    stream.close()
    assert _tool_ids(agent) == ["c0", "c1", "c2", "c3"]


def test_interrupt_during_a_parallel_segment_answers_everything(tmp_path):
    never = threading.Event()
    agent = _make_agent([_segmented_round(tmp_path)[1:], ["never reached"]])
    # Drop the first call: chunks now start with the parallel reads.

    def tool(name, args):
        agent._cancel.set()
        never.wait(0.3)
        return "ok"

    agent._execute_tool = tool
    events = list(agent._run_conversation_loop("go"))
    assert sum(e.get("type") == "interrupted" for e in events) == 1
    assert _tool_ids(agent) == ["c1", "c2", "c3"]


def test_cancel_before_a_parallel_segment_starts_no_worker(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    ran = []
    agent = _make_agent([], tool_fn=lambda name, args: ran.append(name))
    agent._untrusted_policy = SimpleNamespace(wrap=lambda name, text: text)
    agent._cancel.set()
    calls = [_write(a), _write(b)]
    outcome = None
    stream = agent._run_parallel_batch(calls)
    try:
        while True:
            next(stream)
    except StopIteration as stop:
        outcome = stop.value
    assert outcome == ("interrupted", False)
    assert ran == []
    assert _tool_ids(agent) == [c["id"] for c in calls]


def test_append_interrupted_tool_results_answers_each_call():
    agent = _make_agent([])
    agent._append_interrupted_tool_results([_read("a"), _read("b")])
    answers = agent.messages[1:]
    assert [m["tool_call_id"] for m in answers] == [_read("a")["id"], _read("b")["id"]]
    assert all(m["content"] == "Process interrupted by user." and m["role"] == "tool" for m in answers)
