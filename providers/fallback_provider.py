"""Fallback provider — wraps a primary and secondary LLMProvider.

If the primary raises, the fallback is tried unless the FailoverPolicy blocks
it (partial stream already emitted, user cancel, non-retryable error such as
context overflow). Blocked failures are re-raised so core can recover (K-30).
"""
import logging

from utils.failover_policy import FailoverPolicy

from .base import LLMProvider
from .error_classifier import classify_api_error

logger = logging.getLogger(__name__)


class FallbackProvider(LLMProvider):
    """Try primary; on an allowed failure log a warning and use fallback."""

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
        policy: FailoverPolicy | None = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.policy = policy if policy is not None else FailoverPolicy()

    @property
    def name(self) -> str:
        return getattr(self.primary, "name", "")

    @property
    def model(self) -> str:
        return getattr(self.primary, "model", "") or getattr(self.primary, "_model", "")

    def list_models(self) -> list[str]:
        return self.primary.list_models()

    def rotate_key(self, reason: str = "") -> bool:
        if hasattr(self.primary, "rotate_key"):
            try:
                return self.primary.rotate_key(reason)
            except TypeError:
                return self.primary.rotate_key()
        return False

    def report_key_failure(
        self,
        reason: str,
        status_code: int | None = None,
    ) -> None:
        if hasattr(self.primary, "report_key_failure"):
            self.primary.report_key_failure(reason, status_code)

    def key_health(self) -> list[dict]:
        if hasattr(self.primary, "key_health"):
            return self.primary.key_health()
        return []

    def _block_reason(
        self, exc: Exception, emitted_chunks: int, cancel_event=None
    ) -> tuple[str, str | None]:
        classified = classify_api_error(
            exc,
            provider=getattr(self.primary, "name", ""),
            model=self.model,
        )
        cancelled = cancel_event is not None and cancel_event.is_set()
        return classified.reason.value, self.policy.block_reason(
            classified, emitted_chunks, cancelled
        )

    # ── LLMProvider interface ─────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict:
        try:
            return self.primary.chat(messages, tools=tools, stream=stream)
        except Exception as e:
            reason, label = self._block_reason(e, emitted_chunks=0)
            if label is not None:
                logger.warning("Primary provider failed (%s); not failing over (%s).", e, label)
                raise
            logger.warning(
                "Primary provider failed (%s), switching to fallback (reason=%s).", e, reason
            )
            return self.fallback.chat(messages, tools=tools, stream=stream)

    def stream_chat(self, messages: list[dict], tools: list[dict] | None = None, cancel_event=None):
        emitted_chunks = 0
        try:
            for chunk in self.primary.stream_chat(
                messages, tools=tools, cancel_event=cancel_event
            ):
                emitted_chunks += 1
                yield chunk
        except Exception as e:
            reason, label = self._block_reason(e, emitted_chunks, cancel_event)
            if label is not None:
                logger.warning(
                    "Primary provider failed during stream (%s); not failing over (%s).", e, label
                )
                raise
            logger.warning(
                "Primary provider failed during stream (%s), switching to fallback (reason=%s).",
                e,
                reason,
            )
            yield from self.fallback.stream_chat(messages, tools=tools, cancel_event=cancel_event)
