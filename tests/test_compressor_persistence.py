import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Agent
from utils.model_metadata import MINIMUM_CONTEXT_LENGTH


def _runtime():
    return {
        "model": "test-model",
        "provider": "test-provider",
        "base_url": "https://example.test/v1",
        "api_key": "test-key",
    }


def _section():
    return {"threshold_percent": 0.5, "summary_model": "summary-model"}


def test_context_compressor_is_reused_for_unchanged_configuration(monkeypatch):
    created = []

    class StubCompressor:
        def __init__(self, **kwargs):
            created.append(self)

    monkeypatch.setattr("utils.context_compressor.ContextCompressor", StubCompressor)
    agent = Agent.__new__(Agent)

    first = agent._context_compressor(_runtime(), _section())
    second = agent._context_compressor(_runtime(), _section())

    assert second is first
    assert created == [first]


@pytest.mark.parametrize(
    ("changed", "field", "value"),
    [
        ("runtime", "model", "other-model"),
        ("runtime", "provider", "other-provider"),
        ("runtime", "base_url", "https://other.test/v1"),
        ("runtime", "api_key", "other-key"),
        ("section", "threshold_percent", 0.75),
        ("section", "summary_model", "other-summary-model"),
    ],
)
def test_context_compressor_is_replaced_when_configuration_changes(
    monkeypatch, changed, field, value
):
    class StubCompressor:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr("utils.context_compressor.ContextCompressor", StubCompressor)
    agent = Agent.__new__(Agent)
    runtime = _runtime()
    section = _section()
    first = agent._context_compressor(runtime, section)

    if changed == "runtime":
        runtime[field] = value
    else:
        section[field] = value

    second = agent._context_compressor(runtime, section)

    assert second is not first
    assert agent._compressor_cache[1] is second


def test_reset_drops_context_compressor_cache(monkeypatch):
    agent = Agent.__new__(Agent)
    agent._compressor_cache = ((), object())
    agent._ctx = SimpleNamespace(messages=[], summary="")
    agent._pending_dynamic_context = ""
    agent._session_progress = 1.0
    agent.cfg = {}
    agent._static_system_prompt = lambda _channel: "system prompt"
    agent.auto_save = lambda: "saved"
    monkeypatch.setattr("skills.working_memory.wm_clear", lambda: None)
    monkeypatch.setattr("config.save_config", lambda _cfg: None)

    agent.reset()

    assert getattr(agent, "_compressor_cache", None) is None


def test_short_conversation_does_not_construct_context_compressor(monkeypatch):
    constructed = []

    def unexpected_construction(**kwargs):
        constructed.append(kwargs)

    monkeypatch.setattr(
        "utils.context_compressor.ContextCompressor", unexpected_construction
    )
    monkeypatch.setattr(
        "utils.model_metadata.estimate_messages_tokens_rough",
        lambda _messages: MINIMUM_CONTEXT_LENGTH - 1,
    )
    agent = Agent.__new__(Agent)
    agent.cfg = {"context_compression": {"enabled": True}}
    agent.messages = [{"role": "user", "content": "short"}]

    agent._maybe_compress_context()

    assert constructed == []
    assert getattr(agent, "_compressor_cache", None) is None


def test_raising_compressor_constructor_fails_open(monkeypatch):
    constructed = []

    def broken_constructor(**kwargs):
        constructed.append(kwargs)
        raise RuntimeError("constructor failed")

    monkeypatch.setattr(
        "utils.context_compressor.ContextCompressor", broken_constructor
    )
    monkeypatch.setattr(
        "utils.model_metadata.estimate_messages_tokens_rough",
        lambda _messages: MINIMUM_CONTEXT_LENGTH + 1,
    )
    agent = Agent.__new__(Agent)
    agent.cfg = {"context_compression": {"enabled": True}}
    agent._provider_runtime = lambda: _runtime()
    agent.messages = [{"role": "user", "content": "keep this history"}]
    original_messages = agent.messages

    agent._maybe_compress_context()

    assert len(constructed) == 1
    assert agent.messages is original_messages
    assert getattr(agent, "_compressor_cache", None) is None
