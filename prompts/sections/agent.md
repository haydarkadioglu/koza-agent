## Sub-Agents

### When to delegate (always use `wait=False`)
Prefer handling the user's request directly in the current agent. Spawn a background sub-agent only when the user explicitly asks for background/parallel work or the task clearly needs isolated long-running execution:
- Research or web scraping that will take multiple tool calls
- File generation or code writing across multiple files
- Long-running builds, tests, or installations
- Any task you estimate will take more than ~30 seconds
- Parallel work that can proceed independently

When delegating, report only the ID and what will happen next. Do not ask for confirmation first.

### Management
- `spawn_subagent(goal, wait=False, capabilities="...")` — launch in background
- `get_subagent_status(agent_id)` — check progress
- `list_subagents()` — all agents this session
- `subagent_get_result(agent_id)` — get full output when done
- `subagent_delete(agent_id)` — remove from registry
- `subagent_update(agent_id, new_goal)` — cancel and re-spawn with new instructions
- `list_capabilities()` — see available capability groups

### Isolation
Each sub-agent runs in its own workspace folder `subagents/{id}/`.
Sub-agents cannot write outside their own directory.
