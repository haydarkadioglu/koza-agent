"""Tool registry — ALL_TOOLS and ALL_HANDLERS assembled from all skill modules."""
from typing import Callable

# Runtime plugin tools accumulator — populated by plugin_loader
_PLUGIN_TOOLS: list[dict] = []
_PLUGIN_HANDLERS: dict[str, Callable] = {}


def register_plugin_tools(tools: list[dict], handlers: dict[str, Callable]) -> None:
    """Register tools and handlers from an external plugin.
    
    Called at runtime by plugin_loader.load_plugin(). After registration,
    ALL_TOOLS and ALL_HANDLERS are rebuilt to include the new entries.
    """
    global ALL_TOOLS, ALL_HANDLERS
    _PLUGIN_TOOLS.extend(_normalize(tools))
    _PLUGIN_HANDLERS.update(handlers)
    # Rebuild with plugin tools included
    ALL_TOOLS = _build_all_tools()
    ALL_HANDLERS = _build_all_handlers()


def _build_all_tools() -> list[dict]:
    return _normalize(
        _STATIC_TOOLS + _PLUGIN_TOOLS
    )


def _build_all_handlers() -> dict[str, Callable]:
    h = dict(_STATIC_HANDLERS)
    h.update(_PLUGIN_HANDLERS)
    return h

from skills import (
    filesystem, shell, web, code_runner, system_info, kanban, cron,
    agents, browser_control, creative, datascience, devops, email_skill, finance,
    gaming, github_skill, mcp_skill, media, mlops, notes,
    productivity, research, security, smarthome, social,
    session_memory, messaging, shared_memory, working_memory,
    config_manager, image_gen, sync, skill_ecosystem, vision, plugin_loader, delegation, repo_manager, code_tools,
)


def _normalize(tools: list[dict]) -> list[dict]:
    """Ensure every tool is in OpenAI's nested format: {"type":"function","function":{...}}"""
    result = []
    for t in tools:
        if "function" in t:
            # Already nested — ensure 'type' field is present
            result.append({"type": "function", **t} if "type" not in t else t)
        elif "name" in t:
            # Flat format — wrap it
            result.append({"type": "function", "function": t})
        # Skip anything else (malformed)
    return result

_STATIC_TOOLS: list[dict] = _normalize(
    filesystem.TOOL_DEFINITIONS
    + shell.TOOL_DEFINITIONS
    + web.TOOL_DEFINITIONS
    + browser_control.TOOL_DEFINITIONS
    + code_runner.TOOL_DEFINITIONS
    + system_info.TOOL_DEFINITIONS
    + kanban.TOOL_DEFINITIONS
    + cron.TOOL_DEFINITIONS
    + agents.TOOL_DEFINITIONS
    + creative.TOOL_DEFINITIONS
    + datascience.TOOL_DEFINITIONS
    + devops.TOOL_DEFINITIONS
    + email_skill.TOOL_DEFINITIONS
    + finance.TOOL_DEFINITIONS
    + gaming.TOOL_DEFINITIONS
    + github_skill.TOOL_DEFINITIONS
    + mcp_skill.TOOL_DEFINITIONS
    + media.TOOL_DEFINITIONS
    + mlops.TOOL_DEFINITIONS
    + notes.TOOL_DEFINITIONS
    + productivity.TOOL_DEFINITIONS
    + research.TOOL_DEFINITIONS
    + security.TOOL_DEFINITIONS
    + smarthome.TOOL_DEFINITIONS
    + social.TOOL_DEFINITIONS
    + session_memory.TOOL_DEFINITIONS
    + messaging.TOOL_DEFINITIONS
    + shared_memory.TOOL_DEFINITIONS
    + working_memory.TOOL_DEFINITIONS
    + config_manager.TOOL_DEFINITIONS
    + image_gen.TOOL_DEFINITIONS
    + sync.TOOL_DEFINITIONS
    + skill_ecosystem.TOOL_DEFINITIONS
    + vision.TOOL_DEFINITIONS
    + plugin_loader.TOOL_DEFINITIONS
    + delegation.TOOL_DEFINITIONS
    + repo_manager.TOOL_DEFINITIONS
    + code_tools.TOOL_DEFINITIONS
)

_STATIC_HANDLERS: dict[str, Callable] = {
    **filesystem.HANDLERS,
    **shell.HANDLERS,
    **web.HANDLERS,
    **browser_control.HANDLERS,
    **code_runner.HANDLERS,
    **system_info.HANDLERS,
    **kanban.HANDLERS,
    **cron.HANDLERS,
    **agents.HANDLERS,
    **creative.HANDLERS,
    **datascience.HANDLERS,
    **devops.HANDLERS,
    **email_skill.HANDLERS,
    **finance.HANDLERS,
    **gaming.HANDLERS,
    **github_skill.HANDLERS,
    **mcp_skill.HANDLERS,
    **media.HANDLERS,
    **mlops.HANDLERS,
    **notes.HANDLERS,
    **productivity.HANDLERS,
    **research.HANDLERS,
    **security.HANDLERS,
    **smarthome.HANDLERS,
    **social.HANDLERS,
    **session_memory.HANDLERS,
    **messaging.HANDLERS,
    **shared_memory.HANDLERS,
    **working_memory.HANDLERS,
    **config_manager.HANDLERS,
    **image_gen.HANDLERS,
    **sync.HANDLERS,
    **skill_ecosystem.HANDLERS,
    **vision.HANDLERS,
    **plugin_loader.HANDLERS,
    **delegation.HANDLERS,
    **repo_manager.HANDLERS,
    **code_tools.HANDLERS,
}

ALL_TOOLS = _build_all_tools()
ALL_HANDLERS = _build_all_handlers()
