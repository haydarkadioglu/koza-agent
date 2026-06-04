"""
Task Delegation — spawn multiple sub-agents in parallel, collect results.

Two modes:
1. delegate_task(goal, context, toolsets) — single task
2. delegate_tasks(tasks) — batch (up to 3 concurrent)

Each sub-agent gets:
- Isolated workspace under workspace/subagents/<id>/
- Shared memory + working memory context auto-injected
- Tools filtered by toolsets/capabilities
- Per-task timeout with automatic status check

Inspired by Hermes Agent's delegate_task tool.
"""
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# Max concurrent sub-agents
_MAX_CONCURRENT = 3
_DEFAULT_TIMEOUT = 300  # 5 minutes per task


def _resolve_toolsets(toolsets: list[str] | None) -> str:
    """Convert toolset names (like 'terminal', 'file', 'web') to capability string.
    
    Falls back to all tools if no toolsets specified.
    """
    if not toolsets:
        return ""
    
    # Map common toolset names to Koza capability groups
    _TOOLSET_MAP = {
        "terminal": "code",
        "file": "files",
        "web": "browser,research",
        "browser": "browser",
        "code": "code",
        "research": "research",
        "github": "github",
        "memory": "memory",
        "kanban": "kanban",
        "cron": "cron",
        "security": "security",
        "creative": "creative",
        "social": "social",
        "finance": "finance",
        "devops": "devops",
        "note": "notes",
        "data": "data",
        "system": "system",
    }
    
    caps = set()
    for ts in toolsets:
        mapped = _TOOLSET_MAP.get(ts.lower(), ts.lower())
        for c in mapped.split(","):
            caps.add(c.strip())
    return ",".join(sorted(caps))


def delegate_task(goal: str, context: str = "", toolsets: list[str] | None = None,
                  timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Spawn a single sub-agent with context and return its result summary.
    
    Args:
        goal: What the sub-agent should accomplish.
        context: Background information, file paths, constraints.
        toolsets: List of toolset names (e.g. ['terminal', 'file']).
        timeout: Max seconds to wait (default 300).
    
    Returns:
        Status + result summary string.
    """
    from skills.agents import spawn_subagent
    
    full_goal = goal
    if context:
        full_goal = f"{goal}\n\n## Context\n{context}"
    
    result = spawn_subagent(
        full_goal,
        capabilities=_resolve_toolsets(toolsets),
        wait=True,
    )
    return result


def delegate_tasks(tasks: list[dict], max_concurrent: int = _MAX_CONCURRENT) -> list[dict]:
    """Spawn multiple sub-agents in parallel and collect all results.
    
    Args:
        tasks: List of dicts with keys:
            - goal (str, required): What this task should accomplish.
            - context (str, optional): Background info for this task.
            - toolsets (list[str], optional): Toolset names.
            - timeout (int, optional): Per-task timeout in seconds.
        max_concurrent: Max parallel agents (default 3).
    
    Returns:
        List of dicts: [{index, goal, status, summary}]
    """
    if not tasks:
        return [{"index": 0, "goal": "", "status": "error", "summary": "No tasks provided."}]
    
    max_workers = min(max_concurrent, _MAX_CONCURRENT, len(tasks))
    results: list[dict] = []
    results_lock = threading.Lock()
    
    def _run_single(index: int, task: dict) -> None:
        goal = task.get("goal", "")
        context = task.get("context", "")
        toolsets = task.get("toolsets", None)
        timeout = task.get("timeout", _DEFAULT_TIMEOUT)
        
        try:
            summary = delegate_task(goal, context, toolsets, timeout)
        except Exception as e:
            summary = f"ERROR: {e}"
        
        with results_lock:
            results.append({
                "index": index,
                "goal": goal[:80],
                "status": "done" if not summary.startswith("ERROR") else "error",
                "summary": summary[:500],
            })
    
    threads = []
    for i, task in enumerate(tasks):
        t = threading.Thread(target=_run_single, args=(i, task), daemon=True)
        threads.append(t)
        t.start()
        
        # Throttle to max_concurrent
        if len(threads) >= max_workers:
            for th in threads:
                th.join(timeout=1)
            threads = [th for th in threads if th.is_alive()]
    
    # Wait for remaining
    for th in threads:
        th.join(timeout=30)
    
    # Sort by index
    results.sort(key=lambda r: r["index"])
    return results


# ─── Tool Definitions ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "delegate_task",
        "description": (
            "Spawn a sub-agent to work on a single task in an isolated context. "
            "The sub-agent gets its own terminal session and tool set. "
            "Returns the result when complete. Use for tasks that benefit from "
            "focused, independent execution."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "What the sub-agent should accomplish. Be specific and self-contained.",
                },
                "context": {
                    "type": "string",
                    "description": "Background information: file paths, error messages, project structure, constraints.",
                    "default": "",
                },
                "toolsets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool sets to enable (e.g. ['terminal', 'file', 'web']). Default: all tools.",
                    "default": [],
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait (default 300).",
                    "default": 300,
                },
            },
            "required": ["goal"],
        },
    },
    {
        "name": "delegate_tasks",
        "description": (
            "Spawn multiple sub-agents in parallel to work on independent tasks. "
            "Each gets its own isolated context and terminal. "
            "All results are returned together. Max 3 concurrent agents."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "List of tasks to run in parallel. Each task must have a 'goal' field.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "What this sub-agent should do."},
                            "context": {"type": "string", "description": "Optional background context.", "default": ""},
                            "toolsets": {"type": "array", "items": {"type": "string"}, "description": "Optional toolset names.", "default": []},
                            "timeout": {"type": "integer", "description": "Optional per-task timeout.", "default": 300},
                        },
                        "required": ["goal"],
                    },
                },
            },
            "required": ["tasks"],
        },
    },
]

HANDLERS: dict = {
    "delegate_task":  lambda goal, context="", toolsets=None, timeout=300: delegate_task(goal, context, toolsets, int(timeout)),
    "delegate_tasks": lambda tasks: format_batch_results(delegate_tasks(tasks)),
}


def format_batch_results(results: list[dict]) -> str:
    """Format batch delegation results into a readable string."""
    if not results:
        return "No results."
    
    total = len(results)
    done = sum(1 for r in results if r["status"] == "done")
    failed = total - done
    
    lines = [
        f"📋 Batch Delegation Results ({done}/{total} completed{f', {failed} failed' if failed else ''}):\n"
    ]
    for r in results:
        status_icon = "✅" if r["status"] == "done" else "❌"
        lines.append(f"  {status_icon} Task #{r['index'] + 1}: {r['goal']}")
        if r["summary"]:
            # Show first 200 chars, handle multi-line
            summary = r["summary"].replace("\n", " ")[:200]
            lines.append(f"     {summary}")
        lines.append("")
    
    return "\n".join(lines)
