"""Core agent loop — tool-calling orchestration."""
import shutil
import sys
import threading
from typing import Callable

from providers.base import LLMProvider
from prompt import build_system_prompt
from skills import (
    kanban, cron, session_memory, messaging, shared_memory, working_memory,
    email_skill, media, smarthome, social, productivity, notes, github_skill,
)
from tools.registry import ALL_TOOLS, ALL_HANDLERS

# How many recent messages to keep in context (system + last N)
# Older messages are summarized/compacted to save tokens
MAX_CONTEXT_MESSAGES = 50

# Tool messages older than this many exchanges get compacted to a single-line note
# (keeps tool history visible without burning too many tokens)
TOOL_COMPACT_AFTER = 20


def _detect_capabilities() -> dict:
    """Detect what system capabilities are actually available at runtime."""
    caps = {}

    # Headless browser (Playwright)
    try:
        import importlib.util
        caps["playwright"] = importlib.util.find_spec("playwright") is not None
    except Exception:
        caps["playwright"] = False

    # Docker
    caps["docker"] = shutil.which("docker") is not None

    # ffmpeg
    caps["ffmpeg"] = shutil.which("ffmpeg") is not None

    # git
    caps["git"] = shutil.which("git") is not None

    # Display / GUI (Linux/macOS check)
    import os
    caps["has_display"] = (
        sys.platform == "win32"
        or bool(os.environ.get("DISPLAY"))
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )

    # Running inside a container (Docker/LXC)
    caps["in_container"] = os.path.exists("/.dockerenv") or (
        sys.platform != "win32"
        and os.path.exists("/proc/1/cgroup")
        and any("docker" in line or "lxc" in line
                for line in open("/proc/1/cgroup").readlines()
                if line.strip())
    )

    return caps


# Cached at startup — re-detect only on explicit request
_SYSTEM_CAPS: dict = {}

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
                   "credential_set", "credential_get", "credential_list",
                   "wm_add", "wm_get", "wm_clear", "save_session", "recall_sessions", "list_sessions"],
    "agent":      ["spawn_subagent", "get_subagent_status", "list_subagents",
                   "cancel_subagent", "subagent_get_result", "subagent_update",
                   "start_coding_session", "list_capabilities",
                   "create_project", "list_projects", "extract_project"],
    "message":    ["send_message", "get_messages", "telegram_send", "telegram_get_updates",
                   "telegram_send_photo", "telegram_send_video",
                   "discord_send", "discord_get_messages", "whatsapp_send",
                   "twilio_send_sms", "twilio_send_whatsapp", "twilio_make_call",
                   "twilio_call_status", "twilio_list_messages", "twilio_lookup_phone",
                   "twilio_account_info"],
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
    "email":      ["send_email", "read_emails", "search_emails", "reply_email"],
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
    "dosya indirildi": ["file"], "[dosya": ["file"],  # Telegram file download messages
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
    # credentials
    "token": ["memory"], "api key": ["memory"], "apikey": ["memory"], "credential": ["memory"],
    "password": ["memory"], "secret": ["memory"], "key": ["memory"],
    # agents
    "agent": ["agent"], "subagent": ["agent"], "parallel": ["agent"],
    # messaging
    "telegram": ["message"], "discord": ["message"], "whatsapp": ["message"],
    "twilio": ["message"], "sms gönder": ["message"], "arama yap": ["message"],
    "twilio_send": ["message"], "send sms": ["message"], "make call": ["message"],
    "telefon ara": ["message"], "numaraya mesaj": ["message"],
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

# ── Core tools always included ────────────────────────────────────────────────
# Minimal set sent even when keyword matching gives no results.
# These are general-purpose enough that almost any task may need them.
_CORE_TOOL_NAMES: set[str] = {
    "web_search", "fetch_url",
    "memory_recall", "memory_store",
    "run_command", "run_python",
    "read_file", "write_file",
}

def _tool_name(t: dict) -> str:
    """Get tool name regardless of nested or flat format."""
    if "function" in t:
        return t["function"]["name"]
    return t.get("name", "")

_TOOL_BY_NAME: dict[str, dict] = {_tool_name(t): t for t in ALL_TOOLS}


def _expand_tools_for_call(current_tools: list[dict], called_names: list[str]) -> list[dict]:
    """
    Dynamically expand the tool list when the model calls a tool that wasn't
    sent in the current set. Adds the full group that contains the requested tool.
    Called once per iteration before feeding results back to the model.
    """
    current_names = {_tool_name(t) for t in current_tools}
    to_add: set[str] = set()
    for name in called_names:
        if name in current_names:
            continue
        # Find the group this tool belongs to and add all tools in that group
        for group, group_tools in _TOOL_GROUPS.items():
            if name in group_tools:
                to_add.update(group_tools)
                break
        # If not in any group, add just the tool itself
        if name not in to_add and name in _TOOL_BY_NAME:
            to_add.add(name)
    if not to_add:
        return current_tools
    new_tools = list(current_tools)
    for n in to_add:
        if n not in current_names and n in _TOOL_BY_NAME:
            new_tools.append(_TOOL_BY_NAME[n])
    return new_tools[:128]

import re as _re
_CRED_PATTERNS = _re.compile(
    r"(?:"
    r"(?P<service1>[\w\s]+?)\s+(?:api\s*)?(?:key|token|secret|password|credential|apikey|api_key|access_token)\s*(?:is|:|=)\s*(?P<val1>\S{8,})"
    r"|(?P<val2>(?:sk-|ghp_|xox[bprao]-|Bearer\s+)\S{6,})"
    r"|(?P<service2>[\w]+)\s+(?:api\s+)?key\s*[:=]\s*(?P<val3>\S{8,})"
    r")",
    _re.IGNORECASE,
)
# Telegram bot token: digits:alphanumeric (e.g. 1234567890:ABCdefGHI...)
_TG_TOKEN_RE = _re.compile(r'\b(\d{8,12}:[A-Za-z0-9_\-]{30,50})\b')


def _select_tools(user_input: str) -> list[dict]:
    """
    Return a targeted subset of tools based on keywords in the user message.
    - If keywords match → return only those tool groups (+ always-on core tools)
    - If no match → return only the minimal _CORE_TOOL_NAMES set
    Never returns ALL_TOOLS upfront; groups are expanded dynamically during the
    agentic loop via _expand_tools_for_call() when the model requests them.
    """
    lower = user_input.lower()
    groups: set[str] = set()
    for keyword, grp_list in _KEYWORD_MAP.items():
        if keyword in lower:
            groups.update(grp_list)

    # Always include core tools
    core = [t for t in ALL_TOOLS if _tool_name(t) in _CORE_TOOL_NAMES]

    if not groups:
        return core  # narrow set — model can get more via _expand_tools_for_call

    tool_names: set[str] = set(_CORE_TOOL_NAMES)
    for g in groups:
        tool_names.update(_TOOL_GROUPS.get(g, []))

    selected = [t for t in ALL_TOOLS if _tool_name(t) in tool_names]
    return selected[:128] if selected else core


class Agent:
    def __init__(self, provider: LLMProvider, db_path: str, cfg: dict = None,
                 on_token: Callable[[str], None] | None = None,
                 channel: str = "cli"):
        self.provider = provider
        self.on_token = on_token
        self.channel: str = channel  # persist for use in _refresh_memory_context
        self.messages: list[dict] = [{"role": "system", "content": build_system_prompt(channel=channel)}]
        # Rolling summary of conversations older than the context window
        self._context_summary: str = ""
        # Permission hook: callable(name, args) -> bool  (None = allow all)
        self.permission_callback: Callable[[str, dict], bool] | None = None
        # Interrupt/cancel support — set to cancel the current stream_chat loop
        self._cancel: threading.Event = threading.Event()
        self._busy: bool = False
        kanban.init_db(db_path)
        cron.init_db(db_path)
        session_memory.init_db(db_path)
        shared_memory.init_db(db_path)
        working_memory.init_db(db_path)
        # Detect and cache system capabilities once per agent init
        global _SYSTEM_CAPS
        if not _SYSTEM_CAPS:
            _SYSTEM_CAPS = _detect_capabilities()
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

    def _drop_dangling_tool_calls(self) -> int:
        """
        Permanently remove any trailing assistant+tool_calls from self.messages
        that don't have matching tool responses. Returns number of messages removed.
        Used for emergency recovery from API 400 errors.
        """
        # Build set of tool_call_ids that have responses
        result_ids: set[str] = set()
        for m in self.messages:
            if m.get("role") == "tool":
                result_ids.add(m.get("tool_call_id", ""))

        removed = 0
        clean: list[dict] = []
        skip_ids: set[str] = set()
        for m in self.messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                missing = [tc for tc in m["tool_calls"]
                           if tc.get("id", tc.get("name", "")) not in result_ids]
                if missing:
                    for tc in m["tool_calls"]:
                        skip_ids.add(tc.get("id", tc.get("name", "")))
                    removed += 1
                    continue
            if m.get("role") == "tool" and m.get("tool_call_id", "") in skip_ids:
                removed += 1
                continue
            clean.append(m)
        self.messages = clean
        return removed

    def _compact_tool_messages(self, messages: list[dict]) -> list[dict]:
        """Replace old tool message pairs with single compact notes.

        Tool call + result pairs older than TOOL_COMPACT_AFTER non-system messages
        are compressed to a single user-role "[tool log]" message to save tokens
        while keeping a readable trace of what was done.
        """
        non_system = [m for m in messages if m.get("role") != "system"]
        system_msgs = [m for m in messages if m.get("role") == "system"]

        if len(non_system) <= TOOL_COMPACT_AFTER:
            return messages

        # Split: older half gets compacted, recent half is kept verbatim
        cut = len(non_system) - TOOL_COMPACT_AFTER
        old_msgs = non_system[:cut]
        recent_msgs = non_system[cut:]

        # Build a compact log from old messages
        log_lines: list[str] = []
        skip_ids: set[str] = set()
        for m in old_msgs:
            role = m.get("role", "")
            if role == "user":
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
                if content:
                    log_lines.append(f"USER: {str(content)[:200]}")
            elif role == "assistant":
                content = m.get("content") or ""
                tool_calls = m.get("tool_calls") or []
                if tool_calls:
                    names = ", ".join(tc.get("name", "?") for tc in tool_calls)
                    for tc in tool_calls:
                        skip_ids.add(tc.get("id", tc.get("name", "")))
                    if content:
                        log_lines.append(f"ASSISTANT: {str(content)[:120]} [called: {names}]")
                    else:
                        log_lines.append(f"ASSISTANT called: {names}")
                elif content:
                    log_lines.append(f"ASSISTANT: {str(content)[:200]}")
            elif role == "tool":
                result = str(m.get("content", ""))[:150]
                name = m.get("name", "tool")
                log_lines.append(f"  ↳ {name}: {result}")

        if log_lines:
            compact_msg = {
                "role": "user",
                "content": "[Earlier conversation summary]\n" + "\n".join(log_lines),
            }
            return system_msgs + [compact_msg] + recent_msgs
        return system_msgs + recent_msgs

    def _maybe_build_rolling_summary(self) -> None:
        """When messages exceed MAX_CONTEXT_MESSAGES, summarize the overflow into
        self._context_summary using a lightweight provider call.

        Summary is stored in memory and injected into the system prompt each turn
        via _refresh_memory_context so context is never truly lost.
        """
        rest = [m for m in self.messages if m.get("role") != "system"]
        overflow_count = len(rest) - MAX_CONTEXT_MESSAGES
        if overflow_count <= 0:
            return

        # Take the overflow portion and summarize it
        overflow = rest[:overflow_count]
        lines = []
        for m in overflow:
            role = m.get("role", "")
            content = m.get("content") or ""
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            if role in ("user", "assistant") and content:
                lines.append(f"{role.upper()}: {str(content)[:300]}")
        if not lines:
            return

        snippet = "\n".join(lines[-40:])  # cap to avoid token explosion
        try:
            resp = self.provider.chat(
                [
                    {"role": "system", "content": "You are a concise summarizer."},
                    {"role": "user",   "content":
                        f"Summarize the key facts, decisions, and outcomes from this conversation excerpt "
                        f"in 3-5 bullet points. Be very concise. Focus on: what was asked, what was done, "
                        f"key values/names/paths mentioned.\n\n{snippet}"},
                ],
                tools=None,
            )
            summary_text = (resp.get("content") or "").strip()
            if summary_text:
                self._context_summary = summary_text
        except Exception:
            # If summarization fails, fall back to raw truncation of the excerpt
            self._context_summary = "\n".join(lines[-10:])

    def _trim_messages(self) -> list[dict]:
        """
        Return a windowed view of messages: system prompt + last MAX_CONTEXT_MESSAGES.
        - Compacts old tool message pairs into single-line notes
        - Normalizes assistant tool_calls and tool result messages to API format
        - Ensures no orphan tool messages
        - Removes dangling assistant+tool_calls
        """
        import json
        system = [m for m in self.messages if m.get("role") == "system"]
        rest = [m for m in self.messages if m.get("role") != "system"]
        window = system + rest[-MAX_CONTEXT_MESSAGES:]

        # ── Pass 0: compact old tool pairs to save tokens ─────────────────────
        window = self._compact_tool_messages(window)

        # ── Pass 1: ensure every tool msg has a valid preceding assistant ─────
        valid_call_ids: set[str] = set()
        for m in window:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    valid_call_ids.add(tc.get("id", tc.get("name", "")))

        window = [m for m in window
                  if not (m.get("role") == "tool"
                          and m.get("tool_call_id", "") not in valid_call_ids)]

        # ── Pass 2: remove dangling assistant+tool_calls pairs ────────────────
        result_ids: set[str] = set()
        for m in window:
            if m.get("role") == "tool":
                result_ids.add(m.get("tool_call_id", ""))

        skip_ids: set[str] = set()
        clean: list[dict] = []
        for m in window:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                missing = [tc for tc in m["tool_calls"]
                           if tc.get("id", tc.get("name", "")) not in result_ids]
                if missing:
                    for tc in m["tool_calls"]:
                        skip_ids.add(tc.get("id", tc.get("name", "")))
                    continue
            if m.get("role") == "tool" and m.get("tool_call_id", "") in skip_ids:
                continue
            clean.append(m)

        # ── Pass 3: normalize to API format ──────────────────────────────────
        normalized = []
        for m in clean:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                api_tool_calls = []
                for tc in m["tool_calls"]:
                    if "function" in tc:
                        api_tool_calls.append({"type": "function", **tc} if "type" not in tc else tc)
                    else:
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
                if "content" not in m:
                    m = {**m, "content": None}
            elif m.get("role") == "tool":
                m = {**m, "content": str(m.get("content", ""))}
            elif m.get("role") == "assistant" and "content" not in m:
                m = {**m, "content": ""}
            normalized.append(m)

        # ── Pass 4: flatten vision (list) content for non-vision providers ───
        if not getattr(self.provider, "supports_vision", False):
            from providers.base import LLMProvider as _LLMProvider
            normalized = _LLMProvider._flatten_messages_for_text(normalized)

        return normalized

    def interrupt(self) -> bool:
        """Cancel the current in-progress stream_chat. Returns True if was busy."""
        if self._busy:
            self._cancel.set()
            return True
        return False

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
            permanent_failure = False
            for tc in tool_calls:
                result = self._execute_tool(tc["name"], tc.get("arguments", {}))
                result_str = str(result)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", tc["name"]),
                    "name": tc["name"],
                    "content": result_str,
                })
                if "PERMANENT FAILURE" in result_str:
                    permanent_failure = True

            # Expand tools for next round if model called something outside current set
            tools = _expand_tools_for_call(tools, [tc["name"] for tc in tool_calls])

            if permanent_failure:
                self.messages.append({"role": "user", "content": "The tool returned a PERMANENT FAILURE. Report the error to the user and stop."})
                response = self.provider.chat(self._trim_messages(), tools=[])
                final = (response.get("content") or "").strip()
                if final:
                    self.messages.append({"role": "assistant", "content": final})
                return final or ""

        return "Max tool iterations reached."

    def stream_chat(self, user_input: str, image_path: str | None = None):
        """
        Stream chat — yields structured events:
          {"type": "thinking"}                         — waiting for LLM
          {"type": "tool_start", "name": ..., "args": ...}
          {"type": "tool_done",  "name": ..., "result": ..., "elapsed": float}
          {"type": "tool_denied", "name": ...}
          {"type": "text", "token": ...}               — streamed response token

        Args:
            user_input: The user's text message.
            image_path: Optional path to an image file. When provided and the
                current provider supports vision, the image is encoded as base64
                and sent alongside the text in a multi-part content message.

        Agentic loop: keeps calling tools until the model produces a pure-text
        response (no more tool calls / DSML bleed-through).
        """
        import time, json as _json

        self._refresh_memory_context(user_input)

        # Build user message — use vision format when image provided and supported
        if image_path and self.provider.supports_vision:
            import base64 as _b64, mimetypes as _mime
            mime_type = _mime.guess_type(image_path)[0] or "image/jpeg"
            try:
                with open(image_path, "rb") as _f:
                    b64_data = _b64.b64encode(_f.read()).decode()
                user_msg: dict = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_input},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime_type};base64,{b64_data}"
                        }},
                    ],
                }
            except Exception:
                user_msg = {"role": "user", "content": user_input}
        else:
            user_msg = {"role": "user", "content": user_input}

        self.messages.append(user_msg)
        tools = _select_tools(user_input)

        self._cancel.clear()
        self._busy = True

        try:
            MAX_ROUNDS = 10  # safety cap
            for _round in range(MAX_ROUNDS):
                if self._cancel.is_set():
                    yield {"type": "interrupted"}
                    return

                if self.provider.supports_thinking:
                    yield {"type": "thinking"}

                # ── Collect the streaming response ──────────────────────────────
                full = ""
                _tool_buf: dict[int, dict] = {}

                _stream_retried = False
                while True:
                    try:
                        for item in self.provider.stream_chat(self._trim_messages(), tools=tools):
                            if self._cancel.is_set():
                                yield {"type": "interrupted"}
                                return
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
                        break  # stream finished successfully
                    except Exception as _e:
                        # Auto-recover from "tool_calls must be followed by tool messages" (400)
                        _emsg = str(_e)
                        if not _stream_retried and ("tool_calls" in _emsg or "400" in _emsg):
                            _stream_retried = True
                            n = self._drop_dangling_tool_calls()
                            import logging as _logging
                            _logging.getLogger(__name__).warning(
                                f"stream_chat: 400 tool_calls error — dropped {n} dangling messages, retrying"
                            )
                            full = ""
                            _tool_buf = {}
                            continue
                        raise

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
                permanent_failure = False
                for call in calls:
                    if self._cancel.is_set():
                        yield {"type": "interrupted"}
                        return
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
                    result_str = str(result)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": name,
                        "content": result_str,
                    })
                    if "PERMANENT FAILURE" in result_str:
                        permanent_failure = True

                if permanent_failure:
                    # Tell the model once, then stop — do not retry
                    self.messages.append({"role": "user", "content": "The tool returned a PERMANENT FAILURE. Report the error to the user and stop."})
                    response = self.provider.chat(self._trim_messages(), tools=[])
                    final = (response.get("content") or "").strip()
                    if final:
                        for tok in final:
                            yield {"type": "text", "token": tok}
                        self.messages.append({"role": "assistant", "content": final})
                    return

                # Expand tools for next round if model called something outside current set
                tools = _expand_tools_for_call(tools, [c["name"] for c in calls])
                # loop → ask model again with tool results

        finally:
            self._busy = False
            self._cancel.clear()

    def _refresh_memory_context(self, user_input: str) -> None:
        """
        System prompt update every turn:
        - Working memory  → compact recent activity
        - Permanent memory → top relevant entries (query-filtered)
        - Rolling summary  → if conversation history was truncated
        Credentials are NOT injected here — agent calls credential_get() on demand.
        """
        self._maybe_build_rolling_summary()
        self._auto_save_credentials(user_input)

        try:
            from skills.shell import get_cwd as _get_cwd
            from pathlib import Path as _Path
            import os as _os
            wm_ctx = working_memory.wm_get_context()
            new_system = build_system_prompt(user_input, wm_ctx or "", channel=self.channel)
            home_dir = str(_Path.home())
            cwd = _get_cwd()
            new_system += (
                f"\n\n**User home directory:** `{home_dir}`"
                f"\n**Current working directory:** `{cwd}`"
                f"\n**Workspace:** `{_os.path.join(home_dir, '.Koza', 'workspace')}`"
                f"\nWhen the user says 'home dizini' or 'home folder' they mean `{home_dir}` — NOT the workspace or project root."
            )
            # ── Inject detected system capabilities ───────────────────────────
            if _SYSTEM_CAPS:
                available = []
                unavailable = []
                if _SYSTEM_CAPS.get("playwright"):
                    available.append("Playwright/headless browser (js_render=True works)")
                else:
                    unavailable.append("Playwright/headless browser (js_render=True will fail — skip it)")
                if _SYSTEM_CAPS.get("docker"):
                    available.append("Docker")
                else:
                    unavailable.append("Docker (not installed)")
                if _SYSTEM_CAPS.get("ffmpeg"):
                    available.append("ffmpeg (video/audio processing)")
                else:
                    unavailable.append("ffmpeg (not installed — avoid audio/video conversion)")
                if _SYSTEM_CAPS.get("git"):
                    available.append("git")
                else:
                    unavailable.append("git (not installed)")
                if _SYSTEM_CAPS.get("in_container"):
                    available.append("Container environment (limited filesystem access)")
                cap_lines = ""
                if available:
                    cap_lines += "\n**Available:** " + ", ".join(available)
                if unavailable:
                    cap_lines += "\n**NOT available on this system:** " + ", ".join(unavailable)
                if cap_lines:
                    new_system += f"\n\n## System Capabilities{cap_lines}"
            # ── Inject rolling summary of older conversations ─────────────────
            if self._context_summary:
                new_system += (
                    f"\n\n## Earlier Conversation Summary\n"
                    f"(This happened before the current context window)\n"
                    f"{self._context_summary}"
                )
            # ── Auto-inject relevant permanent memories ───────────────────────
            try:
                pm_ctx = shared_memory.get_relevant_context(user_input, limit=8)
                if pm_ctx:
                    new_system += f"\n\n{pm_ctx}"
            except Exception:
                pass
            if self.messages and self.messages[0]["role"] == "system":
                self.messages[0]["content"] = new_system
            working_memory.wm_add(summary=user_input[:120], event_type="user")
        except Exception:
            pass

    def _auto_save_credentials(self, user_input: str) -> None:
        """Detect and auto-save any credentials/tokens mentioned in user message."""
        try:
            # ── Telegram bot token (digits:alphanumeric) ─────────────────────
            for m in _TG_TOKEN_RE.finditer(user_input):
                tg_token = m.group(1)
                shared_memory.credential_set("telegram_bot", tg_token)
                try:
                    from config import load_config, save_config
                    _cfg = load_config()
                    _cfg.setdefault("messaging", {}).setdefault("telegram", {})["token"] = tg_token
                    # Also save at the flat key used by the daemon
                    _cfg["telegram_token"] = tg_token
                    save_config(_cfg)
                except Exception:
                    pass

            # ── Generic credential patterns ───────────────────────────────────
            for m in _CRED_PATTERNS.finditer(user_input):
                service = (m.group("service1") or m.group("service2") or "").strip()
                value   = (m.group("val1") or m.group("val2") or m.group("val3") or "").strip()
                if not value or len(value) < 8:
                    continue
                if not service:
                    # Infer service from value prefix
                    v = value.lower()
                    if v.startswith("sk-"):
                        service = "openai"
                    elif v.startswith("ghp_") or v.startswith("github_pat"):
                        service = "github"
                    elif v.startswith("xox"):
                        service = "slack"
                    elif ":" in value and value.split(":")[0].isdigit():
                        service = "telegram_bot"
                    else:
                        service = "unknown"
                shared_memory.credential_set(service.lower().strip(), value)
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
        self.messages = [{"role": "system", "content": build_system_prompt(channel=self.channel)}]
        self._context_summary = ""
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
