"""Intent Router — LLM-driven message classification replacing keyword matching.

Uses a single lightweight LLM call to classify user messages into routing
decisions: background delegation, coding mode activation, tool group selection.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from prompt_loader import PromptLoader

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

_ROUTING_SYSTEM_PROMPT = PromptLoader().load("routing/classifier.md")

_CODE_ACTION_RE = re.compile(
    r"\b("
    r"yap|yapsana|oluştur|olustur|kur|hazırla|hazirla|üret|uret|"
    r"kodla|yaz|tasarla|geliştir|gelistir|build|create|make|write|implement"
    r")\b",
    re.IGNORECASE,
)
_CODE_ARTIFACT_RE = re.compile(
    r"\b("
    r"website|web\s*site|site|landing|portfolio|portfolyo|"
    r"app|uygulama|dashboard|panel|"
    r"react|vue|svelte|next|vite|html|css|javascript|typescript|"
    r"python|script|bot|api|frontend|backend|component|sayfa|index\.(js|html|css)"
    r")\b",
    re.IGNORECASE,
)
_BACKGROUND_HINT_RE = re.compile(
    r"\b("
    r"tam proje|multi[- ]?file|çok dosya|cok dosya|full stack|"
    r"büyük|buyuk|komple|tamamen|production|prod"
    r")\b",
    re.IGNORECASE,
)


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


def _heuristic_decision(message: str, coding_enabled: bool) -> RoutingDecision | None:
    """Fast local guardrails for short build/code commands.

    The LLM router is useful for nuanced text, but short Turkish commands like
    "portfolio sitesi yap" are easy to misclassify as web research. If the user
    combines an action verb with a buildable artifact, treat it as coding.
    """
    text = message.strip()
    if not text:
        return None
    if _CODE_ACTION_RE.search(text) and _CODE_ARTIFACT_RE.search(text):
        groups = ["file", "shell", "code", "agent", "web"]
        sections = ["workspace", "code", "shell"]
        if re.search(r"\b(site|website|web\s*site|landing|portfolio|portfolyo|react|vue|svelte|next|vite|frontend|sayfa)\b", text, re.IGNORECASE):
            sections.append("web")
        return RoutingDecision(
            delegate_to_background=bool(_BACKGROUND_HINT_RE.search(text)),
            activate_coding_mode=coding_enabled,
            tool_groups=groups,
            prompt_sections=sections,
        )
    return None


class IntentRouter:
    """Classifies user messages via a single LLM call returning structured JSON."""

    def __init__(self, provider: "LLMProvider", coding_enabled: bool = False) -> None:
        self._provider = provider
        self._coding_enabled = coding_enabled

    def classify(self, message: str) -> RoutingDecision:
        """Classify user message into a routing decision.

        Makes exactly one LLM call. On any failure, returns a safe fallback
        (empty decision = include all tools, use default sections).
        """
        if not message or not message.strip():
            return RoutingDecision()

        heuristic = _heuristic_decision(message, self._coding_enabled)
        if heuristic:
            return heuristic

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
            activate_coding_mode=(
                bool(data.get("activate_coding_mode", False))
                and self._coding_enabled
            ),
            tool_groups=_validate_groups(data.get("tool_groups", [])),
            prompt_sections=[s for s in data.get("prompt_sections", []) if isinstance(s, str)],
        )
