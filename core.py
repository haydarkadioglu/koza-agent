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

# Re-export context constants from core_context for backward compatibility
from core_context import MAX_CONTEXT_MESSAGES, TOOL_COMPACT_AFTER


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
    "web":        ["web_search", "fetch_url", "browser_task"],
    "code":       ["run_python", "run_node", "run_script", "run_jupyter_cell", "pandas_query", "matplotlib_plot",
                   "create_project", "list_projects", "extract_project",
                   "patch_file", "search_files", "format_code", "lint_code", "run_tests", "read_file_range"],
    "kanban":     ["create_task", "create_task_plan", "list_tasks", "move_task", "update_task", "delete_task"],
    "cron":       ["create_cron", "create_once_cron", "list_crons", "delete_cron"],
    "memory":     ["memory_store", "memory_recall", "memory_search", "memory_list", "memory_delete",
                   "credential_set", "credential_get", "credential_list",
                   "wm_add", "wm_get", "wm_list", "wm_clear", "save_session", "recall_sessions", "list_sessions"],
    "config":     ["get_config", "set_config", "delete_config"],
    "agent":      ["spawn_subagent", "get_subagent_status", "list_subagents",
                   "cancel_subagent", "subagent_get_result", "subagent_update",
                   "start_coding_session", "start_tracked_coding_task", "list_capabilities",
                   "create_project", "list_projects", "extract_project", "run_swarm"],
    "message":    ["send_message", "get_messages", "telegram_send", "telegram_get_updates",
                   "telegram_send_photo", "telegram_send_video",
                   "telegram_status", "start_telegram_daemon",
                   "discord_send", "discord_get_messages", "whatsapp_send",
                   "twilio_send_sms", "twilio_send_whatsapp", "twilio_make_call",
                   "twilio_call_status", "twilio_list_messages", "twilio_lookup_phone",
                   "twilio_account_info"],
    "github":     ["github_search_code", "github_create_issue", "github_list_prs",
                   "github_repo_info", "github_clone_repo", "github_prepare_repo"],
    "finance":    ["crypto_price", "stock_price", "crypto_top"],
    "media":      ["spotify_search", "youtube_search", "gif_search", "youtube_download"],
    "system":     ["get_os_info", "get_env_var", "list_processes"],
    "research":   ["arxiv_search", "wikipedia_search", "polymarket_search"],
    "security":   ["port_scan", "http_headers_check", "ssl_check", "whois_lookup",
                   "kali_tool_status", "kali_run_recon"],
    "smarthome":  ["hue_list_lights", "hue_set_light", "mqtt_publish", "home_assistant_call"],
    "social":     ["twitter_search", "reddit_search", "mastodon_post",
                   "bluesky_search", "bluesky_post", "hackernews_top", "hackernews_search",
                   "linkedin_post", "threads_post", "instagram_post", "instagram_get_profile"],
    "note":       ["note_create", "note_search", "note_read", "note_list"],
    "email":      ["send_email", "read_emails", "search_emails", "reply_email", "send_batch_emails", "email_log", "email_setup"],
    "devops":     ["git_operation", "docker_run", "webhook_listen"],
    "creative":   ["ascii_art", "architecture_diagram", "generate_image"],
    "mlops":      ["run_eval", "model_benchmark", "huggingface_model_info"],
    "gaming":     ["minecraft_command", "pokemon_lookup"],
    "mcp":        ["mcp_list_tools", "mcp_call_tool"],
    "productivity": ["google_calendar_list", "google_calendar_create", "google_sheets_read", "airtable_query"],
    "vision":     ["vision_analyze", "image_info", "take_screenshot", "get_last_screenshot"],
    "skill":      ["skill_save", "skill_load", "skill_list", "skill_delete"],
    "plugin":     ["plugin_list", "plugin_info", "plugin_enable", "plugin_disable"],
    "delegation": ["delegate_task", "delegate_tasks"],
    "repo":       ["repo_prepare", "repo_list", "repo_status", "repo_run", "project_init", "project_install_deps"],
}

_KEYWORD_MAP: dict[str, list[str]] = {
    # file
    "file": ["file"], "folder": ["file"], "directory": ["file"], "read": ["file"],
    "write": ["file"], "delete": ["file"], "list": ["file", "kanban"],
    "dosya indirildi": ["file"], "[dosya": ["file"],  # Telegram file download messages
    "dosya": ["file"], "attım": ["file"], "gönderdim": ["file"], "kaydet": ["file", "memory"],
    "pdf": ["file"], "indir": ["file"], "yükle": ["file"],
    # shell
    "run": ["shell", "code"], "command": ["shell"], "terminal": ["shell"], "powershell": ["shell"],
    # web
    "search": ["web", "research"], "google": ["web"], "url": ["web"],
    "website": ["web", "file", "shell", "code", "agent"], "web site": ["web", "file", "shell", "code", "agent"],
    "site yap": ["file", "shell", "code", "agent"], "website yap": ["file", "shell", "code", "agent"],
    "site oluştur": ["file", "shell", "code", "agent"], "site olustur": ["file", "shell", "code", "agent"],
    "portfolio": ["web", "file", "shell", "code", "agent"], "portfolyo": ["web", "file", "shell", "code", "agent"],
    "browser": ["web"], "tarayıcı": ["web"], "siteye gir": ["web"], "fetch": ["web"],
    # code
    "python": ["code"], "script": ["code"], "code": ["code"], "execute": ["code", "shell"],
    "jupyter": ["code"], "pandas": ["code"], "plot": ["code"],
    "react": ["file", "shell", "code", "agent"], "vue": ["file", "shell", "code", "agent"],
    "svelte": ["file", "shell", "code", "agent"], "next": ["file", "shell", "code", "agent"],
    "vite": ["file", "shell", "code", "agent"], "html": ["file", "shell", "code", "agent"],
    "css": ["file", "shell", "code", "agent"], "javascript": ["file", "shell", "code", "agent"],
    "typescript": ["file", "shell", "code", "agent"], "uygulama yap": ["file", "shell", "code", "agent"],
    "kod yaz": ["file", "shell", "code", "agent"], "tasarla": ["file", "shell", "code", "agent"],
    "oluştur": ["file", "shell", "code", "agent"], "olustur": ["file", "shell", "code", "agent"],
    "coding": ["code", "agent", "kanban", "cron"], "kodlama": ["code", "agent", "kanban", "cron"],
    "donuyor": ["agent", "kanban", "cron"], "dondu": ["agent", "kanban", "cron"],
    # kanban / tasks
    "task": ["kanban"], "kanban": ["kanban"], "todo": ["kanban"], "doing": ["kanban"],
    "checklist": ["kanban"], "plan": ["kanban"],
    # cron / schedule
    "schedule": ["cron"], "cron": ["cron"], "every day": ["cron"], "recurring": ["cron"],
    "tek sefer": ["cron"], "one-shot": ["cron"], "follow-up": ["cron"], "takip": ["cron", "kanban"],
    # memory
    "remember": ["memory"], "forget": ["memory"], "recall": ["memory"], "memory": ["memory"],
    "session": ["memory"],
    # credentials
    "token": ["memory", "config"], "api key": ["memory", "config"], "apikey": ["memory", "config"],
    "credential": ["memory", "config"], "password": ["memory", "config"], "secret": ["memory", "config"],
    "key": ["memory", "config"],
    # agents
    "agent": ["agent"], "subagent": ["agent"], "parallel": ["agent"],
    # messaging
    "telegram": ["message", "config"],
    "telegram bot": ["message", "config"],
    "telegram token": ["message", "config", "memory"],
    "discord": ["message"], "whatsapp": ["message"],
    "twilio": ["message"], "sms gönder": ["message"], "arama yap": ["message"],
    "twilio_send": ["message"], "send sms": ["message"], "make call": ["message"],
    "telefon ara": ["message"], "numaraya mesaj": ["message"],
    "send message": ["message"], "message": ["message"],
    # github
    "github": ["github"], "git": ["github", "devops"], "repo": ["github"],
    "clone": ["github"], "repo çek": ["github"], "pull request": ["github"], "issue": ["github"],
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
    "security": ["security"], "kali": ["security"], "pentest": ["security"],
    "nmap": ["security"], "nikto": ["security"], "whatweb": ["security"], "nuclei": ["security"],
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
    # vision
    "image": ["vision", "creative"], "photo": ["vision"], "screenshot": ["vision", "browser_control"],
    "ekran görüntüsü": ["vision"], "resim": ["vision", "creative"], "görsel": ["vision", "creative"],
    "ocr": ["vision"], "read image": ["vision"],
    # skills
    "skill": ["skill"], "skills": ["skill"], "template": ["skill"],
    "şablon": ["skill"], "kaydet": ["skill", "memory", "file"],
    "reusable": ["skill"], "öğren": ["skill"], "learn": ["skill"],
    "procedure": ["skill"], "workflow": ["skill"],
    # plugins
    "plugin": ["plugin"], "plugins": ["plugin"], "eklenti": ["plugin"],
    "plug-in": ["plugin"], "extension": ["plugin"],
    # delegation
    "delegate": ["delegation", "agent"], "parallel": ["delegation", "agent"],
    "batch": ["delegation", "kanban"], "multi task": ["delegation"],
    "subtask": ["delegation", "kanban"], "delege et": ["delegation"],
    "alt agent": ["delegation", "agent"], "concurrent": ["delegation"],
    "background task": ["delegation", "agent"],
    # code tools
    "format": ["code"], "lint": ["code"], "test": ["code", "devops"],
    "patch": ["code", "file"], "search code": ["code"],
    "grep": ["code"], "refactor": ["code"],
    "kod formatla": ["code"], "test et": ["code"],
    "runtest": ["code"], "pytest": ["code"],
    "birlesik test": ["code"],
    # repo / project management
    "clone": ["repo", "github"], "repo": ["repo", "github"],
    "repository": ["repo"], "github repo": ["repo", "github"],
    "project": ["repo", "kanban"], "proje": ["repo"],
    "repos": ["repo"], "install deps": ["repo"],
    "kurulum": ["repo"], "bagimlilik": ["repo"],
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
        import uuid
        self._session_id = str(uuid.uuid4())
        self._active_session_id = None
        from core_context import ContextWindow
        self.provider = provider
        self.on_token = on_token
        self.channel: str = channel  # persist for use in _refresh_memory_context
        # Context window manages message list, compaction, trimming, rolling summary
        self._ctx = ContextWindow(provider)
        self._ctx.messages = [{"role": "system", "content": build_system_prompt(channel=channel)}]
        # Permission hook: callable(name, args) -> bool  (None = allow all)
        self.permission_callback: Callable[[str, dict], bool] | None = None
        # Interrupt/cancel support — set to cancel the current stream_chat loop
        self._cancel: threading.Event = threading.Event()
        self._busy: bool = False
        self._stream_lock: threading.Lock = threading.Lock()
        kanban.init_db(db_path)
        cron.init_db(db_path)
        session_memory.init_db(db_path)
        shared_memory.init_db(db_path)
        working_memory.init_db(db_path)
        from skills import agents
        agents.init_db(db_path)
        # Load tools and plugins dynamically based on active config state
        from tools.registry import rebuild_registry
        rebuild_registry()
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

    @property
    def messages(self) -> list[dict]:
        # Fallback for test instances created with Agent.__new__() without _ctx
        if hasattr(self, "_ctx"):
            return self._ctx.messages
        if not hasattr(self, "_messages"):
            self._messages = []
        return self._messages

    @messages.setter
    def messages(self, value: list[dict]) -> None:
        if hasattr(self, "_ctx"):
            self._ctx.messages = value
        else:
            self._messages = value

    @property
    def _context_summary(self) -> str:
        return self._ctx.summary

    @_context_summary.setter
    def _context_summary(self, value: str) -> None:
        self._ctx.summary = value

    def _drop_dangling_tool_calls(self) -> int:
        if hasattr(self, "_ctx"):
            return self._ctx.drop_dangling_tool_calls()
        result_ids = {
            m.get("tool_call_id", "")
            for m in self.messages
            if m.get("role") == "tool"
        }
        removed = 0
        clean = []
        skip_ids = set()
        for m in self.messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                missing = [
                    tc for tc in m["tool_calls"]
                    if tc.get("id", tc.get("name", "")) not in result_ids
                ]
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

    def _maybe_build_rolling_summary(self) -> None:
        if hasattr(self, "_ctx"):
            self._ctx.maybe_build_rolling_summary()

    def _trim_messages(self) -> list[dict]:
        if hasattr(self, "_ctx"):
            return self._ctx.trim(getattr(self.provider, "supports_vision", False))
        return self.messages

    def interrupt(self) -> bool:
        """Cancel the current in-progress stream_chat. Returns True if was busy."""
        if self._busy:
            self._cancel.set()
            return True
        return False

    def chat(self, user_input: str) -> str:
        """Send a user message, run tool loop, return final response."""
        import time
        from skills.agents.trajectory import record_trajectory
        
        t0 = time.time()
        final_response_tokens = []
        for event in self._run_conversation_loop(user_input):
            if event.get("type") == "text":
                final_response_tokens.append(event.get("token", ""))
            
        elapsed = time.time() - t0
        res = "".join(final_response_tokens)
        session_id = getattr(self, "_session_id", None)
        if not session_id:
            import uuid
            self._session_id = str(uuid.uuid4())
            session_id = self._session_id
        record_trajectory(session_id, {
            "elapsed_time": elapsed,
            "provider": self.provider.name,
            "model": getattr(self.provider, "model", ""),
            "user_input": user_input,
            "response": res,
        })
        return res

    def stream_chat(self, user_input: str, image_path: str | None = None):
        import time
        from skills.agents.trajectory import record_trajectory
        
        t0 = time.time()
        final_response_tokens = []
        for event in self._run_conversation_loop(user_input, image_path):
            if event.get("type") == "text":
                final_response_tokens.append(event.get("token", ""))
            yield event
            
        elapsed = time.time() - t0
        res = "".join(final_response_tokens)
        session_id = getattr(self, "_session_id", None)
        if not session_id:
            import uuid
            self._session_id = str(uuid.uuid4())
            session_id = self._session_id
        record_trajectory(session_id, {
            "elapsed_time": elapsed,
            "provider": self.provider.name,
            "model": getattr(self.provider, "model", ""),
            "user_input": user_input,
            "response": res,
        })


    def _run_conversation_loop(self, user_input: str, image_path: str | None = None):
        """
        Unified conversation loop that drives one turn.
        Yields structured events:
          {"type": "thinking"}                         — waiting for LLM
          {"type": "text", "token": token}             — text token from LLM
          {"type": "tool_start", "name": ..., "args": ...}
          {"type": "tool_done",  "name": ..., "result": ..., "elapsed": float}
          {"type": "tool_denied", "name": ...}
          {"type": "error", "message": ...}
          {"type": "interrupted"}
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
        if hasattr(self, "_stream_lock"):
            self._stream_lock.acquire()

        try:
            MAX_ROUNDS = 25  # safety cap — allows complex multi-step tasks
            empty_retries = 0
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
                _stream_key_retries = 0
                while True:
                    try:
                        for item in self.provider.stream_chat(self._trim_messages(), tools=tools, cancel_event=self._cancel):
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
                        _emsg = str(_e).lower()
                        is_rate_limit = "429" in _emsg or "rate limit" in _emsg or "quota" in _emsg or "exhausted" in _emsg or "limit" in _emsg
                        if is_rate_limit and _stream_key_retries < 5:
                            if hasattr(self.provider, "rotate_key") and self.provider.rotate_key():
                                _stream_key_retries += 1
                                full = ""
                                _tool_buf = {}
                                import logging
                                logging.getLogger(__name__).warning("Rate limit hit during stream, rotated to next API key.")
                                continue

                        # Auto-recover from "tool_calls must be followed by tool messages" (400)
                        _emsg = str(_e)
                        if not _stream_retried and not full and not _tool_buf and ("tool_calls" in _emsg or "400" in _emsg):
                            _stream_retried = True
                            n = self._drop_dangling_tool_calls()
                            import logging as _logging
                            _logging.getLogger(__name__).warning(
                                f"stream_chat: 400 tool_calls error — dropped {n} dangling messages, retrying"
                            )
                            full = ""
                            _tool_buf = {}
                            continue
                        # For any other exception, yield an error event instead of crashing
                        yield {"type": "error", "message": str(_e)}
                        return

                # ── Empty response detection & recovery ──────────────────────────
                if not full and not _tool_buf:
                    if empty_retries < 3:
                        empty_retries += 1
                        import logging
                        logging.getLogger(__name__).warning(
                            f"Empty response from model — retry {empty_retries}/3"
                        )
                        # We trigger a status/thinking event and continue the loop to retry
                        if self.provider.supports_thinking:
                            yield {"type": "thinking"}
                        continue
                    else:
                        # Retries exhausted
                        self.messages.append({"role": "assistant", "content": ""})
                        return

                # Reset empty retries counter if we got some content or tool calls
                empty_retries = 0

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
            if hasattr(self, "_stream_lock") and self._stream_lock.locked():
                try:
                    self._stream_lock.release()
                except RuntimeError:
                    pass  # already released

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
                    available.append("Playwright visible browser automation (browser_task) and headless render (js_render=True)")
                else:
                    unavailable.append("Playwright browser automation (browser_task/js_render=True will fail — skip it)")
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
                    working_memory.wm_add(
                        summary="Telegram bot token saved to config.",
                        detail="Next step: call start_telegram_daemon and then telegram_status.",
                        event_type="config",
                    )
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
            if name == "save_session" and not args.get("messages"):
                return self.auto_save(
                    title=str(args.get("title") or ""),
                    summary=str(args.get("summary") or ""),
                )
            if name == "browser_task":
                try:
                    from skills import browser_control as _browser_control
                    _browser_control.set_permission_callback(self.permission_callback)
                except Exception:
                    pass
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
        self._active_session_id = None  # reset active session ID
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
        active_id = getattr(self, "_active_session_id", None)
        new_id = session_memory.save_session(title, msgs, summary, session_id=active_id)
        self._active_session_id = new_id
        return f"Session #{new_id} saved: '{title}'"
