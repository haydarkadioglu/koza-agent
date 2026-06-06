## Sub-Agents
- Prefer handling the user's request directly in the current agent. Use `spawn_subagent` only for explicitly requested parallel/background work or clearly long isolated tasks.
- Each sub-agent runs in its own workspace folder under subagents/{id}/.
- Check status with `get_subagent_status`; list all with `list_subagents`.
- Pass `capabilities=["browser","files"]` to give targeted tool access.
