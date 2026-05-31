"""Sub-agent thread runner — heavy execution logic lives here."""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ._registry import _subagents, _registry_lock

# Max tool-calling iterations per subagent
_DEFAULT_MAX_ITER = 30


def _run_subagent_thread(agent_id: str, goal: str, provider: str, model: str,
                         tools_filter: list[str],
                         system_prompt_override: str = "",
                         cancel_event: threading.Event | None = None) -> None:
    """Run a sub-agent in a background thread using the core Agent."""
    with _registry_lock:
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

        max_iter = int(
            cfg.get("coding_mode", {}).get("max_retries", 3)
        ) * 8 or _DEFAULT_MAX_ITER

        # Each subagent gets its own isolated working directory
        ws = Path(cfg.get("workspace_path", str(Path.home() / ".Koza" / "workspace")))
        agent_dir = ws / "subagents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        _shell.set_cwd(str(agent_dir))
        with _registry_lock:
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
            handlers = dict(ALL_HANDLERS)

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

        for _ in range(max_iter):
            # Check cancellation before each LLM call
            if cancel_event and cancel_event.is_set():
                with _registry_lock:
                    _subagents[agent_id]["status"] = "cancelled"
                    _subagents[agent_id]["result"]  = "Sub-agent was cancelled."
                return

            response   = prov.chat(messages, tools=tools)
            content    = response.get("content", "")
            tool_calls = response.get("tool_calls")

            if not tool_calls:
                with _registry_lock:
                    _subagents[agent_id]["result"] = content or ""
                break

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            # ── Parallel tool execution ───────────────────────────────────────
            # Independent tool calls run concurrently; results merged in order.
            tool_results: dict[str, str] = {}

            if len(tool_calls) > 1:
                with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as pool:
                    future_map = {}
                    for tc in tool_calls:
                        name    = tc["name"]
                        handler = handlers.get(name)
                        if handler:
                            fut = pool.submit(handler, **tc.get("arguments", {}))
                        else:
                            fut = pool.submit(lambda n=name: f"Unknown tool: {n}")
                        future_map[fut] = tc

                    for fut in as_completed(future_map):
                        tc = future_map[fut]
                        try:
                            tool_results[tc["name"] + tc.get("id", "")] = str(fut.result())
                        except Exception as e:
                            tool_results[tc["name"] + tc.get("id", "")] = f"Tool error: {e}"
            else:
                # Single tool call — no overhead of ThreadPoolExecutor
                tc = tool_calls[0]
                handler = handlers.get(tc["name"])
                try:
                    res = handler(**tc.get("arguments", {})) if handler else f"Unknown tool: {tc['name']}"
                except Exception as e:
                    res = f"Tool error: {e}"
                tool_results[tc["name"] + tc.get("id", "")] = str(res)

            for tc in tool_calls:
                key = tc["name"] + tc.get("id", "")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", tc["name"]),
                    "name": tc["name"],
                    "content": tool_results.get(key, ""),
                })
        else:
            with _registry_lock:
                _subagents[agent_id]["result"] = "Max iterations reached."

        with _registry_lock:
            _subagents[agent_id]["messages"] = messages
            _subagents[agent_id]["status"]   = "done"

    except Exception as e:
        import traceback
        with _registry_lock:
            _subagents[agent_id]["status"] = "error"
            _subagents[agent_id]["result"] = f"Sub-agent error: {type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}"

