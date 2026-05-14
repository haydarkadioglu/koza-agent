"""Core agent loop — tool-calling orchestration."""
from typing import Callable

from providers.base import LLMProvider
from skills import (
    kanban, cron, session_memory, messaging, shared_memory, working_memory,
    email_skill, media, smarthome, social, productivity, notes, github_skill,
)
from tools.registry import ALL_TOOLS, ALL_HANDLERS

SYSTEM_PROMPT = """You are Hermes, a powerful AI assistant with access to tools.
You can read/write files, run shell commands, search the web, execute code,
manage Kanban tasks, schedule cron jobs, search GitHub, query research papers,
check crypto/stock prices, control smart home devices, post to social media,
manage notes, run data science workflows, and much more.
Always think step by step. Use tools when needed. Be concise but thorough."""


class Agent:
    def __init__(self, provider: LLMProvider, db_path: str, cfg: dict = None,
                 on_token: Callable[[str], None] | None = None):
        self.provider = provider
        self.on_token = on_token
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
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

    def chat(self, user_input: str) -> str:
        """Send a user message, run tool loop, return final response."""
        self._refresh_memory_context(user_input)
        self.messages.append({"role": "user", "content": user_input})

        for _ in range(10):  # max tool iterations
            response = self.provider.chat(self.messages, tools=ALL_TOOLS)
            content = response.get("content")
            tool_calls = response.get("tool_calls")

            if not tool_calls:
                # Final text response
                if content:
                    self.messages.append({"role": "assistant", "content": content})
                return content or ""

            # Append assistant message with tool calls
            self.messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            # Execute each tool call
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
        """Stream chat — yields text tokens, handles tools internally."""
        self._refresh_memory_context(user_input)
        self.messages.append({"role": "user", "content": user_input})

        # First check if tools are needed (non-streaming probe)
        response = self.provider.chat(self.messages, tools=ALL_TOOLS)
        tool_calls = response.get("tool_calls")

        if tool_calls:
            # Execute tools then stream final answer
            self.messages.append({"role": "assistant", "content": response.get("content"), "tool_calls": tool_calls})
            for tc in tool_calls:
                result = self._execute_tool(tc["name"], tc.get("arguments", {}))
                yield f"\n🔧 **{tc['name']}**\n```\n{result}\n```\n"
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", tc["name"]),
                    "name": tc["name"],
                    "content": str(result),
                })
            # Stream final response
            for token in self.provider.stream_chat(self.messages):
                yield token
        else:
            # Pure streaming
            full = ""
            for token in self.provider.stream_chat(self.messages):
                full += token
                yield token
            self.messages.append({"role": "assistant", "content": full})

    def _refresh_memory_context(self, user_input: str) -> None:
        """
        Dual-memory system prompt update:
        - Working memory  → always injected (compact recent activity, last 20 events)
        - Permanent memory → NOT auto-injected; only when agent calls memory_recall/search
        """
        try:
            wm_ctx = working_memory.wm_get_context()
            new_system = SYSTEM_PROMPT
            if wm_ctx:
                new_system = f"{SYSTEM_PROMPT}\n\n{wm_ctx}"
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
