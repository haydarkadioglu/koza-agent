"""Core agent loop — tool-calling orchestration."""
import json
from typing import Callable

from .providers.base import LLMProvider
from .skills import filesystem, shell, web, code_runner, system_info, kanban, cron

SYSTEM_PROMPT = """You are Hermes, a powerful AI assistant with access to tools.
You can read/write files, run shell commands, search the web, execute code, manage tasks (Kanban), and schedule recurring jobs (cron).
Always think step by step. Use tools when needed. Be concise but thorough."""

ALL_TOOLS = (
    filesystem.TOOL_DEFINITIONS
    + shell.TOOL_DEFINITIONS
    + web.TOOL_DEFINITIONS
    + code_runner.TOOL_DEFINITIONS
    + system_info.TOOL_DEFINITIONS
    + kanban.TOOL_DEFINITIONS
    + cron.TOOL_DEFINITIONS
)

ALL_HANDLERS: dict[str, Callable] = {
    **filesystem.HANDLERS,
    **shell.HANDLERS,
    **web.HANDLERS,
    **code_runner.HANDLERS,
    **system_info.HANDLERS,
    **kanban.HANDLERS,
    **cron.HANDLERS,
}


class Agent:
    def __init__(self, provider: LLMProvider, db_path: str, on_token: Callable[[str], None] | None = None):
        self.provider = provider
        self.on_token = on_token
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        kanban.init_db(db_path)
        cron.init_db(db_path)

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
