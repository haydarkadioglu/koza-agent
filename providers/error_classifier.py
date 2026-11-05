from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


class FailoverReason(enum.Enum):
    auth = "auth"                        # Authentication failure
    billing = "billing"                  # Billing/quota exhausted
    rate_limit = "rate_limit"            # Rate limit / throttling
    overloaded = "overloaded"            # Server overloaded / busy
    server_error = "server_error"        # Internal server error
    timeout = "timeout"                  # Connection or read timeout
    context_overflow = "context_overflow" # Context length exceeded
    invalid_request = "invalid_request"  # Malformed request / unknown model
    unknown = "unknown"                  # Unclassifiable error

@dataclass
class ClassifiedError:
    reason: FailoverReason
    status_code: int | None = None
    provider: str | None = None
    model: str | None = None
    message: str = ""
    retryable: bool = True
    retry_after: float | None = None     # Server-requested wait in seconds

def _extract_status_code(error: Exception) -> int | None:
    current = error
    for _ in range(5):
        code = getattr(current, "status_code", None)
        if isinstance(code, int):
            return code
        code = getattr(current, "status", None)
        if isinstance(code, int) and 100 <= code < 600:
            return code
        cause = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if cause is None or cause is current:
            break
        current = cause
    return None

def _extract_error_body(error: Exception) -> dict:
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        return body
    response = getattr(error, "response", None)
    if response is not None:
        try:
            json_body = response.json()
            if isinstance(json_body, dict):
                return json_body
        except Exception:  # noqa: BLE001
            return {}
    return {}

def _extract_message(error: Exception, body: dict) -> str:
    if isinstance(body, dict):
        err_obj = body.get("error", {})
        if isinstance(err_obj, dict) and "message" in err_obj:
            return str(err_obj["message"])
        if "message" in body:
            return str(body["message"])
    return str(error)

def _parse_retry_after(value) -> float | None:
    """Parse a Retry-After value (seconds or HTTP-date) into seconds, or None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            seconds = float(text)
        except ValueError:
            try:
                when = parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                return None
            if when is None:
                return None
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            return max(0.0, (when - datetime.now(UTC)).total_seconds())
    else:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _header_value(headers, name: str):
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter(name)
    if value is None:
        value = getter(name.title())
    if value is None and hasattr(headers, "items"):
        for key, candidate in headers.items():
            if isinstance(key, str) and key.lower() == name:
                return candidate
    return value


def _extract_retry_after(error: Exception, body: dict) -> float | None:
    """Return the server-requested retry delay in seconds, or None.

    Reads the Retry-After header from the error (or its response), then the
    retry_after / retryAfter body keys. Fail-open: header objects come from
    arbitrary SDKs, so any lookup failure means "no hint" rather than an error.
    """
    try:
        response = getattr(error, "response", None)
        for headers in (
            getattr(response, "headers", None) if response is not None else None,
            getattr(error, "headers", None),
        ):
            if headers is None:
                continue
            value = _header_value(headers, "retry-after")
            if value is not None:
                parsed = _parse_retry_after(value)
                if parsed is not None:
                    return parsed
        if isinstance(body, dict):
            for key in ("retry_after", "retryAfter"):
                if key in body:
                    return _parse_retry_after(body[key])
    except Exception:  # noqa: BLE001 — a malformed hint must never break classification
        return None
    return None


def classify_api_error(
    error: Exception,
    *,
    provider: str = "",
    model: str = "",
) -> ClassifiedError:
    """Classifies LLM provider/API errors to determine recovery and retry behavior.

    Adopts the Hermes structured classification taxonomy.
    Context overflow is not retryable as-is; recovery must shorten history.
    """
    status_code = _extract_status_code(error)
    error_type = type(error).__name__
    if status_code is None and error_type == "RateLimitError":
        status_code = 429
    body = _extract_error_body(error)
    msg = _extract_message(error, body).lower()
    retry_after = _extract_retry_after(error, body)

    # 1. Billing patterns
    billing_patterns = [
        "insufficient credits",
        "insufficient_quota",
        "insufficient balance",
        "credit balance",
        "credits exhausted",
        "payment required",
        "billing hard limit",
        "exceeded your current quota",
        "account is deactivated",
        "plan does not include",
        "out of funds",
        "balance_depleted",
        "free tier",
    ]
    if status_code == 402 or any(p in msg for p in billing_patterns):
        return ClassifiedError(
            reason=FailoverReason.billing,
            status_code=status_code,
            provider=provider,
            model=model,
            message=msg,
            retryable=False,
        )
        
    # 2. Rate limit patterns
    rate_limit_patterns = [
        "rate limit",
        "rate_limit",
        "too many requests",
        "throttled",
        "requests per minute",
        "tokens per minute",
        "requests per day",
        "try again in",
        "please retry after",
        "resource_exhausted",
        "throttlingexception",
        "too many concurrent requests",
        "servicequotaexceededexception",
        "exhausted",
        "quota",
    ]
    if status_code == 429 or any(p in msg for p in rate_limit_patterns):
        return ClassifiedError(
            reason=FailoverReason.rate_limit,
            status_code=status_code,
            provider=provider,
            model=model,
            message=msg,
            retryable=True,
            retry_after=retry_after,
        )

    # 3. Context overflow patterns
    context_patterns = [
        "context length",
        "context length exceeded",
        "context_length_exceeded",
        "maximum context length",
        "context window",
        "too many tokens",
        "prompt is too long",
        "input is too long",
        "reduce the length",
        "string_above_max_length",
        "length of the prompt",
    ]
    if any(p in msg for p in context_patterns):
        return ClassifiedError(
            reason=FailoverReason.context_overflow,
            status_code=status_code,
            provider=provider,
            model=model,
            message=msg,
            retryable=False,
        )

    # 4. Invalid request patterns. Retrying or failing over cannot fix a
    # malformed request or a bad model id, and every retry burns the
    # key-rotation budget, so these are terminal. Context overflow is matched
    # above so a 400 "maximum context length" still reaches overflow recovery.
    invalid_request_patterns = [
        "model_not_found",
        "model not found",
        "model does not exist",
        "invalid model",
        "invalid_request_error",
        "unknown model",
    ]
    if (
        status_code in (400, 404, 422)
        or any(p in msg for p in invalid_request_patterns)
        # OpenAI words it as "The model `x` does not exist" — require both halves
        # so an auth message like "api key does not exist" keeps its own class.
        or ("does not exist" in msg and "model" in msg)
    ):
        return ClassifiedError(
            reason=FailoverReason.invalid_request,
            status_code=status_code,
            provider=provider,
            model=model,
            message=msg,
            retryable=False,
        )

    # 5. Overloaded patterns
    overloaded_patterns = [
        "overloaded",
        "busy",
        "temporarily unavailable",
        "service_unavailable",
        "503",
        "529",
    ]
    if status_code in (503, 529) or any(p in msg for p in overloaded_patterns):
        return ClassifiedError(
            reason=FailoverReason.overloaded,
            status_code=status_code,
            provider=provider,
            model=model,
            message=msg,
            retryable=True,
            retry_after=retry_after,
        )
    # 6. Server error patterns
    if status_code in (500, 502, 504) or "500" in msg or "502" in msg or "504" in msg:
        return ClassifiedError(
            reason=FailoverReason.server_error,
            status_code=status_code,
            provider=provider,
            model=model,
            message=msg,
            retryable=True,
            retry_after=retry_after,
        )

    # 7. Transport / Timeout patterns
    timeout_patterns = [
        "timeout",
        "time out",
        "connection",
        "connect",
        "network",
    ]
    if any(p in msg for p in timeout_patterns):
        return ClassifiedError(
            reason=FailoverReason.timeout,
            status_code=status_code,
            provider=provider,
            model=model,
            message=msg,
            retryable=True,
            retry_after=retry_after,
        )

    # 8. Authentication patterns
    auth_patterns = [
        "unauthorized",
        "invalid api key",
        "api key is invalid",
        "authentication failed",
        "auth token",
        "401",
        "403",
    ]
    if status_code in (401, 403) or any(p in msg for p in auth_patterns):
        return ClassifiedError(
            reason=FailoverReason.auth,
            status_code=status_code,
            provider=provider,
            model=model,
            message=msg,
            retryable=False,
        )

    # 9. Unknown (retryable by default)
    return ClassifiedError(
        reason=FailoverReason.unknown,
        status_code=status_code,
        provider=provider,
        model=model,
        message=msg,
        retryable=True,
        retry_after=retry_after,
    )


def is_context_overflow(
    error: Exception,
    *,
    provider: str = "",
    model: str = "",
) -> bool:
    """Return whether a provider error indicates that its context limit was exceeded."""
    return classify_api_error(error, provider=provider, model=model).reason == (
        FailoverReason.context_overflow
    )
