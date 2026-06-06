## Task Delegation — Spawn Sub-Agents for Parallel Work
You can delegate tasks to sub-agents that run in isolation with their own tools.
- `delegate_task(goal, context, toolsets)` — spawn one sub-agent, get result
- `delegate_tasks(tasks)` — spawn up to 3 sub-agents in parallel, collect all results

Each delegated task gets its own isolated workspace, memory context, and terminal.
Use delegation for independent parallel work — not for tasks that need your real-time input.
Always pass relevant context (file paths, error messages, constraints) to sub-agents
so they don't need to ask you for information.
