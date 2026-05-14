# Sub-agents

Koza can spawn **autonomous sub-agents** — independent agent instances that run in background threads with their own tool-calling loops.

---

## What is a Sub-agent?

A sub-agent is a full Koza Agent instance that:
- Runs in a **background thread** (non-blocking)
- Has access to **all 96 tools** (or a filtered subset)
- Shares both **working memory** and **permanent memory** with the parent
- Can run up to **10 tool-calling iterations** to complete its goal
- Times out after **180 seconds**

---

## How to Use

Just ask Koza:

```
Spawn a sub-agent to search for the top 5 Python web frameworks and summarize them
```

Or use the tool directly:

```
spawn_subagent(
  goal="Search for the top 5 Python web frameworks and summarize them",
  wait=True
)
```

---

## Tools

### `spawn_subagent`
```
goal       (required)  The task or goal for the sub-agent
provider   (optional)  Override LLM provider (e.g. "openai")
model      (optional)  Override model name (e.g. "gpt-4o-mini")
tools      (optional)  Comma-separated tool names to restrict to
wait       (optional)  true = wait for result, false = fire and forget
```

**Returns:** Sub-agent ID + status + result summary

### `get_subagent_status`
```
agent_id   (required)  ID returned by spawn_subagent
```

**Returns:** Status (pending/running/done/error), elapsed time, result

### `list_subagents`
Lists all sub-agents spawned in the current session.

---

## Examples

### Wait for result (default)
```
You: Research the latest news about Rust programming language
Koza: [spawns sub-agent, waits up to 180s]
        [Sub-agent abc12345] done
        The latest Rust news: ...
```

### Fire and forget (parallel work)
```
You: Start a background agent to monitor the weather every hour
Koza: Sub-agent f3a9b2c1 launched (background).
        Use get_subagent_status('f3a9b2c1') to check.
```

### Restrict to specific tools
```
spawn_subagent(
  goal="Search arXiv for recent papers on diffusion models",
  tools="arxiv_search,web_search",
  wait=True
)
```

---

## Memory Sharing

Sub-agents automatically receive context at spawn time:

```python
# Injected into sub-agent system prompt:
wm_ctx  = wm_get_context()              # working memory (last 20 events)
mem_ctx = get_relevant_context(goal)    # top-6 relevant permanent memories
```

This means sub-agents know what the parent has been doing and can access stored facts.

---

## Architecture

```
Parent Agent (main thread)
    │
    ├─ spawn_subagent(goal) ──────────────────────────────────────┐
    │                                                              │
    │  Background Thread                                           │
    │  ┌────────────────────────────────────────────────────────┐ │
    │  │ 1. Load config + provider                              │ │
    │  │ 2. Inject working + permanent memory                   │ │
    │  │ 3. Tool-calling loop (max 10 iterations, 180s timeout) │ │
    │  │ 4. Store result in _subagents[agent_id]                │ │
    │  └────────────────────────────────────────────────────────┘ │
    │                                                              │
    └─ (if wait=True) join thread, return result ◄────────────────┘
```

---

## Limitations

- Sub-agents run **in-process** (same Python interpreter) — not isolated sandboxes
- A sub-agent that calls `spawn_subagent` will create nested threads (use with care)
- Memory writes by sub-agents go to the **shared SQLite DB** — visible to all agents
- Maximum 10 tool iterations per sub-agent
