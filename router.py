"""Intent Router — LLM-driven message classification replacing keyword matching.

Uses a single lightweight LLM call to classify user messages into routing
decisions: background delegation, coding mode activation, tool group selection.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from providers.base import LLMProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Structured output from the LLM router."""
    delegate_to_background: bool = False
    activate_coding_mode: bool = False
    tool_groups: list[str] = field(default_factory=list)
    prompt_sections: list[str] = field(default_factory=list)


# Known tool groups (for validation)
_KNOWN_GROUPS = {
    "file", "shell", "web", "code", "kanban", "cron", "memory", "agent",
    "message", "github", "finance", "media", "system", "research",
    "security", "smarthome", "social", "note", "email", "devops",
    "creative", "mlops", "gaming", "productivity", "background", "mcp",
}

_ROUTING_SYSTEM_PROMPT = """You are a routing classifier. Given a user message, determine:
1. Should this be delegated to a background coding task? (requires actual code writing/file creation)
2. Should this activate coding mode? (user wants to produce code, not just discuss it)
3. Which tool groups are relevant?
4. Which prompt sections should be included?

Rules:
- delegate_to_background: true ONLY for substantial coding tasks (writing apps, scripts, multi-file projects, building features). NOT for questions about code, short explanations, single-command operations, or casual mentions of programming.
- activate_coding_mode: true ONLY when user explicitly wants code produced as output. NOT for conceptual questions, discussions about code, or asking "can you code?".
- tool_groups: list only groups whose tools might actually be called. Empty list = include all tools.
- prompt_sections: list sections whose instructions are relevant. Empty list = use defaults.

Available tool_groups: file, shell, web, code, kanban, cron, memory, agent, message, github, finance, media, system, research, security, smarthome, social, note, email, devops, creative, mlops, gaming, productivity, background

Available prompt_sections: workspace, code, web, shell, memory, agent, security, devops, background

Respond with ONLY a JSON object, no other text:
{"delegate_to_background": false, "activate_coding_mode": false, "tool_groups": [], "prompt_sections": []}"""


def _extract_json(text: str) -> dict:
    """Extract JSON object from LLM response (handles ```json fences)."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    return json.loads(text)


def _validate_groups(groups: list) -> list[str]:
    """Filter to only known tool group names."""
    return [g for g in groups if isinstance(g, str) and g in _KNOWN_GROUPS]


class IntentRouter:
    """Classifies user messages via a single LLM call returning structured JSON."""

    def __init__(self, provider: "LLMProvider") -> None:
        self._provider = provider

    def classify(self, message: str) -> RoutingDecision:
        """Classify user message into a routing decision.

        Makes exactly one LLM call. On any failure, returns a safe fallback
        (empty decision = include all tools, use default sections).
        """
        if not message or not message.strip():
            return RoutingDecision()

        try:
            response = self._provider.chat(
                [
                    {"role": "system", "content": _ROUTING_SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                tools=None,
            )
            raw_content = response.get("content", "")
        except Exception as e:
            logger.warning(f"Router LLM call failed: {e}")
            return RoutingDecision()

        try:
            data = _extract_json(raw_content)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Router JSON parse failed: {e}")
            return RoutingDecision()

        return RoutingDecision(
            delegate_to_background=bool(data.get("delegate_to_background", False)),
            activate_coding_mode=bool(data.get("activate_coding_mode", False)),
            tool_groups=_validate_groups(data.get("tool_groups", [])),
            prompt_sections=[s for s in data.get("prompt_sections", []) if isinstance(s, str)],
        )
