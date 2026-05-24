"""Fallback provider — wraps a primary and secondary LLMProvider.

If the primary raises any exception, the fallback is tried automatically.
"""
import logging

from .base import LLMProvider

logger = logging.getLogger(__name__)


class FallbackProvider(LLMProvider):
    """Try primary; on failure log a warning and use fallback."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary = primary
        self.fallback = fallback

    # ── LLMProvider interface ─────────────────────────────────────────────────

    def chat(self, messages: list[dict], tools: list[dict] = None) -> dict:
        try:
            return self.primary.chat(messages, tools=tools)
        except Exception as e:
            logger.warning("Primary provider failed (%s), switching to fallback.", e)
            return self.fallback.chat(messages, tools=tools)

    def stream_chat(self, messages: list[dict], tools: list[dict] = None, cancel_event=None):
        try:
            yield from self.primary.stream_chat(messages, tools=tools, cancel_event=cancel_event)
        except Exception as e:
            logger.warning("Primary provider failed during stream (%s), switching to fallback.", e)
            yield from self.fallback.stream_chat(messages, tools=tools, cancel_event=cancel_event)
