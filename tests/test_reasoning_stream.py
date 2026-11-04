"""Native reasoning deltas are surfaced for display, never kept as content.

Reasoning models (DeepSeek r1/reasoner, OpenAI o-series) stream their
reasoning in a separate delta field. It used to be dropped, so the user paid
for tokens they never saw. The providers now emit it as a ``__reasoning__``
chunk and the agent loop turns that into a ``thinking_delta`` event — but the
reasoning must never leak into the answer text or the history sent back.
"""
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Agent, ToolLoopGuardrail
from providers.base import extract_reasoning_delta
from providers.deepseek_provider import DeepSeekProvider
from providers.openai_provider import OpenAIProvider
from tui.event_adapter import stream_event_to_record

# ── extractor ────────────────────────────────────────────────────────────────

def test_reasoning_read_from_plain_attribute():
    assert extract_reasoning_delta(SimpleNamespace(reasoning_content="step 1")) == "step 1"
    assert extract_reasoning_delta(SimpleNamespace(reasoning="step 2")) == "step 2"


def test_reasoning_read_from_model_extra():
    delta = SimpleNamespace(content=None, model_extra={"reasoning_content": "hidden"})
    assert extract_reasoning_delta(delta) == "hidden"


def test_absent_reasoning_is_empty():
    assert extract_reasoning_delta(SimpleNamespace(content="hi")) == ""
    assert extract_reasoning_delta(SimpleNamespace(reasoning_content=None, model_extra=None)) == ""
    assert extract_reasoning_delta(None) == ""


def test_non_string_reasoning_is_ignored_without_raising():
    assert extract_reasoning_delta(SimpleNamespace(reasoning_content={"x": 1})) == ""
    assert extract_reasoning_delta(SimpleNamespace(model_extra={"reasoning": 42})) == ""

    class _Exploding:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    assert extract_reasoning_delta(_Exploding()) == ""


# ── providers ────────────────────────────────────────────────────────────────

def _delta(content=None, reasoning=None, tool_calls=None):
    return SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=tool_calls)


def _chunk(delta, finish_reason=None):
    return SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
    )


def _tool_call_delta(index, call_id, name, arguments):
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class _FakeStream(list):
    def close(self):
        pass


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        return _FakeStream(self._chunks)


def _stream_chunks():
    return [
        _chunk(_delta(reasoning="Let me think.\n")),
        _chunk(_delta(reasoning="Weigh options.")),
        _chunk(_delta(content="Hello ")),
        _chunk(_delta(content="world")),
        _chunk(_delta(tool_calls=[_tool_call_delta(0, "call-1", "read_file", '{"path":')])),
        _chunk(_delta(tool_calls=[_tool_call_delta(0, None, None, ' "a.py"}')]), "tool_calls"),
    ]


def _run_provider(cls):
    provider = cls.__new__(cls)
    provider._client = _FakeClient(_stream_chunks())
    provider._model = "reasoner-model"
    return list(provider.stream_chat([{"role": "user", "content": "hi"}]))


def _assert_reasoning_kept_out_of_text(items):
    assert items[0] == {"__reasoning__": True, "token": "Let me think.\n"}
    reasoning = [i["token"] for i in items if isinstance(i, dict) and i.get("__reasoning__")]
    assert "".join(reasoning) == "Let me think.\nWeigh options."
    assert "".join(i for i in items if isinstance(i, str)) == "Hello world"

    tool_chunks = [i for i in items if isinstance(i, dict) and i.get("__tool_chunk__")]
    assert len(tool_chunks) == 1
    assert tool_chunks[0]["name"] == "read_file"
    assert tool_chunks[0]["id"] == "call-1"
    assert tool_chunks[0]["args_chunk"] == '{"path": "a.py"}'


def test_deepseek_stream_emits_reasoning_separately():
    _assert_reasoning_kept_out_of_text(_run_provider(DeepSeekProvider))


def test_openai_stream_emits_reasoning_separately():
    _assert_reasoning_kept_out_of_text(_run_provider(OpenAIProvider))


# ── the conversation loop ────────────────────────────────────────────────────

class _FakeProvider:
    name = "fake"
    supports_vision = False
    supports_thinking = True
    _model = "fake-model"

    def __init__(self, rounds):
        self._rounds = list(rounds)

    def stream_chat(self, messages, tools=None, cancel_event=None):
        yield from (self._rounds.pop(0) if self._rounds else [])


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
    agent._execute_tool = lambda name, args: "ran"
    return agent


def test_loop_yields_thinking_delta_and_keeps_reasoning_out_of_history():
    agent = _make_agent([
        [
            {"__reasoning__": True, "token": "secret chain of thought"},
            "The answer ",
            "is 4.",
            {"__finish_reason__": "stop"},
        ],
    ])

    events = list(agent._run_conversation_loop("what is 2+2?"))
    types = [e["type"] for e in events]

    assert "thinking_delta" in types
    assert "text" in types
    assert types.index("thinking_delta") < types.index("text")
    deltas = [e for e in events if e["type"] == "thinking_delta"]
    assert deltas == [{"type": "thinking_delta", "token": "secret chain of thought"}]
    assert "".join(e["token"] for e in events if e["type"] == "text") == "The answer is 4."

    for message in agent.messages:
        assert "secret chain of thought" not in str(message.get("content") or "")
        assert "reasoning_content" not in message


# ── display adapter ──────────────────────────────────────────────────────────

def test_event_adapter_shows_last_reasoning_line_as_status():
    channel, text = stream_event_to_record({"type": "thinking_delta", "token": "step 2\nweigh options"})
    assert channel == "status"
    assert "weigh options" in text
    assert "step 2" not in text


def test_event_adapter_truncates_long_reasoning_line():
    channel, text = stream_event_to_record({"type": "thinking_delta", "token": "x" * 500})
    assert channel == "status"
    assert text.count("x") == 80


def test_event_adapter_ignores_empty_reasoning():
    assert stream_event_to_record({"type": "thinking_delta", "token": ""}) == ("ignore", "")
    assert stream_event_to_record({"type": "thinking_delta", "token": "\n  \n"}) == ("ignore", "")
