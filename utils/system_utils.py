import sys
import os
import shutil

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

