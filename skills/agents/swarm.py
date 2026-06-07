"""Parallel Swarm Orchestrator — decomposes goals, runs worker sub-agents, and synthesizes results."""
import json
import time
import re
import logging

from config import load_config
from providers.factory import get_provider
from skills.agents._registry import _subagents, _registry_lock

logger = logging.getLogger(__name__)


def run_swarm(goal: str, capabilities: str = "") -> str:
    """Run a parallel agent swarm to solve a complex task.
    
    1. Decomposes the task using a critic LLM.
    2. Spawns background worker sub-agents in parallel threads.
    3. Polls the registry to monitor their status.
    4. Aggregates results and runs a final synthesis LLM pass.
    """
    from skills.agents import spawn_subagent, subagent_get_result

    cfg = load_config()
    prov = get_provider(cfg)

    # 1. Decompose the high-level goal
    decomposition_system = "You are an expert swarm coordinator. Decompose a complex task into multiple smaller, independent subtasks that can be executed concurrently in parallel."
    decomposition_user = f"""Decompose the following high-level task into a JSON array of subtask dictionaries.
Each subtask dictionary MUST have the exact keys:
- "title": a short descriptive title for the subtask.
- "goal": the detailed, specific instructions/goal for the worker subagent. Make it complete and self-contained (include relevant paths, context, and target requirements).
- "capabilities": a comma-separated string of capability groups required (e.g. "files,code" or "browser" or "code,github").

High-level Task: {goal}

Provide ONLY the valid JSON array starting with `[` and ending with `]` inside a ```json ``` code block. Do not write any other explanations."""

    logger.info("Decomposing goal: %s", goal)
    resp = prov.chat([
        {"role": "system", "content": decomposition_system},
        {"role": "user", "content": decomposition_user}
    ])
    content = resp.get("content", "").strip()

    # Extract JSON block
    match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    json_str = match.group(1) if match else content
    
    try:
        subtasks = json.loads(json_str.strip())
    except Exception as e:
        logger.error("Failed to parse decomposition JSON: %s. Raw output: %s", e, content)
        return f"Failed to decompose goal. JSON parsing failed: {e}\nRaw coordinator response:\n{content}"

    if not isinstance(subtasks, list):
        return f"Invalid decomposition format: expected list, got {type(subtasks)}.\nRaw: {content}"

    # 2. Spawn subagents in background
    agent_ids = []
    launched_details = []
    
    for i, task in enumerate(subtasks):
        t_title = task.get("title", f"Subtask {i+1}")
        t_goal = task.get("goal", "")
        t_caps = task.get("capabilities", capabilities or "files,code")
        
        # Spawn in background without waiting
        res = spawn_subagent(goal=t_goal, capabilities=t_caps, wait=False)
        
        # Extract 8-char subagent ID
        m = re.search(r"Sub-agent\s+([a-f0-9]{8})", res)
        if m:
            aid = m.group(1)
            agent_ids.append((aid, t_title))
            launched_details.append(f"  • Worker #{aid}: '{t_title}' (capabilities: {t_caps})")
        else:
            launched_details.append(f"  • Failed to spawn subagent for '{t_title}': {res}")

    total_workers = len(agent_ids)
    if total_workers == 0:
        return "No sub-agents could be spawned.\nDetails:\n" + "\n".join(launched_details)

    logger.info("Launched %d swarm workers", total_workers)

    # 3. Monitor sub-agents concurrently
    completed = set()
    logger.info("Monitoring swarm workers...")
    
    while len(completed) < total_workers:
        time.sleep(3)
        for aid, title in agent_ids:
            if aid in completed:
                continue
            with _registry_lock:
                ag = _subagents.get(aid)
            if ag:
                status = ag.get("status")
                if status in ("done", "error", "cancelled"):
                    completed.add(aid)
                    logger.info("Worker #%s (%s) finished with status: %s", aid, title, status)

    # 4. Gather results
    results_summary = []
    for aid, title in agent_ids:
        res_text = subagent_get_result(aid)
        with _registry_lock:
            ag = _subagents.get(aid)
            goal_desc = ag.get("goal", "") if ag else ""
        results_summary.append(f"=== Worker #{aid} Result ({title}) ===\nGoal: {goal_desc}\nOutput:\n{res_text}\n")

    results_str = "\n".join(results_summary)

    # 5. Synthesize final response
    synthesis_system = "You are a swarm synthesis specialist. Integrate the results of multiple parallel worker agents into a final, unified report or solution."
    synthesis_user = f"""The parallel worker agents have finished executing their tasks. Synthesize their outputs to address the original high-level task.

Original High-level Task: {goal}

Worker Outputs:
{results_str}

Provide the final synthesized solution or report. Make it comprehensive, coherent, and detailed."""

    logger.info("Synthesizing final outputs...")
    synth_resp = prov.chat([
        {"role": "system", "content": synthesis_system},
        {"role": "user", "content": synthesis_user}
    ])
    
    final_output = synth_resp.get("content", "").strip()
    return final_output
