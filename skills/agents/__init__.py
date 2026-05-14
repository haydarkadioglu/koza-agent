"""
Agents package — spawn and manage autonomous sub-agents.
Exports TOOL_DEFINITIONS and HANDLERS for core.py.
"""
import threading
import time
import uuid

from ._registry import _subagents
from .runner import _run_subagent_thread


def spawn_subagent(goal: str, provider: str = "", model: str = "",
                   tools: str = "", wait: bool = True) -> str:
    """Spawn a sub-agent with a specific goal. Runs in-process in a thread."""
    agent_id     = str(uuid.uuid4())[:8]
    tools_filter = [t.strip() for t in tools.split(",") if t.strip()] if tools else []

    _subagents[agent_id] = {
        "id": agent_id, "goal": goal[:80], "status": "pending",
        "result": "", "messages": [], "started": time.time(),
    }

    t = threading.Thread(
        target=_run_subagent_thread,
        args=(agent_id, goal, provider, model, tools_filter),
        daemon=True,
    )
    t.start()

    if wait:
        t.join(timeout=180)
        ag     = _subagents[agent_id]
        status = ag["status"]
        result = ag.get("result", "")
        return f"[Sub-agent {agent_id}] {status}\n{result}"
    return f"Sub-agent {agent_id} launched (background). Use get_subagent_status('{agent_id}') to check."


def get_subagent_status(agent_id: str) -> str:
    """Check the status and result of a running or completed sub-agent."""
    ag = _subagents.get(agent_id)
    if not ag:
        if not _subagents:
            return "No sub-agents have been spawned in this session."
        lines = [f"#{a['id']}: {a['status']} — {a['goal']}" for a in _subagents.values()]
        return "Active sub-agents:\n" + "\n".join(lines)
    elapsed = round(time.time() - ag["started"], 1)
    return (
        f"Sub-agent {agent_id}\n"
        f"  Status : {ag['status']}\n"
        f"  Goal   : {ag['goal']}\n"
        f"  Elapsed: {elapsed}s\n"
        f"  Result : {ag.get('result', '')[:500]}"
    )


def list_subagents() -> str:
    """List all sub-agents spawned this session."""
    if not _subagents:
        return "No sub-agents spawned yet."
    lines = []
    for ag in _subagents.values():
        elapsed = round(time.time() - ag["started"], 1)
        lines.append(f"  #{ag['id']} [{ag['status']}] {elapsed}s — {ag['goal']}")
    return "Sub-agents this session:\n" + "\n".join(lines)


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "spawn_subagent",
        "description": (
            "Spawn an autonomous sub-agent with its own tool-calling loop to handle a sub-task. "
            "Runs in the background and returns its result. "
            "Use for parallel work, research tasks, or delegating complex sub-problems."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal":     {"type": "string",  "description": "The task or goal for the sub-agent"},
                "provider": {"type": "string",  "default": "", "description": "LLM provider override"},
                "model":    {"type": "string",  "default": "", "description": "Model override"},
                "tools":    {"type": "string",  "default": "", "description": "Comma-separated tool names (empty = all)"},
                "wait":     {"type": "boolean", "default": True, "description": "Wait for completion or launch in background"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "get_subagent_status",
        "description": "Check the status and result of a previously spawned sub-agent by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "ID returned by spawn_subagent"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "list_subagents",
        "description": "List all sub-agents spawned this session with their status.",
        "parameters": {"type": "object", "properties": {}},
    },
]

HANDLERS: dict = {
    "spawn_subagent":      lambda goal, provider="", model="", tools="", wait=True:
                               spawn_subagent(goal, provider, model, tools, wait),
    "get_subagent_status": lambda agent_id: get_subagent_status(agent_id),
    "list_subagents":      lambda **_: list_subagents(),
}
