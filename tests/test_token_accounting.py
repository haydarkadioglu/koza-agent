"""Real token accounting: provider usage is recorded and used for preflight (K-15).

``core.py`` used to size the conversation with ``len(str(messages)) // 4`` and
never read the ``usage`` block providers send back.  These tests pin the new
path end to end: the OpenAI-compatible providers ask for usage, surface it as a
``__usage__`` stream event, the agent loop records it in its ``TokenLedger``,
and the compression preflight prefers that exact number over the guess.
"""
import os
import sys
import threading
from types import SimpleNamespace
from typing import ClassVar

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Agent, ToolLoopGuardrail  # noqa: I001 - sys.path bootstrap above
from providers.base import create_openai_stream
from providers.openai_provider import OpenAIProvider
from utils.model_metadata import MINIMUM_CONTEXT_LENGTH, estimate_messages_tokens_rough
from utils.token_accounting import TokenLedger, normalize_usage, usage_event


# ── normalize_usage ───────────────────────────────────────────────────────────

def test_normalize_openai_dict():
    assert normalize_usage({"prompt_tokens": 120, "completion_tokens": 7, "total_tokens": 127}) == {
        "prompt_tokens": 120,
        "completion_tokens": 7,
        "total_tokens": 127,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }


def test_normalize_object_and_alternate_spellings():
    # The OpenAI SDK returns pydantic objects, not dicts.
    sdk_usage = SimpleNamespace(prompt_tokens=10, completion_tokens=3, total_tokens=13)
    assert normalize_usage(sdk_usage)["prompt_tokens"] == 10
    # Anthropic spelling.
    assert normalize_usage({"input_tokens": 40, "output_tokens": 2})["prompt_tokens"] == 40
    # Gemini spelling.
    assert normalize_usage({"prompt_token_count": 55, "candidates_token_count": 5})["total_tokens"] == 60


def test_normalize_reads_nested_cache_and_reasoning_buckets():
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "prompt_tokens_details": {"cached_tokens": 80},
        "completion_tokens_details": {"reasoning_tokens": 12},
    }
    normalized = normalize_usage(usage)
    assert normalized["cache_read_tokens"] == 80
    assert normalized["reasoning_tokens"] == 12


def test_normalize_returns_empty_for_unusable_payloads():
    assert normalize_usage(None) == {}
    assert normalize_usage({}) == {}
    assert normalize_usage({"prompt_tokens": "n/a"}) == {}
    assert usage_event({}) is None


# ── request helper ────────────────────────────────────────────────────────────

class _Recorder:
    def __init__(self, fail_first=None):
        self.calls = []
        self.fail_first = fail_first

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError(self.fail_first)
        return "stream"


def _client(recorder):
    return SimpleNamespace(chat=SimpleNamespace(completions=recorder))


def test_stream_request_asks_for_usage():
    recorder = _Recorder()
    assert create_openai_stream(_client(recorder), {"model": "m", "stream": True}) == "stream"
    assert recorder.calls[0]["stream_options"] == {"include_usage": True}


def test_stream_request_retries_without_stream_options_when_rejected():
    recorder = _Recorder(fail_first="400 unknown field: stream_options")
    assert create_openai_stream(_client(recorder), {"model": "m", "stream": True}) == "stream"
    assert len(recorder.calls) == 2
    assert "stream_options" not in recorder.calls[1]


def test_stream_request_does_not_swallow_unrelated_errors():
    recorder = _Recorder(fail_first="401 invalid api key")
    with pytest.raises(RuntimeError):
        create_openai_stream(_client(recorder), {"model": "m", "stream": True})
    assert len(recorder.calls) == 1


# ── OpenAI provider emits the usage event ─────────────────────────────────────

def _chunk(content=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=None)
    choices = [SimpleNamespace(delta=delta, finish_reason=None)] if content is not None else []
    return SimpleNamespace(choices=choices, usage=usage)


def _provider_with_chunks(chunks):
    recorder = _Recorder()
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = _client(recorder)
    provider._model = "gpt-test"
    provider._cfg = {}

    def create(**kwargs):
        recorder.calls.append(kwargs)
        return iter(chunks)

    recorder.create = create
    return provider, recorder


def test_provider_streams_text_then_usage_event():
    provider, recorder = _provider_with_chunks([
        _chunk("hello "),
        _chunk("world"),
        # OpenAI sends usage on a final chunk with an empty choices list.
        _chunk(usage=SimpleNamespace(prompt_tokens=321, completion_tokens=9, total_tokens=330)),
    ])
    events = list(provider.stream_chat([{"role": "user", "content": "hi"}]))

    assert "".join(e for e in events if isinstance(e, str)) == "hello world"
    usage_events = [e for e in events if isinstance(e, dict) and e.get("__usage__")]
    assert len(usage_events) == 1
    assert usage_events[0]["__usage__"]["prompt_tokens"] == 321
    assert recorder.calls[0]["stream_options"] == {"include_usage": True}


def test_provider_emits_no_usage_event_when_server_omits_it():
    provider, _ = _provider_with_chunks([_chunk("only text")])
    events = list(provider.stream_chat([{"role": "user", "content": "hi"}]))
    assert events == ["only text"]


# ── TokenLedger ───────────────────────────────────────────────────────────────

def _rough(messages):
    return estimate_messages_tokens_rough(messages)


def test_ledger_falls_back_to_rough_estimate_until_usage_arrives():
    ledger = TokenLedger(_rough)
    messages = [{"role": "user", "content": "x" * 400}]
    assert ledger.prompt_tokens(messages) == _rough(messages)
    assert not ledger.has_real_usage


def test_ledger_prefers_real_usage_and_adds_only_appended_messages():
    ledger = TokenLedger(_rough)
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "x" * 800}]
    ledger.mark_request(len(messages))
    ledger.record({"prompt_tokens": 1000, "completion_tokens": 50}, message_count=len(messages))
    assert ledger.prompt_tokens(messages) == 1000

    messages = messages + [
        {"role": "assistant", "content": "answer"},
        {"role": "tool", "content": "y" * 400},
    ]
    assert ledger.prompt_tokens(messages) == 1000 + _rough(messages[2:])
    assert ledger.last_completion_tokens == 50
    assert ledger.samples == 1


def test_ledger_ignores_empty_usage_and_resets():
    ledger = TokenLedger(_rough)
    messages = [{"role": "user", "content": "x" * 40}]
    assert ledger.record({}) is False
    assert ledger.prompt_tokens(messages) == _rough(messages)

    ledger.record({"prompt_tokens": 10, "completion_tokens": 1}, message_count=len(messages))
    ledger.reset()
    assert not ledger.has_real_usage
    assert ledger.prompt_tokens(messages) == _rough(messages)


def test_ledger_falls_back_after_history_is_rewritten():
    ledger = TokenLedger(_rough)
    ledger.record({"prompt_tokens": 5000, "completion_tokens": 10}, message_count=6)
    shorter = [{"role": "system", "content": "s"}, {"role": "user", "content": "x" * 100}]
    # Compression rewrote the history: the mark points past the end, so the
    # exact number no longer describes these messages.
    assert ledger.prompt_tokens(shorter) == _rough(shorter)


# ── agent loop wiring ─────────────────────────────────────────────────────────

class _UsageProvider:
    name = "fake"
    supports_vision = False
    supports_thinking = False
    _model = "fake-model"

    def __init__(self, rounds):
        self._rounds = list(rounds)

    def stream_chat(self, messages, tools=None, cancel_event=None):
        if not self._rounds:
            return
        yield from self._rounds.pop(0)

    @property
    def model(self):
        return self._model


class _FixedRouter:
    def classify(self, text):
        return SimpleNamespace(prompt_sections={"workspace"}, tool_groups=set())


def _make_agent(rounds):
    agent = Agent.__new__(Agent)
    agent.provider = _UsageProvider(rounds)
    agent.cfg = {}
    agent.channel = "cli"
    agent._system_prompt_cache = {}
    agent._pending_dynamic_context = ""
    agent.messages = [{"role": "system", "content": "placeholder"}]
    agent._cancel = threading.Event()
    agent._busy = False
    agent._router = _FixedRouter()
    agent._guardrail = ToolLoopGuardrail()
    agent.permission_callback = None
    agent.tool_progress_callback = None
    agent._activated_tools = set()
    agent._pre_fetch_links = lambda user_input: iter(())
    agent._maybe_build_rolling_summary = lambda: None
    agent._auto_save_credentials = lambda user_input: None
    agent._resolve_available_tools = lambda *a, **k: []
    agent._execute_tool = lambda name, args: f"ran {name}"
    agent._maybe_compress_context = lambda: None
    agent._token_ledger = TokenLedger()
    return agent


def test_loop_records_provider_usage():
    agent = _make_agent([[
        "answer",
        {"__usage__": {"prompt_tokens": 4321, "completion_tokens": 12, "total_tokens": 4333}},
    ]])
    events = list(agent._run_conversation_loop("hello"))

    assert "answer" in "".join(e.get("token", "") for e in events if e.get("type") == "text")
    assert agent._token_ledger.last_prompt_tokens == 4321
    assert agent._token_ledger.last_completion_tokens == 12
    assert agent._token_ledger.last_model == "fake-model"


def test_usage_event_never_leaks_into_the_visible_answer():
    agent = _make_agent([[
        "done",
        {"__usage__": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}},
    ]])
    events = list(agent._run_conversation_loop("hello"))
    text = "".join(e.get("token", "") for e in events if e.get("type") == "text")
    assert text == "done"
    assert "__usage__" not in text


# ── compression preflight uses the real number ───────────────────────────────

class _StubCompressor:
    instances: ClassVar[list] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.seen_tokens = None
        _StubCompressor.instances.append(self)

    def should_compress(self, tokens):
        self.seen_tokens = tokens
        return True

    def compress(self, messages, current_tokens=None):
        return messages


def _preflight_agent(ledger):
    agent = Agent.__new__(Agent)
    agent.cfg = {"context_compression": {"enabled": True}}
    agent.messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "short"}]
    agent._token_ledger = ledger
    agent._provider_runtime = lambda: {"model": "gpt-test", "provider": "openai", "base_url": "", "api_key": ""}
    return agent


def test_preflight_uses_real_provider_usage(monkeypatch):
    import utils.context_compressor as compressor_module

    monkeypatch.setattr(compressor_module, "ContextCompressor", _StubCompressor)
    _StubCompressor.instances = []

    ledger = TokenLedger()
    ledger.record({"prompt_tokens": 900_000, "completion_tokens": 10}, message_count=2)
    agent = _preflight_agent(ledger)
    agent._maybe_compress_context()

    assert _StubCompressor.instances, "compression was never attempted"
    # The exact number, not the ~10 tokens the two short messages would estimate.
    assert _StubCompressor.instances[0].seen_tokens >= MINIMUM_CONTEXT_LENGTH
    # The measurement boundary is invalidated by the rewrite.
    assert ledger.measured_at is None


def test_preflight_skips_short_conversations_without_usage(monkeypatch):
    import utils.context_compressor as compressor_module

    monkeypatch.setattr(compressor_module, "ContextCompressor", _StubCompressor)
    _StubCompressor.instances = []

    agent = _preflight_agent(TokenLedger())
    agent._maybe_compress_context()
    assert _StubCompressor.instances == []
