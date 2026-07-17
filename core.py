# -*- coding: utf-8 -*-
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


from utils.json_utils import _escape_invalid_chars_in_json_strings, _repair_tool_call_arguments



from utils.system_utils import _detect_capabilities



_PARALLEL_SAFE_TOOLS = {
    "web_search", "fetch_url",
    "memory_recall", "memory_store",
    "get_config", "set_config",
    "read_file", "list_dir",
    "wm_list", "wm_get", "wm_add"
}


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
    "skill":      ["skill_save", "skill_load", "skill_list", "skill_delete", "enable_core_skill", "disable_core_skill", "list_core_skills"],
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
    "yazılım": ["code", "agent"], "yazilim": ["code", "agent"], "program": ["code", "agent"],
    "donuyor": ["agent", "kanban", "cron"], "dondu": ["agent", "kanban", "cron"],
    # kanban / tasks
    "task": ["kanban"], "kanban": ["kanban"], "todo": ["kanban"], "doing": ["kanban"],
    "checklist": ["kanban"], "plan": ["kanban"],
    "görev": ["kanban"], "gorev": ["kanban"], "yapılacak": ["kanban"], "yapilacak": ["kanban"],
    "yapılacaklar": ["kanban"],
    # cron / schedule
    "schedule": ["cron"], "cron": ["cron"], "every day": ["cron"], "recurring": ["cron"],
    "tek sefer": ["cron"], "one-shot": ["cron"], "follow-up": ["cron"], "takip": ["cron", "kanban"],
    "zamanla": ["cron"], "saatlik": ["cron"], "günlük": ["cron"], "gunluk": ["cron"],
    "haftalık": ["cron"], "haftalik": ["cron"], "aylık": ["cron"], "aylik": ["cron"],
    "timer": ["cron"], "reminder": ["cron"], "remind": ["cron"], "hatırlat": ["cron"], "hatirlat": ["cron"],
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
    "wp": ["message"], "whatsapp": ["message"], "mesaj": ["message"], "bot": ["message"],
    "slack": ["message"], "signal": ["message"], "send_message": ["message"],
    "notify": ["message", "email"], "notification": ["message", "email"], "ping": ["message", "email"],
    "inform": ["message", "email"], "haber ver": ["message", "email"], "yaz": ["message", "email"],
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
    "tarama": ["security"], "tara": ["security"], "açık": ["security"], "acik": ["security"],
    "zafiyet": ["security"], "sızma": ["security"], "sizma": ["security"],
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
    "eposta": ["email"], "e-posta": ["email"], "ileti": ["email"],
    "e-mail": ["email"],
    "gönder": ["email", "message"], "gonder": ["email", "message"], "yolla": ["email", "message"],
    "gmail": ["email"], "outlook": ["email"], "imap": ["email"], "pop3": ["email"],
    "inbox": ["email"], "send email": ["email"], "send mail": ["email"], "email_skill": ["email"],
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
    "install deps": ["repo"],
    "kurulum": ["repo"], "bagimlilik": ["repo"],
    # mcp
    "mcp": ["mcp"], "mcp server": ["mcp"], "model context": ["mcp"],
}

# ── Core tools always included ────────────────────────────────────────────────
# Minimal set sent even when keyword matching gives no results.
# These are general-purpose enough that almost any task may need them.
_CORE_TOOL_NAMES: set[str] = {
    "web_search", "fetch_url",
    "memory_recall", "memory_store",
    "run_command", "run_python",
    "read_file", "write_file",
    "list_dir", "create_dir",
    "get_config", "set_config",
    "wm_list", "wm_get", "wm_add",
    "enable_core_skill", "disable_core_skill", "list_core_skills",
}

def _tool_name(t: dict) -> str:
    """Get tool name regardless of nested or flat format."""
    if "function" in t:
        return t["function"]["name"]
    return t.get("name", "")

_TOOL_BY_NAME: dict[str, dict] = {_tool_name(t): t for t in ALL_TOOLS}


class ToolLoopGuardrail:
    """
    Tracks tool-call failures and repetition across a single turn/loop.
    Provides warning or block actions to steer model out of loop state.
    """
    IDEMPOTENT_TOOLS = frozenset({
        "read_file", "read_file_range", "search_files", "find_files", "list_dir",
        "web_search", "fetch_url", "memory_recall", "memory_search",
        "get_config", "list_tasks", "list_crons", "list_subagents", "get_subagent_status",
        "email_log", "list_core_skills", "plugin_list"
    })

    def __init__(self):
        self.reset()

    def reset(self):
        self._consecutive_idempotent_calls: dict[tuple[str, str], list[str]] = {}
        self._consecutive_failures: dict[tuple[str, str], int] = {}
        self._total_failures_by_tool: dict[str, int] = {}

    def before_call(self, name: str, args: dict) -> tuple[bool, str]:
        import json
        try:
            args_str = json.dumps(args, sort_keys=True)
        except Exception:
            args_str = str(args)

        key = (name, args_str)

        # 1. Block if the exact same tool call has failed 4 or more times
        exact_fail_count = self._consecutive_failures.get(key, 0)
        if exact_fail_count >= 4:
            msg = (
                f"ERROR: Tool call blocked. The tool call '{name}' with arguments {args} "
                f"has failed {exact_fail_count} times consecutively. Stop retrying it unchanged; "
                f"change your arguments, switch to a different tool, or report the blocker to the user."
            )
            return True, msg

        # 2. Block if we've run this same tool in general 7 times and it failed
        tool_fail_count = self._total_failures_by_tool.get(name, 0)
        if tool_fail_count >= 7:
            msg = (
                f"ERROR: Tool call blocked. The tool '{name}' has failed {tool_fail_count} times in this turn. "
                f"Stop retrying this tool; change strategy entirely."
            )
            return True, msg

        # 3. Block if we've run this idempotent tool and got the same result 5 times consecutively
        if name in self.IDEMPOTENT_TOOLS:
            consec_results = self._consecutive_idempotent_calls.get(key, [])
            if len(consec_results) >= 5:
                msg = (
                    f"ERROR: Tool call blocked. This read-only tool call has returned the same result "
                    f"{len(consec_results)} times consecutively. Stop repeating it unchanged; "
                    f"use the information already returned in previous turns or try a different query."
                )
                return True, msg

        return False, ""

    def after_call(self, name: str, args: dict, result: str) -> str:
        import json
        try:
            args_str = json.dumps(args, sort_keys=True)
        except Exception:
            args_str = str(args)

        key = (name, args_str)

        is_failure = False
        result_str = str(result).strip()
        if result_str:
            if "Exit code:" in result_str and "Exit code: 0" not in result_str:
                is_failure = True
            else:
                lower = result_str.lower()
                if (
                    result_str.startswith("ERROR:")
                    or result_str.startswith("Tool error")
                    or result_str.startswith("Unknown tool")
                    or result_str.startswith("❌")
                    or result_str.startswith("[Tool execution cancelled")
                    or any(err in lower[:50] for err in ("failed", "not configured", "not installed", "required", "error:", "timed out", "permission denied"))
                ):
                    is_failure = True

        if is_failure:
            self._consecutive_failures[key] = self._consecutive_failures.get(key, 0) + 1
            self._total_failures_by_tool[name] = self._total_failures_by_tool.get(name, 0) + 1
            self._consecutive_idempotent_calls.pop(key, None)

            exact_fail_count = self._consecutive_failures[key]
            if exact_fail_count >= 2:
                warning = (
                    f"\n\n[Warning: Tool call '{name}' has failed {exact_fail_count} times consecutively "
                    f"with identical arguments. This looks like a loop; inspect the error, check your credentials "
                    f"or configurations, and modify your arguments/strategy instead of retrying unchanged.]"
                )
                return result + warning
        else:
            self._consecutive_failures.pop(key, None)
            self._total_failures_by_tool[name] = max(0, self._total_failures_by_tool.get(name, 0) - 1)

            if name in self.IDEMPOTENT_TOOLS:
                results = self._consecutive_idempotent_calls.setdefault(key, [])
                results.append(result_str)
                if len(results) > 10:
                    results.pop(0)

                if len(results) >= 3 and len(set(results[-3:])) == 1:
                    warning = (
                        f"\n\n[Warning: This read-only tool call has returned the same result {len(results)} "
                        f"times consecutively. Use the results already returned above or change arguments "
                        f"instead of repeating the request.]"
                    )
                    return result + warning
            else:
                self._consecutive_idempotent_calls.clear()

        return result


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
    r"(?P<service1>[\w\s]+?)\s+(?:api\s*)?(?:key|token|secret|password|credential|apikey|api_key|access_token|anahtar|anahtarı|şifre|sifre|parola)\s*(?:is|:|da|de|=)\s*(?P<val1>\S{8,})"
    r"|(?P<val2>(?:sk-|ghp_|xox[bprao]-|Bearer\s+)\S{6,})"
    r"|(?P<service2>[\w]+)\s+(?:api\s+)?(?:key|anahtar)\s*[:=]\s*(?P<val3>\S{8,})"
    r")",
    _re.IGNORECASE,
)
# Telegram bot token: digits:alphanumeric (e.g. 1234567890:ABCdefGHI...)
_TG_TOKEN_RE = _re.compile(r'\b(\d{8,12}:[A-Za-z0-9_\-]{30,50})\b')


def _select_tools(user_input: str, messages: list[dict] = None, router_groups: set[str] | None = None) -> list[dict]:
    """
    Return a targeted subset of tools based on keywords in the user message,
    recent history, and recently executed tools, optionally augmented by LLM routing decision.
    - If keywords/router match or tools were recently called → return those tool groups (+ always-on core tools)
    - If no match → return only the minimal _CORE_TOOL_NAMES set
    Never returns ALL_TOOLS upfront; groups are expanded dynamically during the
    agentic loop via _expand_tools_for_call() when the model requests them.
    """
    lower = user_input.lower()
    groups: set[str] = set()

    # Regex checks on current user input
    if _re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", user_input):
        groups.add("email")
    if _re.search(r"\b(?:\+?\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b|\b(?:05\d{9}|\+905\d{9})\b", user_input):
        groups.add("message")
    if _re.search(r"github\.com/[\w\-]+/[\w\-]+", user_input, _re.IGNORECASE) or _re.search(r"\bgithub\b", user_input, _re.IGNORECASE):
        groups.update(["github", "devops"])

    # 1. Scan current user input
    for keyword, grp_list in _KEYWORD_MAP.items():
        if keyword in lower:
            groups.update(grp_list)

    # 2. Integrate router classified groups
    if router_groups:
        groups.update(router_groups)

    # 2. Scan recent messages in history if provided
    if messages:
        # Scan last 4 messages in history for keywords (user messages only, to avoid assistant hallucinations)
        recent_user_texts = []
        for msg in messages[-6:]:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    recent_user_texts.append(content.lower())
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            recent_user_texts.append(item.get("text", "").lower())
        
        for r_text in recent_user_texts:
            if _re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", r_text):
                groups.add("email")
            if _re.search(r"\b(?:\+?\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b|\b(?:05\d{9}|\+905\d{9})\b", r_text):
                groups.add("message")
            if _re.search(r"github\.com/[\w\-]+/[\w\-]+", r_text, _re.IGNORECASE) or _re.search(r"\bgithub\b", r_text, _re.IGNORECASE):
                groups.update(["github", "devops"])
            for keyword, grp_list in _KEYWORD_MAP.items():
                if keyword in r_text:
                    groups.update(grp_list)

        # Scan recent assistant messages for tools that were actually called.
        # If the assistant called a tool, keep its group active.
        for msg in messages[-6:]:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_name = tc.get("name")
                    if tc_name:
                        for g, group_tools in _TOOL_GROUPS.items():
                            if tc_name in group_tools:
                                groups.add(g)

    # Auto-enable disabled skills if their group is requested
    if groups:
        from config import load_config, save_config
        from tools.registry import rebuild_registry
        try:
            cfg = load_config()
            disabled = cfg.get("disabled_skills", [])
            if disabled:
                # Map of tool groups to skill names
                _GROUP_TO_SKILL_MAP = {
                    "email": "email_skill",
                    "message": "messaging",
                    "github": "github_skill",
                    "cron": "cron",
                    "creative": "creative",
                    "productivity": "productivity",
                    "security": "security",
                    "mlops": "mlops",
                    "finance": "finance",
                    "gaming": "gaming",
                    "research": "research",
                    "media": "media",
                    "social": "social",
                    "smarthome": "smarthome",
                    "devops": "devops",
                    "vision": "vision",
                    "code": "code_tools",
                    "kanban": "kanban",
                    "mcp": "mcp_skill",
                }
                needed_skills = []
                for g in groups:
                    skill_id = _GROUP_TO_SKILL_MAP.get(g)
                    if skill_id and skill_id in disabled:
                        needed_skills.append(skill_id)
                if needed_skills:
                    for skill_id in needed_skills:
                        disabled.remove(skill_id)
                    cfg["disabled_skills"] = disabled
                    save_config(cfg)
                    rebuild_registry(force=True)
        except Exception:
            pass

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
        # Progress callback: callable(event_type, name, preview, args, **kwargs)
        self.tool_progress_callback = None
        # Interrupt/cancel support — set to cancel the current stream_chat loop
        self._cancel: threading.Event = threading.Event()
        self._busy: bool = False
        self.cfg = cfg or {}
        self._session_progress: float = self.cfg.get("session_progress", 0.0)
        self._stream_lock: threading.Lock = threading.Lock()
        self.db_path = db_path
        kanban.init_db(db_path)
        cron.init_db(db_path)
        session_memory.init_db(db_path)
        shared_memory.init_db(db_path)
        working_memory.init_db(db_path)
        from skills import agents
        agents.init_db(db_path)
        
        # Initialize IntentRouter and StreamingThinkScrubber
        from router import IntentRouter
        from providers.think_scrubber import StreamingThinkScrubber
        coding_enabled = self.cfg.get("coding_mode", {}).get("enabled", False)
        self._router = IntentRouter(provider, coding_enabled=coding_enabled)
        self._stream_think_scrubber = StreamingThinkScrubber()
        
        # Initialize tool execution middleware list
        from tools.middleware import DEFAULT_MIDDLEWARES
        self.tool_middlewares = list(DEFAULT_MIDDLEWARES)
        
        # Load tools and plugins dynamically based on active config state
        from tools.registry import rebuild_registry
        rebuild_registry(force=True)
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
        
        # Tool call loop guardrail
        self._guardrail = ToolLoopGuardrail()

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
            "messages": self.messages,
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
            "messages": self.messages,
        })


    def _resolve_available_tools(
        self,
        user_input: str,
        tool_groups: set[str] | None,
        is_local: bool,
        previous_tools: list[dict] | None = None
    ) -> list[dict]:
        """
        Resolve the final list of tools (up to 128) based on routing selection,
        plugin tools prioritization, and optional merging with previously expanded tools.
        """
        tools = _select_tools(user_input, self.messages, router_groups=tool_groups)
        if not is_local:
            # For remote providers, maximize capabilities (up to 128 tools),
            # but MUST prioritize selected tools so they are never truncated.
            original_selected_names = {_tool_name(t) for t in tools}
            selected_names = set(original_selected_names)
            
            from tools.registry import _PLUGIN_TOOLS
            plugin_names = {_tool_name(t) for t in _PLUGIN_TOOLS}
            
            merged_tools = list(tools)
            
            # Prioritize plugin (e.g. MCP) tools so they don't get truncated
            for t in ALL_TOOLS:
                name = _tool_name(t)
                if name not in selected_names and name in plugin_names:
                    merged_tools.append(t)
                    selected_names.add(name)
            
            for t in ALL_TOOLS:
                if _tool_name(t) not in selected_names:
                    merged_tools.append(t)
            
            if not getattr(self, "cfg", {}).get("dynamic_tool_selection_cloud", False):
                tools = merged_tools[:128]
            else:
                if original_selected_names.issubset(_CORE_TOOL_NAMES):
                    tools = merged_tools[:128]

        if previous_tools:
            # Merge current tools (including those added by _expand_tools_for_call)
            merged = list(tools)
            current_names = {_tool_name(t) for t in tools}
            for t in previous_tools:
                name = _tool_name(t)
                if name not in current_names:
                    merged.append(t)
            tools = merged[:128]
            
        return tools

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

        if hasattr(self, "_guardrail") and self._guardrail:
            self._guardrail.reset()

        self._pre_fetched_context = ""
        try:
            for event in self._pre_fetch_links(user_input):
                yield event
        except Exception:
            pass

        processed_input = user_input
        if getattr(self, "_pre_fetched_context", ""):
            processed_input += self._pre_fetched_context

        # Run the IntentRouter classification to dynamically select tools and prompt sections
        routing_decision = None
        if hasattr(self, "_router") and self._router:
            try:
                routing_decision = self._router.classify(processed_input)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Router classification failed in core: {e}")

        prompt_sections = set(routing_decision.prompt_sections) if routing_decision else None
        self._refresh_memory_context(processed_input, prompt_sections=prompt_sections)

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
                        {"type": "text", "text": processed_input},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{mime_type};base64,{b64_data}"
                        }},
                    ],
                }
            except Exception:
                user_msg = {"role": "user", "content": processed_input}
        else:
            user_msg = {"role": "user", "content": processed_input}

        self.messages.append(user_msg)
        is_local = getattr(self.provider, "name", "ollama") in ("ollama", "lm_studio")
        tool_groups = set(routing_decision.tool_groups) if routing_decision else None
        tools = self._resolve_available_tools(processed_input, tool_groups, is_local)

        self._cancel.clear()
        self._busy = True
        if hasattr(self, "_stream_lock"):
            self._stream_lock.acquire()

        try:
            MAX_ROUNDS = 25  # safety cap — allows complex multi-step tasks
            empty_retries = 0
            length_continuation_count = 0
            for _round in range(MAX_ROUNDS):
                if self._cancel.is_set():
                    yield {"type": "interrupted"}
                    return

                # Dynamically re-evaluate tools to pick up newly enabled skills / plugins, while preserving previously expanded tools
                try:
                    tools = self._resolve_available_tools(
                        processed_input, tool_groups, is_local, previous_tools=tools
                    )
                except Exception as _tool_sel_err:
                    import logging
                    logging.getLogger(__name__).warning(f"Error updating tools during loop: {_tool_sel_err}")

                if self.provider.supports_thinking:
                    yield {"type": "thinking"}

                # ── Collect the streaming response ──────────────────────────────
                full = ""
                _tool_buf: dict[int, dict] = {}

                _stream_retried = False
                _stream_key_retries = 0
                _stream_call_retries = 0
                _MAX_STREAM_RETRIES = 3
                _finish_reason = None
                while True:
                    try:
                        if hasattr(self, "_stream_think_scrubber"):
                            self._stream_think_scrubber.reset()
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
                            elif isinstance(item, dict) and item.get("__finish_reason__"):
                                _finish_reason = item["__finish_reason__"]
                            else:
                                token = item if isinstance(item, str) else (item.get("token", "") if isinstance(item, dict) else "")
                                if token:
                                    if hasattr(self, "_stream_think_scrubber"):
                                        scrubbed = self._stream_think_scrubber.feed(token)
                                    else:
                                        scrubbed = token
                                    if scrubbed:
                                        full += scrubbed
                                        yield {"type": "text", "token": scrubbed}
                        if hasattr(self, "_stream_think_scrubber"):
                            tail = self._stream_think_scrubber.flush()
                            if tail:
                                full += tail
                                yield {"type": "text", "token": tail}
                        break  # stream finished successfully
                    except Exception as _e:
                        from providers.error_classifier import classify_api_error, FailoverReason
                        err = classify_api_error(_e, provider=getattr(self.provider, "name", ""), model=getattr(self.provider, "_model", ""))
                        is_rate_limit = (err.reason == FailoverReason.rate_limit)
                        is_billing = (err.reason == FailoverReason.billing)
                        is_overloaded = (err.reason in (FailoverReason.overloaded, FailoverReason.server_error, FailoverReason.timeout))
                        
                        # Only retry if we have not successfully yielded any tokens yet to prevent duplicate/corrupted output
                        if not full and not _tool_buf:
                            if (is_rate_limit or is_billing) and _stream_key_retries < 5:
                                if hasattr(self.provider, "rotate_key"):
                                    # Prevent MagicMock from falsely returning a truthy mock object
                                    from unittest.mock import Mock
                                    if not isinstance(self.provider.rotate_key, Mock) and self.provider.rotate_key():
                                        _stream_key_retries += 1
                                        full = ""
                                        _tool_buf = {}
                                        import logging
                                        logging.getLogger(__name__).warning("Rate limit hit during stream, rotated to next API key.")
                                        continue

                            # Auto-recover from "tool_calls must be followed by tool messages" (400)
                            _emsg_orig = str(_e)
                            if not _stream_retried and ("tool_calls" in _emsg_orig or "400" in _emsg_orig):
                                _stream_retried = True
                                n = self._drop_dangling_tool_calls()
                                import logging as _logging
                                _logging.getLogger(__name__).warning(
                                    f"stream_chat: 400 tool_calls error — dropped {n} dangling messages, retrying"
                                )
                                full = ""
                                _tool_buf = {}
                                continue

                            # If rate limit or overloaded/timeout, retry with jittered backoff
                            if (is_rate_limit or is_overloaded) and _stream_call_retries < _MAX_STREAM_RETRIES:
                                _stream_call_retries += 1
                                full = ""
                                _tool_buf = {}
                                
                                # Calculate jittered backoff delay
                                import random
                                import time
                                exponent = max(0, _stream_call_retries - 1)
                                base_delay = 3.0
                                max_delay = 30.0
                                delay = min(base_delay * (2 ** exponent), max_delay)
                                jitter = random.uniform(0, 0.5 * delay)
                                wait_time = delay + jitter
                                
                                import logging
                                logging.getLogger(__name__).warning(
                                    f"Stream API call failed ({_e}). Waiting {wait_time:.2f}s before retry {_stream_call_retries}/{_MAX_STREAM_RETRIES}..."
                                )
                                
                                # Sleep but check for cancellation
                                sleep_step = 0.1
                                slept = 0.0
                                while slept < wait_time:
                                    if self._cancel.is_set():
                                        yield {"type": "interrupted"}
                                        return
                                    time.sleep(sleep_step)
                                    slept += sleep_step
                                continue

                        # For any other exception, or if we already yielded tokens, yield an error event instead of crashing
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
                        
                        # Apply the nudge to recover from empty responses
                        _prior_was_tool = any(m.get("role") == "tool" for m in self.messages[-5:])
                        if _prior_was_tool:
                            self.messages.append({
                                "role": "assistant",
                                "content": "(empty)",
                                "_empty_recovery_synthetic": True
                            })
                            self.messages.append({
                                "role": "user",
                                "content": (
                                    "You just executed tool calls but returned an empty response. "
                                    "Please process the tool results above and continue with the task."
                                ),
                                "_empty_recovery_synthetic": True
                            })
                        else:
                            self.messages.append({
                                "role": "assistant",
                                "content": "(empty)",
                                "_empty_recovery_synthetic": True
                            })
                            self.messages.append({
                                "role": "user",
                                "content": "Please continue with the request.",
                                "_empty_recovery_synthetic": True
                            })

                        if self.provider.supports_thinking:
                            yield {"type": "thinking"}
                        continue
                    else:
                        # Retries exhausted
                        self.messages.append({
                            "role": "assistant",
                            "content": "I apologize, but I encountered an empty response from the model and was unable to proceed."
                        })
                        return

                # Reset empty retries counter if we got some content or tool calls
                empty_retries = 0

                if _finish_reason in ("length", "max_tokens"):
                    if length_continuation_count < 3:
                        length_continuation_count += 1
                        self.messages.append({"role": "assistant", "content": full})
                        self.messages.append({
                            "role": "user",
                            "content": (
                                "[System: Your previous response was truncated by the output length limit. "
                                "Continue exactly where you left off. Do not restart or repeat prior text. "
                                "Finish the answer directly.]"
                            )
                        })
                        import logging
                        logging.getLogger(__name__).warning(
                            f"Response truncated. Triggering continuation round {length_continuation_count}/3."
                        )
                        if self.provider.supports_thinking:
                            yield {"type": "thinking"}
                        continue

                # ── No tool calls → pure text response, done ─────────────────────
                if not _tool_buf:
                    self.messages.append({"role": "assistant", "content": full})
                    return

                # ── Build call list from buffered chunks ─────────────────────────
                calls = []
                for idx, stc in sorted(_tool_buf.items()):
                    raw_args = stc["args"] or "{}"
                    try:
                        args_parsed = _json.loads(raw_args)
                    except Exception:
                        repaired = _repair_tool_call_arguments(raw_args, tool_name=stc["name"])
                        try:
                            args_parsed = _json.loads(repaired)
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
                
                use_parallel = len(calls) > 1 and all(c["name"] in _PARALLEL_SAFE_TOOLS for c in calls)
                
                if use_parallel:
                    denied_indices = set()
                    for idx, call in enumerate(calls):
                        name, args = call["name"], call["arguments"]
                        if self.permission_callback and not self.permission_callback(name, args):
                            denied_indices.add(idx)
                            yield {"type": "tool_denied", "name": name}
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "name": name,
                                "content": "Permission denied by user.",
                            })
                    
                    parallel_calls = [(idx, c) for idx, c in enumerate(calls) if idx not in denied_indices]
                    
                    if parallel_calls:
                        non_blocked_parallel_calls = []
                        blocked_results = {}
                        for idx, call in parallel_calls:
                            name, args = call["name"], call["arguments"]
                            blocked, synth_err = self._guardrail.before_call(name, args)
                            if blocked:
                                blocked_results[call["id"]] = synth_err
                            else:
                                non_blocked_parallel_calls.append((idx, call))

                        for _, call in parallel_calls:
                            name, args = call["name"], call["arguments"]
                            yield {"type": "tool_start", "name": name, "args": args}
                            if hasattr(self, "tool_progress_callback") and self.tool_progress_callback:
                                try:
                                    preview_parts = []
                                    for pk, pv in list(args.items())[:3]:
                                        if pk not in ("code", "script", "content", "text", "body"):
                                            preview_parts.append(f"{pk}={repr(pv)[:30]}")
                                    preview = ", ".join(preview_parts)
                                    self.tool_progress_callback("tool.started", name, preview, args)
                                except Exception:
                                    pass
                        
                        from concurrent.futures import ThreadPoolExecutor
                        def run_one(call):
                            name, args = call["name"], call["arguments"]
                            t0 = time.time()
                            try:
                                res = self._execute_tool(name, args)
                            except Exception as e:
                                import traceback
                                res = f"Error executing tool: {e}\n{traceback.format_exc()}"
                            t_elapsed = time.time() - t0
                            return res, t_elapsed

                        if non_blocked_parallel_calls:
                            import concurrent.futures
                            with ThreadPoolExecutor(max_workers=len(non_blocked_parallel_calls)) as executor:
                                future_to_call = {}
                                for idx, call in non_blocked_parallel_calls:
                                    future_to_call[executor.submit(run_one, call)] = (idx, call)

                                futures = list(future_to_call.keys())
                                completed_results = {}

                                while futures:
                                    if self._cancel.is_set():
                                        for f in futures:
                                            f.cancel()
                                        break

                                    done, futures = concurrent.futures.wait(
                                        futures, timeout=0.1, return_when=concurrent.futures.FIRST_COMPLETED
                                    )

                                    for f in done:
                                        idx, call = future_to_call[f]
                                        name, args = call["name"], call["arguments"]
                                        try:
                                            res, t_elapsed = f.result()
                                        except concurrent.futures.CancelledError:
                                            res = "Tool execution cancelled due to user interrupt."
                                            t_elapsed = 0.0
                                        except Exception as e:
                                            import traceback
                                            res = f"Error executing tool: {e}\n{traceback.format_exc()}"
                                            t_elapsed = 0.0

                                        res = self._guardrail.after_call(name, args, res)
                                        completed_results[call["id"]] = (res, t_elapsed)

                                        if hasattr(self, "tool_progress_callback") and self.tool_progress_callback:
                                            try:
                                                self.tool_progress_callback("tool.completed", name, str(res)[:300], args, duration=t_elapsed)
                                            except Exception:
                                                pass

                                for idx, call in non_blocked_parallel_calls:
                                    call_id = call["id"]
                                    if call_id in completed_results:
                                        res, t_elapsed = completed_results[call_id]
                                    else:
                                        res = "Tool execution cancelled or skipped."
                                        t_elapsed = 0.0

                                    name, args = call["name"], call["arguments"]
                                    yield {"type": "tool_done", "name": name, "result": res, "elapsed": t_elapsed}
                                    res_str = str(res)
                                    self.messages.append({
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "name": name,
                                        "content": res_str,
                                    })
                                    if "PERMANENT FAILURE" in res_str:
                                        permanent_failure = True
                        
                        for idx, call in parallel_calls:
                            if call["id"] in blocked_results:
                                name, args = call["name"], call["arguments"]
                                res_str = blocked_results[call["id"]]
                                yield {"type": "tool_done", "name": name, "result": res_str, "elapsed": 0.0}
                                self.messages.append({
                                    "role": "tool",
                                    "tool_call_id": call["id"],
                                    "name": name,
                                    "content": res_str,
                                })
                        if self._cancel.is_set():
                            yield {"type": "interrupted"}
                            return
                else:
                    for i, call in enumerate(calls):
                        if self._cancel.is_set():
                            for remaining_call in calls[i:]:
                                self.messages.append({
                                    "role": "tool",
                                    "tool_call_id": remaining_call["id"],
                                    "name": remaining_call["name"],
                                    "content": "Process interrupted by user.",
                                })
                            yield {"type": "interrupted"}
                            return
                        name, args = call["name"], call["arguments"]
                        
                        # Check loop guardrail before call
                        blocked, synth_err = self._guardrail.before_call(name, args)
                        if blocked:
                            yield {"type": "tool_start", "name": name, "args": args}
                            yield {"type": "tool_done", "name": name, "result": synth_err, "elapsed": 0.0}
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "name": name,
                                "content": synth_err,
                            })
                            continue

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
                        if hasattr(self, "tool_progress_callback") and self.tool_progress_callback:
                            try:
                                preview_parts = []
                                for pk, pv in list(args.items())[:3]:
                                    if pk not in ("code", "script", "content", "text", "body"):
                                        preview_parts.append(f"{pk}={repr(pv)[:30]}")
                                preview = ", ".join(preview_parts)
                                self.tool_progress_callback("tool.started", name, preview, args)
                            except Exception:
                                pass
                        t0 = time.time()
                        try:
                            result = self._execute_tool(name, args)
                        except Exception as e:
                            import traceback
                            result = f"Error executing tool: {e}\n{traceback.format_exc()}"
                        t_elapsed = time.time() - t0
                        
                        # Check loop guardrail after call
                        result = self._guardrail.after_call(name, args, result)

                        if hasattr(self, "tool_progress_callback") and self.tool_progress_callback:
                            try:
                                self.tool_progress_callback("tool.completed", name, str(result)[:300], args, duration=t_elapsed)
                            except Exception:
                                pass
                        yield {"type": "tool_done", "name": name, "result": result, "elapsed": t_elapsed}
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
            # Clean up empty recovery synthetic messages from self.messages
            self.messages = [m for m in self.messages if not m.get("_empty_recovery_synthetic")]

    def _refresh_memory_context(self, user_input: str, prompt_sections: set[str] | None = None) -> None:
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
            new_system = build_system_prompt(user_input, wm_ctx or "", channel=self.channel, sections=prompt_sections)
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

            # ── Email credentials auto-detection ──────────────────────────────
            email_match = _re.search(r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b", user_input)
            if email_match:
                email_addr = email_match.group(1)
                # Find password: "password: xyz" or "password is xyz" or "password = xyz" or "pwd: xyz"
                pass_match = _re.search(
                    r"\b(?:pass(?:word)?|pwd|app[- ]?pass(?:word)?|şifre[m]?|sifre[m]?|parola[m]?)\s*(?:is|:|da|de|=|\s)\s*([a-zA-Z0-9_\-~@#$^*()\[\]{}]{8,})\b",
                    user_input,
                    _re.IGNORECASE
                )
                if pass_match:
                    email_pass = pass_match.group(1)
                    try:
                        from config import load_config, save_config
                        from skills.email_skill import _preset_for, init_email
                        _cfg = load_config()
                        _cfg.setdefault("email", {})
                        _cfg["email"]["username"] = email_addr
                        _cfg["email"]["password"] = email_pass
                        preset = _preset_for(email_addr)
                        if preset:
                            _cfg["email"]["smtp_host"] = preset.get("smtp_host", "smtp.gmail.com")
                            _cfg["email"]["smtp_port"] = preset.get("smtp_port", 587)
                            _cfg["email"]["imap_host"] = preset.get("imap_host", "imap.gmail.com")
                        save_config(_cfg)
                        init_email(_cfg)
                        working_memory.wm_add(
                            summary=f"Email credentials for {email_addr} auto-saved.",
                            detail=f"Auto-configured SMTP: {_cfg['email'].get('smtp_host')}:{_cfg['email'].get('smtp_port')}",
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
        from tools.middleware import MiddlewareChain
        from tools.registry import ALL_HANDLERS

        handler = ALL_HANDLERS.get(name)
        if not handler:
            return f"Unknown tool: {name}. Note: Many tools are disabled by default to save resources. You can check disabled skills using get_config('disabled_skills') and enable them via set_config."

        def terminal_call(final_args: dict) -> Any:
            return handler(**final_args)

        middlewares = getattr(self, "tool_middlewares", [])
        chain = MiddlewareChain(middlewares)
        try:
            return chain.execute(self, name, args, terminal_call)
        except Exception as e:
            return f"Tool error ({name}): {e}"

    def reset(self):
        self.auto_save()  # save session before clearing
        self._active_session_id = None  # reset active session ID
        self.messages = [{"role": "system", "content": build_system_prompt(channel=self.channel)}]
        self._context_summary = ""
        working_memory.wm_clear()  # wipe short-term memory on reset
        self._session_progress = 0.0
        if hasattr(self, "cfg") and self.cfg is not None:
            self.cfg["session_progress"] = 0.0
            from config import save_config
            try:
                save_config(self.cfg)
            except Exception:
                pass


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

    def _pre_fetch_links(self, user_input: str):
        """Extract, fetch, and append safe link contents (Link-Understanding).
        Yields status events during execution.
        """
        import re
        import urllib.parse
        
        # 1. Extract safe URLs
        text_no_markdown = re.sub(r"\[[^\]]*\]\((https?://[^\s)]+)\)", " ", user_input)
        urls = re.findall(r"(https?://[^\s<>\"'\(\)]+)", text_no_markdown)
        
        seen = set()
        safe_urls = []
        from skills.web import is_safe_url
        for u in urls:
            u = u.rstrip(".,;:!?()[]{}'")
            if u in seen:
                continue
            seen.add(u)
            if is_safe_url(u):
                safe_urls.append(u)
                
        if not safe_urls:
            return

        # 2. Fetch the URLs
        from skills.web import fetch_url
        fetched_blocks = []
        for url in safe_urls[:2]:
            yield {"type": "status", "persona": "System", "message": f"Pre-fetching content from {url}..."}
            try:
                # Limit to 2000 characters to prevent context bloat
                content = fetch_url(url, max_chars=2000)
                if content and not content.startswith("ERROR:"):
                    block = f"\n\n=== PRE-FETCHED CONTENT FOR LINK: {url} ===\n{content}\n=========================================="
                    fetched_blocks.append(block)
                    yield {"type": "status", "persona": "System", "message": f"Successfully pre-fetched {url}"}
                else:
                    yield {"type": "status", "persona": "System", "message": f"Failed to pre-fetch {url}"}
            except Exception as e:
                yield {"type": "status", "persona": "System", "message": f"Error pre-fetching {url}: {e}"}
                continue
                
        if fetched_blocks:
            self._pre_fetched_context = "".join(fetched_blocks)
