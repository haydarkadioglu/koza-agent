"""Retry utilities — jittered backoff for decorrelated retries.

Replaces fixed exponential backoff with jittered delays to prevent
thundering-herd retry spikes when multiple sessions hit the same
rate-limited provider concurrently.
"""

import math
import random
import threading
import time
from dataclasses import dataclass

# Monotonic counter for jitter seed uniqueness within the same process.
# Protected by a lock to avoid race conditions in concurrent retry paths
# (e.g. multiple gateway sessions retrying simultaneously).
_jitter_counter = 0
_jitter_lock = threading.Lock()


def jittered_backoff(
    attempt: int,
    *,
    base_delay: float = 5.0,
    max_delay: float = 120.0,
    jitter_ratio: float = 0.5,
) -> float:
    """Compute a jittered exponential backoff delay.

    Args:
        attempt: 1-based retry attempt number.
        base_delay: Base delay in seconds for attempt 1.
        max_delay: Maximum delay cap in seconds.
        jitter_ratio: Fraction of computed delay to use as random jitter
            range.  0.5 means jitter is uniform in [0, 0.5 * delay].

    Returns:
        Delay in seconds: min(base * 2^(attempt-1), max_delay) + jitter.

    The jitter decorrelates concurrent retries so multiple sessions
    hitting the same provider don't all retry at the same instant.
    """
    global _jitter_counter
    with _jitter_lock:
        _jitter_counter += 1
        tick = _jitter_counter

    exponent = max(0, attempt - 1)
    if exponent >= 63 or base_delay <= 0:
        delay = max_delay
    else:
        delay = min(base_delay * (2 ** exponent), max_delay)

    # Seed from time + counter for decorrelation even with coarse clocks.
    seed = (time.time_ns() ^ (tick * 0x9E3779B9)) & 0xFFFFFFFF
    rng = random.Random(seed)
    jitter = rng.uniform(0, jitter_ratio * delay)

    return delay + jitter


def _is_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


@dataclass(frozen=True)
class RetryPolicy:
    base_delay: float = 3.0
    max_delay: float = 60.0
    jitter_ratio: float = 0.5
    respect_retry_after: bool = True

    @classmethod
    def from_config(cls, cfg: dict | None) -> "RetryPolicy":
        if not isinstance(cfg, dict):
            return cls()
        if "retry" in cfg:
            cfg = cfg["retry"]
        if not isinstance(cfg, dict):
            return cls()

        defaults = cls()
        values = {}
        for name in ("base_delay", "max_delay", "jitter_ratio"):
            value = cfg.get(name)
            values[name] = (
                float(value)
                if _is_number(value) and value >= 0
                else getattr(defaults, name)
            )
        if values["max_delay"] < values["base_delay"]:
            values["base_delay"] = defaults.base_delay
            values["max_delay"] = defaults.max_delay
        respect = cfg.get("respect_retry_after")
        values["respect_retry_after"] = (
            respect if isinstance(respect, bool) else defaults.respect_retry_after
        )
        return cls(**values)


def next_delay(
    policy: RetryPolicy,
    attempt: int,
    retry_after: float | None = None,
) -> float:
    """Return the wait in seconds before 1-based retry ``attempt``.

    A server-provided Retry-After is honoured exactly (no jitter — the server
    already told us when to come back) but capped at ``policy.max_delay`` so a
    hostile or buggy header cannot stall the turn. Without one, fall back to
    the jittered exponential backoff.
    """
    try:
        attempt = max(1, int(attempt))
    except (TypeError, ValueError, OverflowError):
        attempt = 1
    if policy.respect_retry_after and _is_number(retry_after) and retry_after >= 0:
        return min(float(retry_after), policy.max_delay)
    return jittered_backoff(
        attempt,
        base_delay=policy.base_delay,
        max_delay=policy.max_delay,
        jitter_ratio=policy.jitter_ratio,
    )
