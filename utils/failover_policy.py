"""Decide whether a failed primary provider call may switch to the fallback.

A blind failover (K-30) appends the fallback's complete answer to whatever
the primary already streamed, so the caller sees duplicated text and the
tool-call buffer receives two providers' argument chunks concatenated into
corrupt JSON. It also masks errors that the caller knows how to recover from
(e.g. context overflow) behind a second provider's attempt. This policy
blocks failover in those cases so the original error reaches core instead.
"""

from dataclasses import dataclass

CANCELLED = "cancelled"
PARTIAL_STREAM = "partial_stream"
BLOCKED_REASON = "blocked_reason"
NON_RETRYABLE = "non_retryable"

# A dead key or exhausted quota is exactly what a second provider is for, so
# these non-retryable reasons still fail over.
ACCOUNT_SCOPED_REASONS = frozenset({"auth", "billing"})


@dataclass(frozen=True)
class FailoverPolicy:
    blocked_reasons: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, cfg: dict | None) -> "FailoverPolicy":
        if not isinstance(cfg, dict):
            return cls()
        if "fallback" in cfg:
            cfg = cfg["fallback"]
        if not isinstance(cfg, dict):
            return cls()

        defaults = cls()
        blocked = cfg.get("blocked_reasons")
        if isinstance(blocked, (list, tuple)) and all(
            isinstance(name, str) for name in blocked
        ):
            blocked_reasons = tuple(blocked)
        else:
            blocked_reasons = defaults.blocked_reasons
        return cls(blocked_reasons=blocked_reasons)

    def block_reason(self, classified, emitted_chunks: int, cancelled: bool) -> str | None:
        """None = failover allowed; otherwise a short machine label explaining the block."""
        if cancelled:
            return CANCELLED
        if emitted_chunks > 0:
            return PARTIAL_STREAM
        reason = classified.reason.value
        if reason in self.blocked_reasons:
            return f"{BLOCKED_REASON}:{reason}"
        if classified.retryable is False and reason not in ACCOUNT_SCOPED_REASONS:
            return f"{NON_RETRYABLE}:{reason}"
        return None
