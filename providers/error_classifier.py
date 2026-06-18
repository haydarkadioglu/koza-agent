from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

class FailoverReason(enum.Enum):
    auth = "auth"                        # Authentication failure
    billing = "billing"                  # Billing/quota exhausted
    rate_limit = "rate_limit"            # Rate limit / throttling
    overloaded = "overloaded"            # Server overloaded / busy
    server_error = "server_error"        # Internal server error
    timeout = "timeout"                  # Connection or read timeout
    context_overflow = "context_overflow" # Context length exceeded
    unknown = "unknown"                  # Unclassifiable error

@dataclass
class ClassifiedError:
    reason: FailoverReason
    status_code: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    message: str = ""
    retryable: bool = True

def _extract_status_code(error: Exception) -> Optional[int]:
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
        except Exception:
            pass
    return {}

def _extract_message(error: Exception, body: dict) -> str:
    if isinstance(body, dict):
        err_obj = body.get("error", {})
        if isinstance(err_obj, dict) and "message" in err_obj:
            return str(err_obj["message"])
        if "message" in body:
            return str(body["message"])
    return str(error)

def classify_api_error(
    error: Exception,
    *,
    provider: str = "",
    model: str = "",
) -> ClassifiedError:
    """Classifies LLM provider/API errors to determine recovery and retry behavior.

    Adopts the Hermes structured classification taxonomy.
    """
    status_code = _extract_status_code(error)
    error_type = type(error).__name__
    if status_code is None and error_type == "RateLimitError":
        status_code = 429
    body = _extract_error_body(error)
    msg = _extract_message(error, body).lower()
    
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
        )

    # 3. Context overflow patterns
    context_patterns = [
        "context length exceeded",
        "context_length_exceeded",
        "maximum context length",
        "too many tokens",
        "max_tokens",
        "length of the prompt",
        "context window",
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

    # 4. Overloaded patterns
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
        )

    # 5. Server error patterns
    if status_code in (500, 502, 504) or "500" in msg or "502" in msg or "504" in msg:
        return ClassifiedError(
            reason=FailoverReason.server_error,
            status_code=status_code,
            provider=provider,
            model=model,
            message=msg,
            retryable=True,
        )

    # 6. Transport / Timeout patterns
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
        )

    # 7. Authentication patterns
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

    # 8. Unknown (retryable by default)
    return ClassifiedError(
        reason=FailoverReason.unknown,
        status_code=status_code,
        provider=provider,
        model=model,
        message=msg,
        retryable=True,
    )
