from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from providers.error_classifier import FailoverReason, classify_api_error
from utils.failover_policy import FailoverPolicy
from utils.retry_utils import RetryPolicy, next_delay


class _FakeResponse:
    def __init__(self, headers=None, body=None):
        self.headers = headers or {}
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class _FakeError(Exception):
    def __init__(self, message="", status_code=None, headers=None, body=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        self.response = _FakeResponse(headers, body)
        self.body = body


@pytest.mark.parametrize("status", [400, 404, 422])
def test_client_errors_are_invalid_request(status):
    err = classify_api_error(_FakeError("bad request", status_code=status))
    assert err.reason == FailoverReason.invalid_request
    assert err.retryable is False
    assert err.retry_after is None


def test_context_overflow_400_stays_context_overflow():
    err = classify_api_error(
        _FakeError(
            "maximum context length is 8192 tokens",
            status_code=400,
            body={"error": {"message": "maximum context length is 8192 tokens"}},
        )
    )
    assert err.reason == FailoverReason.context_overflow


def test_invalid_request_marker_without_status():
    err = classify_api_error(_FakeError("Error: invalid_request_error: bad field"))
    assert err.reason == FailoverReason.invalid_request
    assert err.retryable is False


def test_model_not_found_message():
    err = classify_api_error(_FakeError("The model `gpt-9` does not exist"))
    assert err.reason == FailoverReason.invalid_request


def test_retry_after_seconds_header():
    err = classify_api_error(
        _FakeError("slow down", status_code=429, headers={"Retry-After": "7"})
    )
    assert err.reason == FailoverReason.rate_limit
    assert err.retry_after == 7.0


def test_retry_after_lowercase_header_on_error():
    exc = _FakeError("slow down", status_code=429)
    exc.response = None
    exc.headers = {"retry-after": 3}
    assert classify_api_error(exc).retry_after == 3.0


def test_retry_after_http_date():
    when = datetime.now(UTC) + timedelta(seconds=30)
    err = classify_api_error(
        _FakeError(
            "slow down",
            status_code=429,
            headers={"Retry-After": format_datetime(when, usegmt=True)},
        )
    )
    assert err.reason == FailoverReason.rate_limit
    assert 25 <= err.retry_after <= 31


def test_retry_after_past_http_date_is_zero():
    err = classify_api_error(
        _FakeError(
            "slow down",
            status_code=429,
            headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
        )
    )
    assert err.retry_after == 0.0


@pytest.mark.parametrize("value", ["soon", "-5", "nan", "inf", ""])
def test_retry_after_garbage_is_none(value):
    err = classify_api_error(
        _FakeError("slow down", status_code=429, headers={"Retry-After": value})
    )
    assert err.reason == FailoverReason.rate_limit
    assert err.retry_after is None


def test_retry_after_from_body():
    err = classify_api_error(
        _FakeError("overloaded", status_code=503, body={"retry_after": 2.5})
    )
    assert err.reason == FailoverReason.overloaded
    assert err.retry_after == 2.5


def test_broken_headers_object_fails_open():
    class _BadHeaders:
        def get(self, name):
            raise RuntimeError("boom")

    err = classify_api_error(
        _FakeError("slow down", status_code=429, headers=_BadHeaders())
    )
    assert err.reason == FailoverReason.rate_limit
    assert err.retry_after is None


@pytest.mark.parametrize(
    "cfg",
    [
        None,
        {},
        "garbage",
        {"retry": "garbage"},
        {
            "retry": {
                "base_delay": "x",
                "max_delay": -1,
                "jitter_ratio": float("nan"),
                "respect_retry_after": "yes",
            }
        },
        {"retry": {"base_delay": True, "max_delay": float("inf")}},
        {"retry": {"base_delay": 10.0, "max_delay": 5.0}},
    ],
)
def test_retry_policy_defaults(cfg):
    assert RetryPolicy.from_config(cfg) == RetryPolicy()


def test_retry_policy_overrides():
    expected = RetryPolicy(
        base_delay=1.0, max_delay=20.0, jitter_ratio=0.0, respect_retry_after=False
    )
    section = {
        "base_delay": 1,
        "max_delay": 20,
        "jitter_ratio": 0,
        "respect_retry_after": False,
    }
    assert RetryPolicy.from_config({"retry": section}) == expected
    assert RetryPolicy.from_config(section) == expected


def test_next_delay_uses_retry_after_exactly():
    assert next_delay(RetryPolicy(), 1, 5.0) == 5.0


def test_next_delay_caps_retry_after():
    policy = RetryPolicy(max_delay=60.0)
    assert next_delay(policy, 1, 3600.0) == 60.0


def test_next_delay_jitter_when_retry_after_ignored():
    policy = RetryPolicy(base_delay=3.0, max_delay=60.0, jitter_ratio=0.5,
                         respect_retry_after=False)
    for _ in range(20):
        d = next_delay(policy, 1, 5.0)
        assert 3.0 <= d <= 3.0 * 1.5


def test_next_delay_jitter_without_retry_after():
    policy = RetryPolicy()
    for _ in range(20):
        d = next_delay(policy, 1, None)
        assert policy.base_delay <= d <= policy.base_delay * (1 + policy.jitter_ratio)
        big = next_delay(policy, 50, None)
        assert big <= policy.max_delay * 1.5


def test_next_delay_clamps_attempt():
    policy = RetryPolicy()
    for attempt in (0, -3, "bad"):
        d = next_delay(policy, attempt)
        assert policy.base_delay <= d <= policy.base_delay * 1.5


def test_failover_blocked_for_invalid_request():
    classified = classify_api_error(_FakeError("model not found", status_code=404))
    assert FailoverPolicy().block_reason(classified, 0, False) == "non_retryable:invalid_request"


def test_failover_allowed_for_rate_limit():
    classified = classify_api_error(
        _FakeError("slow down", status_code=429, headers={"Retry-After": "1"})
    )
    assert FailoverPolicy().block_reason(classified, 0, False) is None
