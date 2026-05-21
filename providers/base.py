"""Base LLM provider interface."""
from abc import ABC, abstractmethod
from typing import Any, Generator


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict:
        """Send messages and return assistant response dict.
        
        Returns:
            {
                "content": str | None,
                "tool_calls": [ {"id": str, "name": str, "arguments": dict} ] | None
            }
        """

    @abstractmethod
    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Generator[str, None, None]:
        """Stream response tokens as a generator of strings."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return available model names."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'openai')."""

    @property
    def supports_thinking(self) -> bool:
        """True for models with native reasoning/thinking tokens (e.g. o1, Claude extended thinking, DeepSeek-R1)."""
        return False
