"""Autonomous AI Agents skill — spawn and manage sub-agents."""
import json
import subprocess
import sys
import threading
import time
import uuid
from typing import Callable

# Registry of running/completed sub-agents
_subagents: dict[str, dict] = {}

# ─── Sub-agent engine ────────────────────────────────────────────────────────

def _run_subagent_thread(agent_id: str, goal: str, provider: str, model: str,
                          tools_filter: list[str]) -> None:
    """Run a sub-agent in a background thread using the core Agent."""
    _subagents[agent_id]["status"] = "running"
    try:
        import sys
        sys.path.insert(0, ".")
        from config import load_config
        from providers.factory import get_provider
        from core import Agent, ALL_TOOLS, ALL_HANDLERS, SYSTEM_PROMPT
        from skills.shared_memory import init_db as sm_init, get_relevant_context

        cfg = load_config()
        if provider:
            cfg["provider"] = provider
        if model:
            cfg["model"] = model

        # Init shared memory so sub-agent can read/write it
        sm_init(cfg["db_path"])

        prov = get_provider(cfg)

        # Optionally restrict tools
        if tools_filter:
            tools = [t for t in ALL_TOOLS if t.get("name") in tools_filter]
            handlers = {k: v for k, v in ALL_HANDLERS.items() if k in tools_filter}
        else:
            tools = ALL_TOOLS
            handlers = ALL_HANDLERS

        # Build system prompt with injected shared memory context
        memory_ctx = get_relevant_context(goal, limit=8)
        system_content = SYSTEM_PROMPT
        if memory_ctx:
            system_content = f"{SYSTEM_PROMPT}\n\n{memory_ctx}"

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user",   "content": goal},
        ]

        for _ in range(10):
            response = prov.chat(messages, tools=tools)
            content = response.get("content", "")
            tool_calls = response.get("tool_calls")

            if not tool_calls:
                _subagents[agent_id]["result"] = content or ""
                break

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                handler = handlers.get(tc["name"])
                if handler:
                    try:
                        res = handler(**tc.get("arguments", {}))
                    except Exception as e:
                        res = f"Tool error: {e}"
                else:
                    res = f"Unknown tool: {tc['name']}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", tc["name"]),
                    "name": tc["name"],
                    "content": str(res),
                })
        else:
            _subagents[agent_id]["result"] = "Max iterations reached."

        _subagents[agent_id]["messages"] = messages
        _subagents[agent_id]["status"] = "done"

    except Exception as e:
        _subagents[agent_id]["status"] = "error"
        _subagents[agent_id]["result"] = f"Sub-agent error: {e}"


# ─── Tools ───────────────────────────────────────────────────────────────────

def spawn_subagent(goal: str, provider: str = "", model: str = "",
                   tools: str = "", wait: bool = True) -> str:
    """Spawn a sub-agent with a specific goal. Runs in-process in a thread."""
    agent_id = str(uuid.uuid4())[:8]
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
        ag = _subagents[agent_id]
        status = ag["status"]
        result = ag.get("result", "")
        return f"[Sub-agent {agent_id}] {status}\n{result}"
    else:
        return f"Sub-agent {agent_id} launched (background). Use get_subagent_status('{agent_id}') to check."


def get_subagent_status(agent_id: str) -> str:
    """Check the status and result of a running or completed sub-agent."""
    ag = _subagents.get(agent_id)
    if not ag:
        # List all if not found
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
        f"  Result : {ag.get('result','')[:500]}"
    )


def list_subagents() -> str:
    """List all sub-agents spawned in this session."""
    if not _subagents:
        return "No sub-agents spawned yet."
    lines = []
    for ag in _subagents.values():
        elapsed = round(time.time() - ag["started"], 1)
        lines.append(f"  #{ag['id']} [{ag['status']}] {elapsed}s — {ag['goal']}")
    return "Sub-agents this session:\n" + "\n".join(lines)


# ─── Tool definitions ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "spawn_subagent",
        "description": (
            "Spawn an autonomous sub-agent with its own tool-calling loop to handle a sub-task. "
            "The sub-agent runs in the background and returns its result. "
            "Use for parallel work, research tasks, or delegating complex sub-problems."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The task or goal for the sub-agent"},
                "provider": {"type": "string", "default": "", "description": "LLM provider override"},
                "model": {"type": "string", "default": "", "description": "Model override"},
                "tools": {"type": "string", "default": "", "description": "Comma-separated tool names to restrict to (empty = all tools)"},
                "wait": {"type": "boolean", "default": True, "description": "Wait for completion (true) or launch in background (false)"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "get_subagent_status",
        "description": "Check the status and result of a previously spawned sub-agent by its ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The sub-agent ID returned by spawn_subagent"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "list_subagents",
        "description": "List all sub-agents spawned in this session with their status.",
        "parameters": {"type": "object", "properties": {}},
    },
]

HANDLERS: dict = {
    "spawn_subagent":      lambda goal, provider="", model="", tools="", wait=True: spawn_subagent(goal, provider, model, tools, wait),
    "get_subagent_status": lambda agent_id: get_subagent_status(agent_id),
    "list_subagents":      lambda **_: list_subagents(),
}
