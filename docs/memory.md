# Memory System

Koza uses a **dual-memory architecture**: short-term working memory and long-term permanent memory. Together they give the agent contextual awareness across tool calls, conversations, and sessions.

---

## Overview

```
┌─────────────────────────────────────────────────────┐
│                   SYSTEM PROMPT                     │
│  ┌─────────────────────────────────────────────┐   │
│  │  Working Memory  (always injected)          │   │
│  │  Ring buffer • last 20 events • auto-logged │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  Permanent Memory  (SQLite — retrieved on demand)   │
│  Shared across all sessions and sub-agents          │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  Session Memory  (SQLite — full conversation saves) │
│  Searchable across past sessions via recall_sessions│
└─────────────────────────────────────────────────────┘
```

---

## 1. Working Memory (Short-term)

**File:** `skills/working_memory.py`  
**Table:** `working_memory` in `~/.koza/koza.db`

- Ring buffer: keeps the **last 20 events**
- **Always injected** into the system prompt on every turn
- Automatically logs every user message and tool call
- Cleared when you do `/reset` or `agent.reset()`

### What gets logged automatically
- Every user message (`event_type = "user"`)
- Every tool call + result preview (`event_type = "tool"`)
- Tool errors (`event_type = "error"`)

### Tools
```
wm_add(summary, detail, event_type)   # add an event manually
wm_get(limit)                          # retrieve recent events
wm_list(limit)                         # retrieve recent events (legacy alias)
wm_clear()                             # wipe working memory
```

### Example prompt injection
```
=== Working Memory (last 20 events) ===
[user]  14:03  "search for python async tutorials"
[tool]  14:03  web_search(query=python async tutorials) → 5 results found...
[tool]  14:03  fetch_url(url=https://realpython.com/...) → Real Python async guide...
[user]  14:05  "summarize it"
```

---

## 2. Permanent Memory (Long-term)

**File:** `skills/shared_memory.py`  
**Table:** `shared_memory` in `~/.koza/koza.db`

- Persists indefinitely across sessions and reboots
- **Not** automatically injected — retrieved only when relevant
- Shared between the main agent and all sub-agents
- Sub-agents receive relevant memories at spawn time via semantic keyword matching

### Tools
```
memory_store(key, value, tags)     # store a permanent fact
memory_recall(query)               # recall by keyword/key
memory_search(query, limit)        # fuzzy search across all memories
memory_list(limit)                 # list recent memories
memory_delete(key)                 # delete a specific memory by key
```

### Example usage (chat)
```
You: Remember that my preferred coding style is PEP8 with 4-space indents
Koza: [calls memory_store] ✅ Stored: "coding_style" = "PEP8, 4-space indents"

You: What's my coding style preference?
Koza: [calls memory_recall] Your coding style is PEP8 with 4-space indents.
```

### Sub-agent memory injection
When a sub-agent is spawned with a goal, it automatically receives:
1. Current working memory context
2. Top-6 relevant permanent memories for the goal (keyword matched)

---

## 3. Session Memory

**File:** `skills/session_memory.py`  
**Table:** `sessions` in `~/.koza/koza.db`

- Auto-saved on every `/reset` and `Ctrl+R` in TUI
- Manually saved with `Ctrl+S` in TUI
- Full message history stored as JSON

### Tools
```
save_session(title, messages, summary)   # save current conversation
recall_sessions(query, limit)            # search past sessions
list_sessions(limit)                     # list saved sessions
delete_session(session_id)               # delete a session
```

### TUI shortcuts
| Shortcut | Action |
|---|---|
| `Ctrl+S` | Save current session |
| `Ctrl+H` | Search session history |
| `Ctrl+R` | Reset chat (auto-saves first) |

---

## Memory Flow Diagram

```
User input
    │
    ▼
_refresh_memory_context()
    │
    ├─ wm_get_context() → inject into system[0]
    ├─ wm_add(user_input)
    │
    ▼
LLM call
    │
    ▼
Tool call
    │
    ├─ handler(args) → result
    ├─ wm_add(tool_name, result_preview)
    │
    ▼
Next turn (working memory updated)
```
