"""Core agent loop — tool-calling orchestration."""
import json
from typing import Callable

from providers.base import LLMProvider
from skills import (
    filesystem, shell, web, code_runner, system_info, kanban, cron,
    agents, creative, datascience, devops, email_skill, finance,
    gaming, github_skill, mcp_skill, media, mlops, notes,
    productivity, research, security, smarthome, social,
    session_memory, messaging,
)

SYSTEM_PROMPT = """You are Hermes, a powerful AI assistant with access to tools.
You can read/write files, run shell commands, search the web, execute code,
manage Kanban tasks, schedule cron jobs, search GitHub, query research papers,
check crypto/stock prices, control smart home devices, post to social media,
manage notes, run data science workflows, and much more.
Always think step by step. Use tools when needed. Be concise but thorough."""

ALL_TOOLS = (
    filesystem.TOOL_DEFINITIONS
    + shell.TOOL_DEFINITIONS
    + web.TOOL_DEFINITIONS
    + code_runner.TOOL_DEFINITIONS
    + system_info.TOOL_DEFINITIONS
    + kanban.TOOL_DEFINITIONS
    + cron.TOOL_DEFINITIONS
    + agents.TOOL_DEFINITIONS
    + creative.TOOL_DEFINITIONS
    + datascience.TOOL_DEFINITIONS
    + devops.TOOL_DEFINITIONS
    + email_skill.TOOL_DEFINITIONS
    + finance.TOOL_DEFINITIONS
    + gaming.TOOL_DEFINITIONS
    + github_skill.TOOL_DEFINITIONS
    + mcp_skill.TOOL_DEFINITIONS
    + media.TOOL_DEFINITIONS
    + mlops.TOOL_DEFINITIONS
    + notes.TOOL_DEFINITIONS
    + productivity.TOOL_DEFINITIONS
    + research.TOOL_DEFINITIONS
    + security.TOOL_DEFINITIONS
    + smarthome.TOOL_DEFINITIONS
    + social.TOOL_DEFINITIONS
    + session_memory.TOOL_DEFINITIONS
    + messaging.TOOL_DEFINITIONS
)

ALL_HANDLERS: dict[str, Callable] = {
    **filesystem.HANDLERS,
    **shell.HANDLERS,
    **web.HANDLERS,
    **code_runner.HANDLERS,
    **system_info.HANDLERS,
    **kanban.HANDLERS,
    **cron.HANDLERS,
    **agents.HANDLERS,
    **creative.HANDLERS,
    **datascience.HANDLERS,
    **devops.HANDLERS,
    **email_skill.HANDLERS,
    **finance.HANDLERS,
    **gaming.HANDLERS,
    **github_skill.HANDLERS,
    **mcp_skill.HANDLERS,
    **media.HANDLERS,
    **mlops.HANDLERS,
    **notes.HANDLERS,
    **productivity.HANDLERS,
    **research.HANDLERS,
    **security.HANDLERS,
    **smarthome.HANDLERS,
    **social.HANDLERS,
    **session_memory.HANDLERS,
    **messaging.HANDLERS,
}


class Agent:
    def __init__(self, provider: LLMProvider, db_path: str, cfg: dict = None,
                 on_token: Callable[[str], None] | None = None):
        self.provider = provider
        self.on_token = on_token
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        kanban.init_db(db_path)
        cron.init_db(db_path)
        session_memory.init_db(db_path)
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

    def _execute_tool(self, name: str, args: dict) -> str:
        handler = ALL_HANDLERS.get(name)
        if not handler:
            return f"Unknown tool: {name}"
        try:
            return handler(**args)
        except Exception as e:
            return f"Tool error ({name}): {e}"

    def reset(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

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
