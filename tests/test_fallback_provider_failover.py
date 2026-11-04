"""K-30: FallbackProvider must not fail over after a partial stream, on cancel,
or on non-retryable errors such as context overflow."""

import threading

import pytest

from providers.error_classifier import FailoverReason, classify_api_error
from providers.fallback_provider import FallbackProvider
from utils.failover_policy import FailoverPolicy


class FakeProvider:
    name = "fake"
    _model = "fake-model"

    def __init__(self, chunks=(), error=None, chat_result=None):
        self.chunks = list(chunks)
        self.error = error
        self.chat_result = chat_result
        self.started = False
        self.consumed = []
        self.chat_calls = 0
        self.chat_kwargs = []

    def stream_chat(self, messages, tools=None, cancel_event=None):
        self.started = True
        for chunk in self.chunks:
            self.consumed.append(chunk)
            yield chunk
        if self.error is not None:
            raise self.error

    def chat(self, messages, tools=None, stream=False):
        self.chat_calls += 1
        self.chat_kwargs.append({"tools": tools, "stream": stream})
        if self.error is not None:
            raise self.error
        return self.chat_result

    def list_models(self):
        return ["fake-model"]


def _drain(provider, cancel_event=None):
    received = []
    with pytest.raises(Exception) as exc_info:
        # Explicit loop: chunks seen before the exception must be kept.
        for chunk in provider.stream_chat([], cancel_event=cancel_event):
            received.append(chunk)  # noqa: PERF402
    return received, exc_info.value


def _collect(provider, cancel_event=None):
    return list(provider.stream_chat([], cancel_event=cancel_event))


def test_partial_stream_reraises_and_never_starts_fallback():
    err = RuntimeError("boom")
    primary = FakeProvider(["Hel", "lo"], error=err)
    fallback = FakeProvider(["FALLBACK"])

    received, raised = _drain(FallbackProvider(primary, fallback))

    assert received == ["Hel", "lo"]
    assert raised is err
    assert fallback.started is False
    assert fallback.consumed == []


def test_failure_before_first_chunk_fails_over():
    primary = FakeProvider(error=Exception("429 rate limit"))
    fallback = FakeProvider(["A", "B", "C"])

    received = _collect(FallbackProvider(primary, fallback))

    assert received == ["A", "B", "C"]
    assert primary.consumed == []
    assert fallback.consumed == ["A", "B", "C"]


def test_cancelled_stream_does_not_fail_over():
    err = Exception("429 rate limit")
    primary = FakeProvider(error=err)
    fallback = FakeProvider(["FALLBACK"])
    cancel = threading.Event()
    cancel.set()

    received, raised = _drain(FallbackProvider(primary, fallback), cancel_event=cancel)

    assert received == []
    assert raised is err
    assert fallback.started is False


def test_context_overflow_reaches_caller_instead_of_fallback():
    err = Exception("This model's maximum context length is 8192 tokens")
    assert classify_api_error(err).reason is FailoverReason.context_overflow
    primary = FakeProvider(error=err)
    fallback = FakeProvider(["FALLBACK"])

    received, raised = _drain(FallbackProvider(primary, fallback))

    assert received == []
    assert raised is err
    assert fallback.started is False


def test_auth_error_still_fails_over():
    err = Exception("401 Invalid API key")
    classified = classify_api_error(err)
    assert classified.reason is FailoverReason.auth
    assert classified.retryable is False
    primary = FakeProvider(error=err)
    fallback = FakeProvider(["FALLBACK"])

    assert _collect(FallbackProvider(primary, fallback)) == ["FALLBACK"]
    assert fallback.consumed == ["FALLBACK"]


def test_configured_blocked_reason_prevents_failover():
    err = Exception("429 rate limit")
    primary = FakeProvider(error=err)
    fallback = FakeProvider(["FALLBACK"])
    policy = FailoverPolicy(blocked_reasons=("rate_limit",))

    received, raised = _drain(FallbackProvider(primary, fallback, policy=policy))

    assert received == []
    assert raised is err
    assert fallback.started is False


def test_chat_context_overflow_propagates_without_fallback():
    err = Exception("This model's maximum context length is 8192 tokens")
    primary = FakeProvider(error=err)
    fallback = FakeProvider(chat_result={"content": "FALLBACK"})

    with pytest.raises(Exception) as exc_info:
        FallbackProvider(primary, fallback).chat([])

    assert exc_info.value is err
    assert fallback.chat_calls == 0


def test_chat_server_error_fails_over():
    primary = FakeProvider(error=Exception("500 Internal Server Error"))
    fallback = FakeProvider(chat_result={"content": "FALLBACK"})

    result = FallbackProvider(primary, fallback).chat([])

    assert result == {"content": "FALLBACK"}
    assert primary.chat_calls == 1
    assert fallback.chat_calls == 1
    assert primary.started is False
    assert fallback.started is False


def test_default_policy_used_when_none_given():
    provider = FallbackProvider(FakeProvider(), FakeProvider())
    assert provider.policy == FailoverPolicy()


def test_fallback_provider_is_instantiable_under_its_interface():
    """Regression: the class used to miss the abstract name/list_models members,
    so get_provider() raised TypeError for any config with fallback_provider set."""
    primary = FakeProvider(chat_result={"content": "PRIMARY"})
    fallback = FakeProvider(chat_result={"content": "FALLBACK"})
    provider = FallbackProvider(primary, fallback)

    assert provider.name == "fake"
    assert provider.model == "fake-model"
    assert provider.list_models() == ["fake-model"]


def test_chat_forwards_tools_and_stream_through_the_sanitizing_wrapper():
    """core.py calls provider.chat(..., stream=...) via SanitizingProviderWrapper;
    a missing stream parameter made that call raise TypeError when a fallback was set."""
    from providers.base import SanitizingProviderWrapper

    primary = FakeProvider(chat_result={"content": "PRIMARY"})
    fallback = FakeProvider(chat_result={"content": "FALLBACK"})
    wrapper = SanitizingProviderWrapper(FallbackProvider(primary, fallback))

    result = wrapper.chat([{"role": "user", "content": "hi"}], tools=[], stream=True)

    assert result == {"content": "PRIMARY"}
    assert primary.chat_kwargs == [{"tools": [], "stream": True}]
    assert wrapper.name == "fake"


@pytest.mark.parametrize(
    "cfg",
    [
        None,
        {},
        {"fallback": {}},
        {"fallback": None},
        {"fallback": {"blocked_reasons": "rate_limit"}},
        {"blocked_reasons": "rate_limit"},
        {"fallback": {"blocked_reasons": ["rate_limit", 3]}},
        "not a dict",
    ],
)
def test_from_config_malformed_falls_back_to_defaults(cfg):
    assert FailoverPolicy.from_config(cfg) == FailoverPolicy()


def test_from_config_accepts_both_shapes():
    wrapped = FailoverPolicy.from_config({"fallback": {"blocked_reasons": ["rate_limit"]}})
    bare = FailoverPolicy.from_config({"blocked_reasons": ["rate_limit"]})

    assert wrapped.blocked_reasons == ("rate_limit",)
    assert bare == wrapped


def test_from_config_keeps_unknown_reason_names_which_never_match():
    policy = FailoverPolicy.from_config({"fallback": {"blocked_reasons": ["no_such_reason"]}})
    assert policy.blocked_reasons == ("no_such_reason",)

    classified = classify_api_error(Exception("429 rate limit"))
    assert policy.block_reason(classified, emitted_chunks=0, cancelled=False) is None


def test_block_reason_labels_follow_rule_order():
    overflow = classify_api_error(Exception("maximum context length exceeded"))
    policy = FailoverPolicy(blocked_reasons=("context_overflow",))

    assert policy.block_reason(overflow, emitted_chunks=5, cancelled=True) == "cancelled"
    assert policy.block_reason(overflow, emitted_chunks=5, cancelled=False) == "partial_stream"
    assert (
        policy.block_reason(overflow, emitted_chunks=0, cancelled=False)
        == "blocked_reason:context_overflow"
    )
    assert (
        FailoverPolicy().block_reason(overflow, emitted_chunks=0, cancelled=False)
        == "non_retryable:context_overflow"
    )
