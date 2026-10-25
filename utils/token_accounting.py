"""Real token accounting for koza turns (K-15).

Before this module the agent only ever knew a rough character estimate
(``len(str(messages)) // 4``) computed in ``core.py`` right before the
compression preflight.  Providers *do* report exact usage — OpenAI-compatible
APIs send a final ``usage`` chunk when ``stream_options.include_usage`` is set,
Anthropic reports ``input_tokens``/``output_tokens``, Gemini reports
``prompt_token_count`` — but nothing in the loop read it, so

  * the compression threshold fired on a guess that drifts badly for code,
    JSON, non-Latin scripts and images, and
  * ``utils/context_engine.py`` (``update_from_response``) never received the
    usage it was designed around.

``TokenLedger`` is deliberately per-agent (one per conversation) and tiny: it
remembers the exact prompt size of the last request the provider answered and
adds a cheap estimate only for the messages appended *after* that request
(the assistant reply and any tool results).  That keeps the number exact at
the point where it matters — a fresh API response — without a tokenizer
dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

# Canonical usage keys, in the order providers tend to use them.
_PROMPT_KEYS = ("prompt_tokens", "input_tokens", "prompt_token_count")
_COMPLETION_KEYS = ("completion_tokens", "output_tokens", "candidates_token_count")
_TOTAL_KEYS = ("total_tokens", "total_token_count")
_CACHE_READ_KEYS = ("cache_read_tokens", "cached_tokens", "cache_read_input_tokens")
_CACHE_WRITE_KEYS = ("cache_write_tokens", "cache_creation_input_tokens")
_REASONING_KEYS = ("reasoning_tokens", "thoughts_token_count")


def _get(payload: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict-like or attribute-style usage payload."""
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _first_int(payload: Any, keys: Iterable[str]) -> int:
    for key in keys:
        value = _as_int(_get(payload, key))
        if value:
            return value
    return 0


def normalize_usage(raw: Any) -> dict[str, int]:
    """Normalize a provider usage payload into koza's canonical dict.

    Accepts a dict or an object (the OpenAI SDK returns pydantic models),
    in OpenAI (``prompt_tokens``), Anthropic (``input_tokens``) or Gemini
    (``prompt_token_count``) spelling, and also understands the nested
    OpenAI ``prompt_tokens_details.cached_tokens`` bucket.

    Returns ``{}`` when the payload carries no token counts at all, so
    callers can keep their previous estimate instead of recording a zero.
    """
    if raw is None:
        return {}

    prompt = _first_int(raw, _PROMPT_KEYS)
    completion = _first_int(raw, _COMPLETION_KEYS)
    total = _first_int(raw, _TOTAL_KEYS) or (prompt + completion)
    if not (prompt or completion or total):
        return {}

    details = _get(raw, "prompt_tokens_details")
    cache_read = _first_int(raw, _CACHE_READ_KEYS) or _first_int(details, ("cached_tokens",))
    details_out = _get(raw, "completion_tokens_details")
    reasoning = _first_int(raw, _REASONING_KEYS) or _first_int(details_out, ("reasoning_tokens",))

    normalized = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": _first_int(raw, _CACHE_WRITE_KEYS),
        "reasoning_tokens": reasoning,
    }
    return normalized


def usage_event(raw: Any) -> dict[str, dict[str, int]] | None:
    """Wrap a usage payload as the provider stream event koza understands."""
    normalized = normalize_usage(raw)
    if not normalized:
        return None
    return {"__usage__": normalized}


class TokenLedger:
    """Per-conversation record of real provider token usage.

    ``record()`` stores the exact prompt size of the request that produced the
    usage payload together with the message count at that moment; ``prompt_tokens()``
    then returns that exact size plus a rough estimate for anything appended
    afterwards.  Image parts therefore count once at their real cost instead of
    being re-estimated from base64 length on every turn.
    """

    def __init__(self, rough_estimator: Callable[[list[dict[str, Any]]], int] | None = None):
        self._rough = rough_estimator
        self.reset()

    def reset(self) -> None:
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.reasoning_tokens = 0
        self.measured_at: int | None = None
        self.samples = 0
        self.last_model = ""
        # K-27: cumulative totals for the whole conversation.
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.session_total_tokens = 0
        self.session_cache_read_tokens = 0
        self.session_cache_write_tokens = 0
        self.session_requests = 0
        self.session_priced_requests = 0
        self.session_cost = 0.0
        self.last_cost: float | None = None

    def mark_request(self, message_count: int) -> None:
        """Remember how much history was sent (used when no usage arrives)."""
        self._pending_mark = max(0, int(message_count))

    def record(
        self,
        usage: Any,
        message_count: int | None = None,
        model: str = "",
        price: Any = None,
    ) -> bool:
        """Record one provider response. Returns True when real numbers landed.

        ``price`` is an optional ``utils.cost_accounting.ModelPrice``; without
        one the response still counts towards the session totals but its cost
        stays unknown (``last_cost is None``).
        """
        normalized = normalize_usage(usage)
        if not normalized:
            return False
        mark = message_count if message_count is not None else getattr(self, "_pending_mark", None)
        self.last_prompt_tokens = normalized["prompt_tokens"]
        self.last_completion_tokens = normalized["completion_tokens"]
        self.last_total_tokens = normalized["total_tokens"]
        self.cache_read_tokens = normalized["cache_read_tokens"]
        self.cache_write_tokens = normalized["cache_write_tokens"]
        self.reasoning_tokens = normalized["reasoning_tokens"]
        self.measured_at = None if mark is None else max(0, int(mark))
        self.last_model = model or self.last_model
        self.samples += 1
        self._pending_mark = None
        self._accumulate(normalized, price)
        return True

    def _accumulate(self, normalized: dict[str, int], price: Any) -> None:
        self.session_prompt_tokens += normalized["prompt_tokens"]
        self.session_completion_tokens += normalized["completion_tokens"]
        self.session_total_tokens += normalized["total_tokens"]
        self.session_cache_read_tokens += normalized["cache_read_tokens"]
        self.session_cache_write_tokens += normalized["cache_write_tokens"]
        self.session_requests += 1
        self.last_cost = None
        if price is None:
            return
        try:
            from utils.cost_accounting import estimate_cost

            cost = estimate_cost(normalized, price)
        except Exception:  # accounting must never break a turn
            import logging
            logging.getLogger(__name__).debug("cost estimate failed", exc_info=True)
            cost = None
        if cost is not None:
            self.last_cost = cost
            self.session_cost += cost
            self.session_priced_requests += 1

    @property
    def has_real_usage(self) -> bool:
        return self.last_prompt_tokens > 0

    def prompt_tokens(
        self,
        messages: list[dict[str, Any]],
        rough_estimator: Callable[[list[dict[str, Any]]], int] | None = None,
    ) -> int:
        """Best known size of ``messages`` in tokens.

        Exact provider count plus a rough estimate of the messages appended
        after the measured request; falls back to the rough estimate when no
        real usage has been seen yet or the history was rewritten (compression)
        so the mark no longer points at a valid boundary.
        """
        rough = rough_estimator or self._rough
        if rough is None:
            return 0
        if not self.has_real_usage:
            return rough(messages)
        mark = self.measured_at
        if mark is None or mark > len(messages):
            return rough(messages)
        tail = messages[mark:]
        return self.last_prompt_tokens + (rough(tail) if tail else 0)

    def summary(self) -> dict[str, Any]:
        """Small dict for logging / telemetry surfaces."""
        return {
            "prompt_tokens": self.last_prompt_tokens,
            "completion_tokens": self.last_completion_tokens,
            "total_tokens": self.last_total_tokens,
            "samples": self.samples,
            "model": self.last_model,
        }

    def usage_report(self) -> dict[str, Any]:
        """Last-response and cumulative session usage, plus estimated cost.

        ``cost_known`` is False until at least one response had a price, so
        callers can print "cost unknown" instead of a misleading ``0``.
        """
        return {
            "last": {
                "prompt_tokens": self.last_prompt_tokens,
                "completion_tokens": self.last_completion_tokens,
                "total_tokens": self.last_total_tokens,
                "cache_read_tokens": self.cache_read_tokens,
                "cache_write_tokens": self.cache_write_tokens,
                "reasoning_tokens": self.reasoning_tokens,
                "cost": self.last_cost,
            },
            "session": {
                "prompt_tokens": self.session_prompt_tokens,
                "completion_tokens": self.session_completion_tokens,
                "total_tokens": self.session_total_tokens,
                "cache_read_tokens": self.session_cache_read_tokens,
                "cache_write_tokens": self.session_cache_write_tokens,
                "requests": self.session_requests,
                "cost": self.session_cost,
                "priced_requests": self.session_priced_requests,
            },
            "model": self.last_model,
            "cost_known": self.session_priced_requests > 0,
        }
