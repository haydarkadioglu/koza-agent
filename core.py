"""Core agent loop — tool-calling orchestration."""
from typing import Callable

from providers.base import LLMProvider
from prompt import SYSTEM_PROMPT
from skills import (
    kanban, cron, session_memory, messaging, shared_memory, working_memory,
    email_skill, media, smarthome, social, productivity, notes, github_skill,
)
from tools.registry import ALL_TOOLS, ALL_HANDLERS

# How many recent messages to keep in context (system + last N)
# Older messages are summarized/dropped to save tokens
MAX_CONTEXT_MESSAGES = 20

# ── Tool selection helpers ────────────────────────────────────────────────────
# Keywords that hint at which tool categories are needed.
# If the user message matches none, we send ALL_TOOLS (safe fallback).

_TOOL_GROUPS: dict[str, list[str]] = {
    "file":       ["read_file", "write_file", "list_dir", "create_dir", "delete_file"],
    "shell":      ["run_command"],
    "web":        ["web_search", "fetch_url"],
    "code":       ["run_python", "run_node", "run_script", "run_jupyter_cell", "pandas_query", "matplotlib_plot"],
    "kanban":     ["create_task", "list_tasks", "move_task", "update_task", "delete_task"],
    "cron":       ["create_cron", "list_crons", "delete_cron"],
    "memory":     ["memory_store", "memory_recall", "memory_search", "memory_list", "memory_delete",
                   "wm_add", "wm_get", "wm_clear", "save_session", "recall_sessions", "list_sessions"],
    "agent":      ["spawn_subagent", "get_subagent_status", "list_subagents"],
    "message":    ["send_message", "get_messages", "telegram_send", "telegram_get_updates",
                   "discord_send", "discord_get_messages", "whatsapp_send"],
    "github":     ["github_search_code", "github_create_issue", "github_list_prs",
                   "github_repo_info", "github_clone_repo"],
    "finance":    ["crypto_price", "stock_price", "crypto_top"],
    "media":      ["spotify_search", "youtube_search", "gif_search", "youtube_download"],
    "system":     ["get_os_info", "get_env_var", "list_processes"],
    "research":   ["arxiv_search", "wikipedia_search", "polymarket_search"],
    "security":   ["port_scan", "http_headers_check", "ssl_check", "whois_lookup"],
    "smarthome":  ["hue_list_lights", "hue_set_light", "mqtt_publish", "home_assistant_call"],
    "social":     ["twitter_search", "reddit_search", "mastodon_post",
                   "bluesky_search", "bluesky_post", "hackernews_top", "hackernews_search",
                   "linkedin_post", "threads_post", "instagram_post", "instagram_get_profile"],
    "note":       ["note_create", "note_search", "note_read", "note_list"],
    "email":      ["send_email", "read_emails"],
    "devops":     ["git_operation", "docker_run", "webhook_listen"],
    "creative":   ["ascii_art", "architecture_diagram", "generate_image"],
    "mlops":      ["run_eval", "model_benchmark", "huggingface_model_info"],
    "gaming":     ["minecraft_command", "pokemon_lookup"],
    "mcp":        ["mcp_list_tools", "mcp_call_tool"],
    "productivity": ["google_calendar_list", "google_calendar_create", "google_sheets_read", "airtable_query"],
}

_KEYWORD_MAP: dict[str, list[str]] = {
    # file
    "file": ["file"], "folder": ["file"], "directory": ["file"], "read": ["file"],
    "write": ["file"], "delete": ["file"], "list": ["file", "kanban"],
    # shell
    "run": ["shell", "code"], "command": ["shell"], "terminal": ["shell"], "powershell": ["shell"],
    # web
    "search": ["web", "research"], "google": ["web"], "url": ["web"], "website": ["web"],
    "browser": ["web"], "fetch": ["web"],
    # code
    "python": ["code"], "script": ["code"], "code": ["code"], "execute": ["code", "shell"],
    "jupyter": ["code"], "pandas": ["code"], "plot": ["code"],
    # kanban / tasks
    "task": ["kanban"], "kanban": ["kanban"], "todo": ["kanban"], "doing": ["kanban"],
    # cron / schedule
    "schedule": ["cron"], "cron": ["cron"], "every day": ["cron"], "recurring": ["cron"],
    # memory
    "remember": ["memory"], "forget": ["memory"], "recall": ["memory"], "memory": ["memory"],
    "session": ["memory"],
    # agents
    "agent": ["agent"], "subagent": ["agent"], "parallel": ["agent"],
    # messaging
    "telegram": ["message"], "discord": ["message"], "whatsapp": ["message"],
    "send message": ["message"], "message": ["message"],
    # github
    "github": ["github"], "git": ["github", "devops"], "repo": ["github"],
    "pull request": ["github"], "issue": ["github"],
    # finance
    "crypto": ["finance"], "bitcoin": ["finance"], "stock": ["finance"], "price": ["finance"],
    "ethereum": ["finance"],
    # media
    "spotify": ["media"], "youtube": ["media"], "gif": ["media"], "music": ["media"],
    "video": ["media"],
    # system
    "system": ["system"], "process": ["system"], "cpu": ["system"], "memory usage": ["system"],
    # research
    "arxiv": ["research"], "paper": ["research"], "wikipedia": ["research"], "research": ["research"],
    # security
    "port": ["security"], "ssl": ["security"], "whois": ["security"], "scan": ["security"],
    "security": ["security"],
    # smarthome
    "hue": ["smarthome"], "light": ["smarthome"], "mqtt": ["smarthome"],
    "home assistant": ["smarthome"],
    # social
    "twitter": ["social"], "reddit": ["social"], "mastodon": ["social"],
    "bluesky": ["social"], "bsky": ["social"], "hacker news": ["social"],
    "hackernews": ["social"], "hn ": ["social"], "linkedin": ["social"],
    "threads": ["social"], "instagram": ["social"],
    # notes
    "note": ["note"], "obsidian": ["note"], "vault": ["note"], "markdown": ["note"],
    # email
    "email": ["email"], "mail": ["email"], "smtp": ["email"],
    # devops
    "docker": ["devops"], "container": ["devops"], "webhook": ["devops"],
    # creative
    "ascii": ["creative"], "diagram": ["creative"], "image": ["creative"],
    # mlops
    "eval": ["mlops"], "benchmark": ["mlops"], "huggingface": ["mlops"], "model": ["mlops"],
    # gaming
    "minecraft": ["gaming"], "pokemon": ["gaming"],
    # productivity
    "calendar": ["productivity"], "sheets": ["productivity"], "airtable": ["productivity"],
}

def _tool_name(t: dict) -> str:
    """Get tool name regardless of nested or flat format."""
    if "function" in t:
        return t["function"]["name"]
    return t.get("name", "")

_TOOL_BY_NAME: dict[str, dict] = {_tool_name(t): t for t in ALL_TOOLS}


def _select_tools(user_input: str) -> list[dict]:
    """
    Return a targeted subset of tools based on keywords in the user message.
    Falls back to ALL_TOOLS if no keyword matched or if input is very short/generic.
    Saves tokens when the intent is narrow.
    """
    lower = user_input.lower()
    groups: set[str] = set()
    for keyword, grp_list in _KEYWORD_MAP.items():
        if keyword in lower:
            groups.update(grp_list)

    if not groups:
        return ALL_TOOLS  # fallback: send everything

    tool_names: set[str] = set()
    for g in groups:
        tool_names.update(_TOOL_GROUPS.get(g, []))

    selected = [t for t in ALL_TOOLS if _tool_name(t) in tool_names]
    # Always include core memory tools
    for name in ("wm_add", "memory_store"):
        if name in _TOOL_BY_NAME and not any(_tool_name(t) == name for t in selected):
            selected.append(_TOOL_BY_NAME[name])

    return selected if selected else ALL_TOOLS


class Agent:
    def __init__(self, provider: LLMProvider, db_path: str, cfg: dict = None,
                 on_token: Callable[[str], None] | None = None):
        self.provider = provider
        self.on_token = on_token
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Permission hook: callable(name, args) -> bool  (None = allow all)
        self.permission_callback: Callable[[str, dict], bool] | None = None
        kanban.init_db(db_path)
        cron.init_db(db_path)
        session_memory.init_db(db_path)
        shared_memory.init_db(db_path)
        working_memory.init_db(db_path)
        if cfg:
            email_skill.init_email(cfg)
            media.init_media(cfg)
            smarthome.init_smarthome(cfg)
            social.init_social(cfg)
            productivity.init_productivity(cfg)
            notes.init_notes(cfg.get("vault_path", ""))
            gh_token = cfg.get("providers", {}).get("github", {}).get("token", "")
            github_skill.init_github(gh_token)
            messaging.init_messaging(cfg)
            # Set working directory to isolated workspace so agent-created files
            # don't pollute the project source tree or end up on GitHub.
            from pathlib import Path as _Path
            from skills import shell as _shell
            ws = _Path(cfg.get("workspace_path", str(_Path.home() / ".Koza" / "workspace")))
            for sub in ("projects", "subagents", "tmp", "downloads"):
                (ws / sub).mkdir(parents=True, exist_ok=True)
            _shell.set_cwd(str(ws))

    def _trim_messages(self) -> list[dict]:
        """
        Return a windowed view of messages: system prompt + last MAX_CONTEXT_MESSAGES.
        Also normalizes assistant tool_calls and tool result messages to API format.
        """
        import json
        system = [m for m in self.messages if m.get("role") == "system"]
        rest = [m for m in self.messages if m.get("role") != "system"]
        window = system + rest[-MAX_CONTEXT_MESSAGES:]

        normalized = []
        for m in window:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                # Ensure tool_calls use the full API format
                api_tool_calls = []
                for tc in m["tool_calls"]:
                    if "function" in tc:
                        # Already in API format — ensure type is present
                        api_tool_calls.append({"type": "function", **tc} if "type" not in tc else tc)
                    else:
                        # Internal flat format → convert to API format
                        args = tc.get("arguments", {})
                        api_tool_calls.append({
                            "id": tc.get("id", tc.get("name", "")),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                            },
                        })
                m = {**m, "tool_calls": api_tool_calls}
                # content must be string or None, not missing
                if "content" not in m:
                    m = {**m, "content": None}
            elif m.get("role") == "tool":
                # Ensure tool result has content as string
                m = {**m, "content": str(m.get("content", ""))}
            elif m.get("role") == "assistant" and "content" not in m:
                m = {**m, "content": ""}
            normalized.append(m)
        return normalized

    def chat(self, user_input: str) -> str:
        """Send a user message, run tool loop, return final response."""
        self._refresh_memory_context(user_input)
        self.messages.append({"role": "user", "content": user_input})
        tools = _select_tools(user_input)

        for _ in range(10):  # max tool iterations
            response = self.provider.chat(self._trim_messages(), tools=tools)
            content = response.get("content")
            tool_calls = response.get("tool_calls")

            if not tool_calls:
                if content:
                    self.messages.append({"role": "assistant", "content": content})
                return content or ""

            self.messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                result = self._execute_tool(tc["name"], tc.get("arguments", {}))
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", tc["name"]),
                    "name": tc["name"],
                    "content": str(result),
                })

        return "Max tool iterations reached."

    def stream_chat(self, user_input: str):
        """
        Stream chat — yields structured events:
          {"type": "thinking"}                         — waiting for LLM
          {"type": "tool_start", "name": ..., "args": ...}
          {"type": "tool_done",  "name": ..., "result": ..., "elapsed": float}
          {"type": "tool_denied", "name": ...}
          {"type": "text", "token": ...}               — streamed response token

        Agentic loop: keeps calling tools until the model produces a pure-text
        response (no more tool calls / DSML bleed-through).
        """
        import time, json as _json

        self._refresh_memory_context(user_input)
        self.messages.append({"role": "user", "content": user_input})
        tools = _select_tools(user_input)

        MAX_ROUNDS = 10  # safety cap
        for _round in range(MAX_ROUNDS):
            yield {"type": "thinking"}

            # ── Collect the streaming response ──────────────────────────────
            full = ""
            _tool_buf: dict[int, dict] = {}

            for item in self.provider.stream_chat(self._trim_messages(), tools=tools):
                if isinstance(item, dict) and item.get("__tool_chunk__"):
                    idx = item["index"]
                    if idx not in _tool_buf:
                        _tool_buf[idx] = {"id": item.get("id"), "name": item.get("name", ""), "args": ""}
                    if item.get("name"):
                        _tool_buf[idx]["name"] = item["name"]
                    if item.get("id"):
                        _tool_buf[idx]["id"] = item["id"]
                    _tool_buf[idx]["args"] += item.get("args_chunk", "")
                else:
                    token = item if isinstance(item, str) else (item.get("token", "") if isinstance(item, dict) else "")
                    if token:
                        full += token
                        yield {"type": "text", "token": token}

            # ── No tool calls → pure text response, done ─────────────────────
            if not _tool_buf:
                self.messages.append({"role": "assistant", "content": full})
                return

            # ── Build call list from buffered chunks ─────────────────────────
            calls = []
            for idx, stc in sorted(_tool_buf.items()):
                try:
                    args_parsed = _json.loads(stc["args"] or "{}")
                except Exception:
                    args_parsed = {}
                calls.append({
                    "id": stc["id"] or stc["name"],
                    "name": stc["name"],
                    "arguments": args_parsed,
                })

            self.messages.append({
                "role": "assistant",
                "content": full or None,
                "tool_calls": calls,
            })

            # ── Execute each tool call ────────────────────────────────────────
            for call in calls:
                name, args = call["name"], call["arguments"]
                if self.permission_callback and not self.permission_callback(name, args):
                    yield {"type": "tool_denied", "name": name}
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": name,
                        "content": "Permission denied by user.",
                    })
                    continue
                yield {"type": "tool_start", "name": name, "args": args}
                t0 = time.time()
                result = self._execute_tool(name, args)
                yield {"type": "tool_done", "name": name, "result": result, "elapsed": time.time() - t0}
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": name,
                    "content": str(result),
                })
            # loop → ask model again with tool results

    def _refresh_memory_context(self, user_input: str) -> None:
        """
        Dual-memory system prompt update:
        - Working memory  → always injected (compact recent activity, last 20 events)
        - Permanent memory → NOT auto-injected; only when agent calls memory_recall/search
        """
        try:
            from skills.shell import get_cwd as _get_cwd
            wm_ctx = working_memory.wm_get_context()
            new_system = SYSTEM_PROMPT
            if wm_ctx:
                new_system = f"{SYSTEM_PROMPT}\n\n{wm_ctx}"
            new_system += f"\n\n**Current working directory:** `{_get_cwd()}`"
            if self.messages and self.messages[0]["role"] == "system":
                self.messages[0]["content"] = new_system
            # Log user input to working memory
            working_memory.wm_add(
                summary=user_input[:120],
                event_type="user",
            )
        except Exception:
            pass

    def _execute_tool(self, name: str, args: dict) -> str:
        handler = ALL_HANDLERS.get(name)
        if not handler:
            return f"Unknown tool: {name}"
        try:
            result = handler(**args)
            # Auto-log tool call to working memory
            arg_preview = ", ".join(f"{k}={str(v)[:40]}" for k, v in args.items())
            summary = f"{name}({arg_preview})"
            detail = str(result)[:300]
            working_memory.wm_add(summary=summary, detail=detail, event_type="tool")
            return result
        except Exception as e:
            err = f"Tool error ({name}): {e}"
            working_memory.wm_add(summary=f"{name} failed: {e}", event_type="error")
            return err

    def reset(self):
        self.auto_save()  # save session before clearing
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        working_memory.wm_clear()  # wipe short-term memory on reset

    def auto_save(self, title: str = "", summary: str = "") -> str:
        """Auto-save current session messages."""
        if not title:
            # Try to derive title from first user message
            for m in self.messages:
                if m.get("role") == "user":
                    title = m.get("content", "")[:60]
                    break
            title = title or "Untitled Session"
        msgs = [m for m in self.messages if m.get("role") != "system"]
        return session_memory.save_session(title, msgs, summary)
