"""Coding Mode persona system prompts.

Each persona is a specialized Agent with a focused system prompt.
They share a CodingContext but have separate message histories.
"""

from prompt_loader import PromptLoader

_loader = PromptLoader()

TEAM_LEAD_PROMPT = _loader.load("personas/team_lead.md")
BACKEND_DEV_PROMPT = _loader.load("personas/backend_dev.md")
FRONTEND_DEV_PROMPT = _loader.load("personas/frontend_dev.md")
TEST_ENGINEER_PROMPT = _loader.load("personas/test_engineer.md")
