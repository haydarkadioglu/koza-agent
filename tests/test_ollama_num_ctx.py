"""K-32: OllamaProvider must send options.num_ctx / num_predict per request so
the server does not silently truncate the prompt at its default window."""

import json

import pytest

import providers.ollama_provider as ollama_mod
from providers.ollama_provider import OllamaProvider

LOCAL_URL = "http://localhost:11434"


class FakeResponse:
    def __init__(self, data=None, lines=()):
        self._data = data if data is not None else {"message": {"content": "ok"}}
        self._lines = list(lines)

    def raise_for_status(self):
        return None

    def json(self):
        return self._data

    def iter_lines(self):
        yield from self._lines

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePost:
    def __init__(self, data=None):
        self.data = data
        self.payloads = []

    def __call__(self, url, json=None, stream=False, timeout=None):
        self.payloads.append(json)
        if stream:
            lines = [
                _dumps({"message": {"content": "o"}}),
                _dumps({"message": {"content": "k"}, "done": True}),
            ]
            return FakeResponse(lines=lines)
        return FakeResponse(data=self.data)


def _dumps(obj):
    return json.dumps(obj).encode()


class ProbeCounter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def __call__(self, model, base_url, api_key=""):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _never_probe(*args, **kwargs):
    raise AssertionError("num_ctx detection must not run")


@pytest.fixture
def fake_post(monkeypatch):
    post = FakePost()
    monkeypatch.setattr(ollama_mod.requests, "post", post)
    return post


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(ollama_mod, "is_local_endpoint", lambda url: True)


def _messages():
    return [{"role": "user", "content": "hi"}]


def _drain(provider):
    return list(provider.stream_chat(_messages()))


def test_explicit_num_ctx_sent_without_probe(monkeypatch, fake_post, local):
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", _never_probe)
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m", "num_ctx": 4096})

    provider.chat(_messages())
    assert _drain(provider) == ["o", "k"]

    assert [p["options"] for p in fake_post.payloads] == [{"num_ctx": 4096}] * 2
    assert fake_post.payloads[1]["stream"] is True


def test_detected_num_ctx_sent_for_local_endpoint(monkeypatch, fake_post, local):
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", ProbeCounter(32768))
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m"})

    provider.chat(_messages())

    assert fake_post.payloads[0]["options"] == {"num_ctx": 32768}


def test_detection_runs_once_per_instance(monkeypatch, fake_post, local):
    probe = ProbeCounter(32768)
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", probe)
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m"})

    provider.chat(_messages())
    _drain(provider)
    provider.chat(_messages())

    assert probe.calls == 1
    assert [p["options"] for p in fake_post.payloads] == [{"num_ctx": 32768}] * 3


def test_detection_none_sends_no_options_and_is_cached(monkeypatch, fake_post, local):
    probe = ProbeCounter(None)
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", probe)
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m"})

    provider.chat(_messages())
    _drain(provider)
    provider.chat(_messages())

    assert probe.calls == 1
    assert all("options" not in p for p in fake_post.payloads)


def test_detection_error_does_not_break_chat(monkeypatch, fake_post, local):
    probe = ProbeCounter(error=RuntimeError("server gone"))
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", probe)
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m"})

    result = provider.chat(_messages())

    assert result == {"content": "ok", "tool_calls": None}
    assert "options" not in fake_post.payloads[0]
    provider.chat(_messages())
    assert probe.calls == 1


def test_context_length_caps_detected_value(monkeypatch, fake_post, local):
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", ProbeCounter(131072))
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m", "context_length": 8192})

    provider.chat(_messages())

    assert fake_post.payloads[0]["options"] == {"num_ctx": 8192}


def test_context_length_does_not_cap_explicit_num_ctx(monkeypatch, fake_post, local):
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", _never_probe)
    provider = OllamaProvider(
        {"base_url": LOCAL_URL, "model": "m", "num_ctx": 4096, "context_length": 8192}
    )

    provider.chat(_messages())

    assert fake_post.payloads[0]["options"] == {"num_ctx": 4096}


def test_num_predict_alone(monkeypatch, fake_post, local):
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", ProbeCounter(None))
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m", "num_predict": 256})

    provider.chat(_messages())

    assert fake_post.payloads[0]["options"] == {"num_predict": 256}


def test_num_predict_with_explicit_num_ctx(monkeypatch, fake_post, local):
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", _never_probe)
    provider = OllamaProvider(
        {"base_url": LOCAL_URL, "model": "m", "num_ctx": 4096, "num_predict": 256}
    )

    _drain(provider)

    assert fake_post.payloads[0]["options"] == {"num_ctx": 4096, "num_predict": 256}


def test_hosted_endpoint_is_never_probed(monkeypatch, fake_post):
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", _never_probe)
    provider = OllamaProvider({"base_url": "https://ollama.com/v1", "model": "m"})

    provider.chat(_messages())
    _drain(provider)

    assert all("options" not in p for p in fake_post.payloads)


@pytest.mark.parametrize("bad", ["auto", -5, True])
def test_garbage_num_ctx_falls_through_to_detection(monkeypatch, fake_post, bad):
    monkeypatch.setattr(ollama_mod, "is_local_endpoint", lambda url: False)
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", _never_probe)
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m", "num_ctx": bad})

    provider.chat(_messages())

    assert "options" not in fake_post.payloads[0]


@pytest.mark.parametrize("bad", ["auto", -5, True])
def test_garbage_num_ctx_uses_detected_value(monkeypatch, fake_post, local, bad):
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", ProbeCounter(16384))
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m", "num_ctx": bad})

    provider.chat(_messages())

    assert fake_post.payloads[0]["options"] == {"num_ctx": 16384}


def test_tool_calls_still_parse_alongside_options(monkeypatch, local):
    data = {
        "message": {
            "content": "",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "a.txt"}}},
                {"function": {"name": "list_dir", "arguments": {"path": "."}}},
            ],
        }
    }
    post = FakePost(data=data)
    monkeypatch.setattr(ollama_mod.requests, "post", post)
    monkeypatch.setattr(ollama_mod, "query_ollama_num_ctx", ProbeCounter(32768))
    provider = OllamaProvider({"base_url": LOCAL_URL, "model": "m"})

    result = provider.chat(_messages(), tools=[{"type": "function"}])

    assert result["tool_calls"] == [
        {"id": "ollama_0", "name": "read_file", "arguments": {"path": "a.txt"}},
        {"id": "ollama_1", "name": "list_dir", "arguments": {"path": "."}},
    ]
    assert post.payloads[0]["options"] == {"num_ctx": 32768}
    assert post.payloads[0]["tools"] == [{"type": "function"}]
