"""Sub-agent thread runner — heavy execution logic lives here."""
import sys
import threading
import time

from ._registry import _subagents


def _run_subagent_thread(agent_id: str, goal: str, provider: str, model: str,
                         tools_filter: list[str],
                         system_prompt_override: str = "") -> None:
    """Run a sub-agent in a background thread using the core Agent."""
    _subagents[agent_id]["status"] = "running"
    try:
        sys.path.insert(0, ".")
        from config import load_config
        from providers.factory import get_provider
        from core import ALL_TOOLS, ALL_HANDLERS
        from prompt import build_system_prompt
        from skills.shared_memory import init_db as sm_init, get_relevant_context
        from skills.working_memory import init_db as wm_init, wm_get_context
        from skills import shell as _shell
        from pathlib import Path

        cfg = load_config()
        if provider:
            cfg["provider"] = provider
        if model:
            cfg["model"] = model

        # Each subagent gets its own isolated working directory
        ws = Path(cfg.get("workspace_path", str(Path.home() / ".Koza" / "workspace")))
        agent_dir = ws / "subagents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        _shell.set_cwd(str(agent_dir))
        _subagents[agent_id]["workdir"] = str(agent_dir)

        sm_init(cfg["db_path"])
        wm_init(cfg["db_path"])
        prov = get_provider(cfg)

        if tools_filter:
            tools    = [t for t in ALL_TOOLS    if t.get("name") in tools_filter
                        or (t.get("function", {}).get("name") in tools_filter)]
            handlers = {k: v for k, v in ALL_HANDLERS.items() if k in tools_filter}
        else:
            tools    = ALL_TOOLS
            handlers = dict(ALL_HANDLERS)  # copy — we'll wrap some entries below

        # Sandbox: restrict write ops to the agent's working directory
        from skills.agents._sandbox import apply_sandbox
        handlers = apply_sandbox(handlers, str(agent_dir), str(agent_dir))

        wm_ctx  = wm_get_context()
        mem_ctx = get_relevant_context(goal, limit=6)

        if system_prompt_override:
            system_content = system_prompt_override
        else:
            system_content = build_system_prompt(user_input=goal, channel="subagent")
        if wm_ctx:
            system_content += f"\n\n{wm_ctx}"
        if mem_ctx:
            system_content += f"\n\n{mem_ctx}"

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user",   "content": goal},
        ]

        for _ in range(10):
            response   = prov.chat(messages, tools=tools)
            content    = response.get("content", "")
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
        _subagents[agent_id]["status"]   = "done"

    except Exception as e:
        _subagents[agent_id]["status"] = "error"
        _subagents[agent_id]["result"] = f"Sub-agent error: {e}"
