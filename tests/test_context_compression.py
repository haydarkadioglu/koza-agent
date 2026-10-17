"""Context compression must actually run (K-11).

The compressor used to live under ``core/``, where the top-level ``core.py``
module shadowed the package (``'core' is not a package``), and it imported
Hermes-only modules (``hermes_cli``, ``hermes_constants``, ``agent.models_dev``)
that do not exist in koza.  Every turn therefore logged "Context compressor
skipped" and long conversations grew until the provider rejected them.

These tests pin the koza-native wiring: the modules import from ``utils/``,
the summary call goes out over HTTP to koza's own provider, and a broken
summary endpoint fails open instead of breaking the turn.
"""
import importlib
import importlib.util
import json
import os
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core import Agent
from utils import base_url_host_matches, base_url_hostname
from utils.auxiliary_llm import call_llm, is_connection_error, resolve_runtime
from utils.context_compressor import ContextCompressor
from utils.model_metadata import (
    MINIMUM_CONTEXT_LENGTH,
    estimate_messages_tokens_rough,
)

SUMMARY_TEXT = "## Active Task\nShip K-11 — context compression."


class _StubSummaryServer:
    """A local OpenAI-compatible endpoint that records what it was sent."""

    def __init__(self):
        self.requests = []
        self.status = 200
        self.content = SUMMARY_TEXT
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) or b"{}"
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {"raw": raw.decode("utf-8", "replace")}
                outer.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": body,
                })
                payload = json.dumps({
                    "id": "stub-1",
                    "model": body.get("model", "stub"),
                    "choices": [{
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": outer.content},
                    }],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                }).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # silence the test log
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def summary_server():
    server = _StubSummaryServer()
    try:
        yield server
    finally:
        server.stop()


def _long_history(turns: int = 30, chars: int = 6000):
    """A conversation large enough (>> MINIMUM_CONTEXT_LENGTH) to compress."""
    messages = [{"role": "system", "content": "You are koza."}]
    for i in range(turns):
        messages.append({"role": "user", "content": f"question {i}: " + "u" * chars})
        messages.append({"role": "assistant", "content": f"answer {i}: " + "a" * chars})
    return messages


class _FakeProvider:
    name = "deepseek"
    _model = "deepseek-chat"
    supports_vision = False
    supports_thinking = False

    def __init__(self, base_url):
        self._client = types.SimpleNamespace(base_url=base_url, api_key="test-key")


def _make_compressor(server) -> ContextCompressor:
    return ContextCompressor(
        model="deepseek-chat",
        provider="deepseek",
        base_url=server.base_url,
        api_key="test-key",
        config_context_length=128000,
        quiet_mode=True,
    )


# ---------------------------------------------------------------- wiring ----

def test_core_resolves_to_the_module_not_a_shadowing_package():
    """`core` must stay the core.py module: a core/ package breaks imports."""
    spec = importlib.util.find_spec("core")
    assert spec is not None
    assert spec.submodule_search_locations is None


def test_compressor_and_engine_import_from_utils():
    compressor = importlib.import_module("utils.context_compressor")
    engine = importlib.import_module("utils.context_engine")
    assert compressor.ContextCompressor.__module__ == "utils.context_compressor"
    assert engine.ContextEngine.__module__ == "utils.context_engine"
    assert issubclass(compressor.ContextCompressor, engine.ContextEngine)


def test_no_hermes_only_imports_remain():
    for module in ("utils.context_compressor", "utils.context_engine", "utils.model_metadata"):
        importlib.import_module(module)


def test_base_url_host_helpers():
    assert base_url_hostname("https://api.openai.com/v1") == "api.openai.com"
    assert base_url_hostname("api.openai.com/v1") == "api.openai.com"
    assert base_url_hostname("http://user:pw@localhost:11434") == "localhost"
    assert base_url_hostname("") == ""
    assert base_url_host_matches("https://openrouter.ai/api/v1", "openrouter.ai")
    assert base_url_host_matches("https://eu.api.openai.com/v1", "openai.com")
    assert not base_url_host_matches("https://notopenai.com/v1", "openai.com")


# ----------------------------------------------------------- aux llm call ----

def test_resolve_runtime_needs_a_provider(monkeypatch):
    monkeypatch.setattr(config, "load_config", dict)
    with pytest.raises(RuntimeError):
        resolve_runtime({})


def test_resolve_runtime_falls_back_to_configured_model(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {
        "model": "configured-model",
        "providers": {"deepseek": {"base_url": "https://api.deepseek.com/v1",
                                   "api_key": "k"}},
    })
    runtime = resolve_runtime({"provider": "deepseek", "api_key": "k"})
    assert runtime["base_url"] == "https://api.deepseek.com/v1"
    assert runtime["model"] == "configured-model"


def test_is_connection_error_classification():
    import requests

    assert is_connection_error(requests.exceptions.ConnectionError("nope"))
    assert is_connection_error(requests.exceptions.Timeout("slow"))
    assert is_connection_error(RuntimeError("incomplete chunked read"))
    assert not is_connection_error(ValueError("bad json"))


def test_call_llm_posts_to_the_given_runtime(summary_server):
    response = call_llm(
        task="compression",
        main_runtime={"provider": "deepseek", "base_url": summary_server.base_url,
                      "api_key": "test-key", "model": "deepseek-chat"},
        messages=[{"role": "user", "content": "summarise this"}],
        max_tokens=64,
    )
    assert response.choices[0].message.content == SUMMARY_TEXT
    sent = summary_server.requests[-1]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["body"]["model"] == "deepseek-chat"
    assert sent["body"]["stream"] is False
    assert sent["body"]["max_tokens"] == 64


# ------------------------------------------------------------ compressor ----

def test_compress_summarises_middle_turns_over_http(summary_server):
    messages = _long_history()
    rough = estimate_messages_tokens_rough(messages)
    assert rough > MINIMUM_CONTEXT_LENGTH  # the fixture is big enough to compress

    compressor = _make_compressor(summary_server)
    assert compressor.should_compress(rough)

    result = compressor.compress(messages, current_tokens=rough)

    assert len(result) < len(messages), "middle turns were not compacted"
    flattened = "\n".join(str(m.get("content")) for m in result)
    assert "Ship K-11" in flattened, "the summary never reached the history"
    assert "CONTEXT COMPACTION" in flattened, "summary was not marked as a handoff"
    assert result[0]["role"] == "system"
    assert compressor._previous_summary  # kept for the next iterative pass

    sent = summary_server.requests[-1]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    prompt = sent["body"]["messages"][0]["content"]
    assert "TURNS TO SUMMARIZE" in prompt
    assert "question 3" in prompt  # middle turns made it into the prompt


def test_compress_fails_open_when_the_summary_endpoint_breaks(summary_server):
    summary_server.status = 500
    messages = _long_history()
    rough = estimate_messages_tokens_rough(messages)

    compressor = _make_compressor(summary_server)
    result = compressor.compress(messages, current_tokens=rough)  # must not raise

    assert isinstance(result, list) and result
    assert result[0]["role"] == "system"


def test_should_compress_respects_the_threshold(summary_server):
    compressor = _make_compressor(summary_server)
    assert not compressor.should_compress(compressor.threshold_tokens - 1)
    assert compressor.should_compress(compressor.threshold_tokens)


# ------------------------------------------------------------ agent path ----

def test_agent_runtime_describes_the_active_provider(summary_server):
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(summary_server.base_url)
    agent.cfg = {"model": "deepseek-chat", "provider": "deepseek"}
    runtime = agent._provider_runtime()
    assert runtime == {
        "model": "deepseek-chat",
        "provider": "deepseek",
        "base_url": summary_server.base_url,
        "api_key": "test-key",
    }


def test_agent_compresses_a_long_history(summary_server, monkeypatch):
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(summary_server.base_url)
    agent.cfg = {"model": "deepseek-chat", "provider": "deepseek",
                 "context_compression": {"enabled": True, "threshold_percent": 0.10}}
    agent.messages = _long_history()
    before = len(agent.messages)

    monkeypatch.setattr("utils.model_metadata.get_model_context_length",
                        lambda *a, **k: 128000)

    agent._maybe_compress_context()

    assert len(agent.messages) < before
    flattened = "\n".join(str(m.get("content")) for m in agent.messages)
    assert "CONTEXT COMPACTION" in flattened
    assert summary_server.requests, "no summary request was made"


def test_agent_skips_compression_when_disabled(summary_server):
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(summary_server.base_url)
    agent.cfg = {"context_compression": {"enabled": False}}
    agent.messages = _long_history()
    before = len(agent.messages)

    agent._maybe_compress_context()

    assert len(agent.messages) == before
    assert summary_server.requests == []


def test_agent_skips_the_probe_for_short_conversations(summary_server):
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(summary_server.base_url)
    agent.cfg = {}
    agent.messages = [{"role": "system", "content": "short"}, {"role": "user", "content": "hi"}]

    agent._maybe_compress_context()

    assert summary_server.requests == []
    assert len(agent.messages) == 2


def test_missing_cfg_is_fail_open(summary_server):
    """A partially-built agent must not take the turn down with it."""
    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(summary_server.base_url)
    agent.messages = _long_history()

    agent._maybe_compress_context()  # no cfg attribute at all — must not raise

    assert agent.messages and agent.messages[0]["role"] == "system"


def test_turn_compresses_the_history_before_the_first_round(summary_server, monkeypatch):
    """The compressor runs at the call site inside the conversation loop."""
    monkeypatch.setattr("utils.model_metadata.get_model_context_length",
                        lambda *a, **k: 128000)

    agent = Agent.__new__(Agent)
    agent.provider = _FakeProvider(summary_server.base_url)
    agent.cfg = {"model": "deepseek-chat", "provider": "deepseek",
                 "context_compression": {"enabled": True, "threshold_percent": 0.10}}
    agent.messages = _long_history()
    agent._cancel = threading.Event()
    agent._busy = False
    agent._router = None
    agent.tool_progress_callback = None
    agent.permission_callback = None
    agent._pre_fetch_links = lambda user_input: iter(())
    agent._refresh_memory_context = lambda *a, **k: None
    agent._resolve_available_tools = lambda *a, **k: []
    agent._execute_tool = lambda name, args: "ran"
    before = len(agent.messages)

    class _StreamingProvider(_FakeProvider):
        def stream_chat(self, messages, tools=None, cancel_event=None):
            yield "ok"

    agent.provider = _StreamingProvider(summary_server.base_url)

    list(agent._run_conversation_loop("carry on"))

    flattened = "\n".join(str(m.get("content")) for m in agent.messages)
    assert "CONTEXT COMPACTION" in flattened
    assert len(agent.messages) < before
    assert summary_server.requests, "the summariser was never called"
