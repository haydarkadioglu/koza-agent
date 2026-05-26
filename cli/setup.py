"""Setup wizard and provider command."""
import os
import sys

from cli.ui import (
    _C, _hr, _config_path, _select_menu, _prompt, _prompt_secret,
)
from cli.setup_constants import PROVIDERS, PROVIDER_MODELS, NEEDS_KEY, _OTHER
from cli.setup_helpers import (
    _validate_api_key, _playwright_gemini_login,
    _check_playwright_session, _reload_and_patch_media,
)


def cmd_setup(args: list) -> None:
    """Interactive plain-terminal setup wizard."""
    from config import save_config, default_config, config_exists, load_config

    _hr()
    print(_C("\n  ✦  K O Z A   A G E N T  ·  Setup Wizard\n", "bold", "yellow"))

    # ── Load or init config ───────────────────────────────────────────────────
    if config_exists():
        cfg = load_config()
    else:
        cfg = default_config()

    def _status(val):
        return _C(f"({val})", "teal") if val else _C("(not set)", "grey")

    # Track what changed so we can save once at the end
    provider        = cfg.get("provider", "")
    model           = cfg.get("model", "")
    gemini_auth     = cfg.get("providers", {}).get("gemini", {}).get("auth", "api_key")

    print(_C("  Select sections to configure. Choose 'Done' when finished.\n", "grey"))

    while True:
        # Refresh status labels before each menu render
        cur_provider = cfg.get("provider", "")
        cur_model    = cfg.get("model", "")
        cur_media    = cfg.get("media_provider", "")
        cur_fallback = cfg.get("fallback_provider", "")
        # Messaging status label
        tg_token  = cfg.get("telegram_token", "") or cfg.get("providers", {}).get("telegram", {}).get("token", "")
        tg_chat   = cfg.get("messaging", {}).get("telegram", {}).get("chat_id", "")
        msg_status = ""
        if tg_token:
            msg_status = f"Telegram ✓" + (f"  chat:{tg_chat}" if tg_chat else "  (no chat_id)")

        sections = [
            f"Primary Provider    {_status(f'{cur_provider} / {cur_model}' if cur_provider else '')}",
            f"Fallback Provider   {_status(cur_fallback)}",
            f"Media (Image/Video) {_status(cur_media or cur_provider)}",
            f"Messaging Channels  {_status(msg_status)}",
            f"Multi-host Sync     {_status(cfg.get('multi_host', {}).get('mode', 'single') if cfg.get('multi_host', {}).get('mode', 'single') != 'single' else '')}",
            f"Voice Mode          {_status('enabled' if cfg.get('voice', {}).get('enabled') else 'disabled')}",
            "Done — save & exit",
        ]
        try:
            section = _select_menu("Configure section", sections, default_idx=6)
        except (KeyboardInterrupt, EOFError):
            print(_C("\n  Cancelled.\n", "grey"))
            return

        # ── Done ──────────────────────────────────────────────────────────────
        if section.startswith("Done"):
            break

        # ── Primary Provider ──────────────────────────────────────────────────
        elif section.startswith("Primary"):
            _setup_primary_provider(cfg)

        # ── Fallback Provider ─────────────────────────────────────────────────
        elif section.startswith("Fallback"):
            _setup_fallback_provider(cfg)

        # ── Media Provider ────────────────────────────────────────────────────
        elif section.startswith("Media"):
            _setup_media_provider(cfg)

        # ── Messaging Channels ────────────────────────────────────────────────
        elif section.startswith("Messaging"):
            _setup_messaging(cfg)

        # ── Multi-host Sync ───────────────────────────────────────────────────
        elif section.startswith("Multi"):
            from cli.commands import cmd_sync
            from config import load_config
            cmd_sync(["setup"])
            # Reload multi_host from disk — cmd_sync saves its own copy
            cfg["multi_host"] = load_config().get("multi_host", cfg.get("multi_host", {}))

        # ── Voice Mode ────────────────────────────────────────────────────────
        elif section.startswith("Voice"):
            _setup_voice_mode(cfg)

    # ── Save & exit ───────────────────────────────────────────────────────────
    save_config(cfg)
    _hr()
    print(_C(f"\n  ✅  Config saved → {_config_path()}\n", "green"))
    _hr()


# ── Section handlers ──────────────────────────────────────────────────────────

def _setup_primary_provider(cfg: dict) -> None:
    """Configure the primary LLM provider."""
    from config import save_config

    _hr("·", "grey")
    print(_C("  Primary Provider", "cyan", "bold"))
    _hr("·", "grey")

    cur_provider = cfg.get("provider", "")
    default_idx = PROVIDERS.index(cur_provider) if cur_provider in PROVIDERS else 0
    try:
        provider_choice = _select_menu("Select provider", PROVIDERS, default_idx=default_idx)
    except (KeyboardInterrupt, EOFError):
        return

    if provider_choice == "gemini api":
        provider = "gemini"; gemini_auth = "api_key"
    elif provider_choice == "gemini cookie":
        provider = "gemini"; gemini_auth = "cookie"
    else:
        provider = provider_choice; gemini_auth = "api_key"

    models = PROVIDER_MODELS.get(provider_choice, [""]) + [_OTHER]
    try:
        model_choice = _select_menu("Select model", models, default_idx=0)
    except (KeyboardInterrupt, EOFError):
        return
    model = _prompt("Enter model name") if model_choice == _OTHER else model_choice

    api_key = ""

    if provider == "gemini" and gemini_auth == "cookie":
        session_ok = _check_playwright_session()
        if session_ok:
            print(_C("  ✓  Gemini browser session found.\n", "green"))
            try:
                cookie_action = _select_menu(
                    "Browser session exists",
                    ["Keep current session",
                     "Re-login (open browser again)",
                     "Enter cookies manually (paste __Secure-1PSID)"],
                    default_idx=0,
                )
            except (KeyboardInterrupt, EOFError):
                cookie_action = "Keep"
            if "Re-login" in cookie_action:
                _playwright_gemini_login()
            elif "manually" in cookie_action:
                print(_C("\n  Get cookies from browser DevTools → Application → Cookies → .google.com\n", "grey"))
                psid = _prompt_secret("__Secure-1PSID")
                psidts = _prompt("__Secure-1PSIDTS (optional, Enter to skip)", default="")
                if psid:
                    cfg.setdefault("providers", {}).setdefault("gemini", {})["cookie_1psid"] = psid
                    if psidts:
                        cfg["providers"]["gemini"]["cookie_1psidts"] = psidts
                    cfg["providers"]["gemini"]["auth"] = "cookie"
                    print(_C("  ✓  Gemini cookies updated.\n", "green"))
                else:
                    print(_C("  ⚠  No cookie entered.\n", "yellow"))
        else:
            print(_C("  ℹ  No Gemini browser session found.\n", "grey"))
            try:
                do_login = _select_menu(
                    "Set up Gemini cookie auth",
                    ["Browser login (Playwright — automatic)",
                     "Enter cookies manually (paste __Secure-1PSID)",
                     "Skip — set up later"],
                    default_idx=0,
                )
            except (KeyboardInterrupt, EOFError):
                do_login = "Skip"
            if "Browser" in do_login:
                _playwright_gemini_login()
            elif "manually" in do_login:
                print(_C("\n  Get cookies from browser DevTools → Application → Cookies → .google.com\n", "grey"))
                psid = _prompt_secret("__Secure-1PSID")
                psidts = _prompt("__Secure-1PSIDTS (optional, Enter to skip)", default="")
                if psid:
                    cfg.setdefault("providers", {}).setdefault("gemini", {})["cookie_1psid"] = psid
                    if psidts:
                        cfg["providers"]["gemini"]["cookie_1psidts"] = psidts
                    cfg["providers"]["gemini"]["auth"] = "cookie"
                    print(_C("  ✓  Gemini cookies saved.\n", "green"))
                else:
                    print(_C("  ⚠  No cookie entered.\n", "yellow"))
    elif provider_choice in NEEDS_KEY:
        existing = cfg.get("providers", {}).get(provider, {}).get("api_key", "")
        if existing:
            print(_C(f"  ✓  Existing key found for {provider_choice}.", "green"))
            reuse = _prompt("Keep existing key?", default="y", choices=["y", "n"])
            if reuse.lower() == "n":
                api_key = _prompt_secret(f"New API key for {provider_choice}")
            else:
                api_key = existing
        else:
            api_key = _prompt_secret(f"API key for {provider_choice}")

        # Validate the API key
        if api_key and api_key != existing:
            valid, msg = _validate_api_key(provider, api_key, model)
            if valid:
                print(_C(f"  ✓  API key verified ({msg})", "green"))
            else:
                print(_C(f"  ✗  API key failed: {msg}", "red"))
                retry = _prompt("Try again?", default="y", choices=["y", "n"])
                if retry.lower() == "y":
                    return  # user will re-enter Primary Provider section
                else:
                    api_key = ""

    ollama_url = "http://localhost:11434"
    if provider == "ollama":
        ollama_url = _prompt("Ollama base URL", default="http://localhost:11434")
    antigravity_url = "http://localhost:5188"
    if provider == "antigravity manager":
        antigravity_url = _prompt("Antigravity Tools LS URL", default="http://localhost:5188")

    # Patch cfg
    cfg["provider"] = provider
    cfg["model"]    = model
    if provider == "gemini":
        cfg.setdefault("providers", {}).setdefault("gemini", {})["auth"] = gemini_auth
        if gemini_auth == "api_key" and api_key:
            cfg["providers"]["gemini"]["api_key"] = api_key
    elif api_key:
        cfg.setdefault("providers", {}).setdefault(provider, {})["api_key"] = api_key
    if provider == "ollama":
        cfg.setdefault("providers", {}).setdefault("ollama", {})["base_url"] = ollama_url
    if provider == "antigravity manager":
        cfg.setdefault("providers", {}).setdefault("antigravity manager", {})["base_url"] = antigravity_url
    print(_C(f"\n  ✓  Primary provider set to {provider} / {model}\n", "green"))


def _setup_fallback_provider(cfg: dict) -> None:
    """Configure the fallback LLM provider."""
    _hr("·", "grey")
    print(_C("  Fallback Provider", "cyan", "bold"))
    print(_C("  Used automatically if primary provider fails.\n", "grey"))
    _hr("·", "grey")

    enable = _prompt("Enable fallback provider?", default="n", choices=["y", "n"])
    if enable.lower() != "y":
        cfg.pop("fallback_provider", None)
        cfg.pop("fallback_model", None)
        print(_C("  ✓  Fallback disabled.\n", "green"))
        return

    cur_p = cfg.get("provider", "")
    remaining = [p for p in PROVIDERS if p != cur_p]
    try:
        fb_choice = _select_menu("Select fallback provider", remaining, default_idx=0)
    except (KeyboardInterrupt, EOFError):
        return
    fb_prov = "gemini" if fb_choice.startswith("gemini") else fb_choice
    fb_models = PROVIDER_MODELS.get(fb_choice, [""]) + [_OTHER]
    try:
        fb_model_choice = _select_menu("Select fallback model", fb_models, default_idx=0)
    except (KeyboardInterrupt, EOFError):
        return
    fb_model = _prompt("Enter fallback model name") if fb_model_choice == _OTHER else fb_model_choice

    fb_key = ""
    if fb_choice in NEEDS_KEY:
        existing = cfg.get("providers", {}).get(fb_prov, {}).get("api_key", "")
        if existing:
            print(_C(f"  ✓  Existing key found for {fb_choice}.", "green"))
        else:
            fb_key = _prompt_secret(f"API key for {fb_choice} (optional if already set)")
            if fb_key:
                valid, msg = _validate_api_key(fb_prov, fb_key, fb_model)
                if valid:
                    print(_C(f"  ✓  API key verified ({msg})", "green"))
                else:
                    print(_C(f"  ✗  API key failed: {msg}", "red"))
                    print(_C("  Fallback key not saved.", "grey"))
                    fb_key = ""

    cfg["fallback_provider"] = fb_prov
    cfg["fallback_model"]    = fb_model
    if fb_key:
        cfg.setdefault("providers", {}).setdefault(fb_prov, {})["api_key"] = fb_key
    print(_C(f"\n  ✓  Fallback set to {fb_prov} / {fb_model}\n", "green"))


def _setup_media_provider(cfg: dict) -> None:
    """Configure the media generation provider."""
    from config import save_config

    _hr("·", "grey")
    print(_C("  Media Generation Provider", "cyan", "bold"))
    print(_C("  Used for image (Imagen/DALL-E) and video (Veo) generation.", "grey"))
    print(_C("  Gemini Pro account + browser session = Imagen Nano + Veo 2 (free).\n", "grey"))
    _hr("·", "grey")

    cur_p = cfg.get("provider", "")
    cur_media_cfg = cfg.get("media_provider", "")
    session_ok = _check_playwright_session()
    status_txt = f"currently: {cur_media_cfg}" if cur_media_cfg else f"follows main ({cur_p})"
    print(_C(f"  {status_txt}\n", "teal"))

    try:
        media_action = _select_menu(
            "Configure media provider",
            ["Use same as main chat provider",
             f"Gemini Browser Session  (Pro — Imagen Nano + Veo 2 free)  {('✓ ready' if session_ok else '⚠ no session')}",
             "Gemini API     (Imagen 3)",
             "OpenAI         (DALL-E 3)",
             "Skip — no changes"],
            default_idx=0,
        )
    except (KeyboardInterrupt, EOFError):
        return

    if "Skip" in media_action:
        return
    elif "same as main" in media_action:
        cfg.pop("media_provider", None)
        cfg.get("providers", {}).pop("gemini_media", None)
        print(_C("  ✓  Media will use main provider.\n", "green"))
    else:
        if "Browser Session" in media_action:
            media_prov = "gemini"; media_auth = "playwright"
        elif "Gemini API" in media_action:
            media_prov = "gemini"; media_auth = "api_key"
        else:
            media_prov = "openai"; media_auth = "api_key"

        m_key = ""
        if media_auth == "playwright":
            if not session_ok:
                print(_C("\n  No browser session found. Opening browser for login…\n", "grey"))
                _playwright_gemini_login()
            else:
                print(_C("  ✓  Browser session already set up.\n", "green"))
                try:
                    re_login = _select_menu(
                        "Browser session exists",
                        ["Keep existing session", "Re-login (open browser again)"],
                        default_idx=0,
                    )
                except (KeyboardInterrupt, EOFError):
                    re_login = "Keep"
                if "Re-login" in re_login:
                    _playwright_gemini_login()
        else:
            existing = cfg.get("providers", {}).get(media_prov, {}).get("api_key", "")
            if existing:
                print(_C(f"  ✓  Using existing {media_prov} API key.\n", "green"))
                m_key = existing
            else:
                m_key = _prompt_secret(f"API key for {media_prov}")

        cfg["media_provider"] = media_prov
        mp = cfg.setdefault("providers", {}).setdefault(
            "gemini_media" if media_prov == "gemini" else f"{media_prov}_media", {}
        )
        mp["auth"] = media_auth
        mp.pop("cookie_1psid", None)
        mp.pop("cookie_1psidts", None)
        if m_key:
            mp["api_key"] = m_key
        save_config(cfg)
        display = media_action.split("(")[0].strip()
        print(_C(f"\n  ✓  Media provider set to {display}\n", "green"))


def _setup_messaging(cfg: dict) -> None:
    """Configure messaging channels (Telegram, Discord, etc.)."""
    from config import save_config

    _hr("·", "grey")
    print(_C("  Messaging Channels", "cyan", "bold"))
    _hr("·", "grey")

    while True:
        tg_token = cfg.get("telegram_token", "") or cfg.get("providers", {}).get("telegram", {}).get("token", "")
        tg_chat  = cfg.get("messaging", {}).get("telegram", {}).get("chat_id", "")
        tg_label = f"✓ token set  chat_id:{tg_chat}" if tg_token else "not configured"

        try:
            channel = _select_menu(
                "Select channel to configure",
                [
                    f"Telegram   {_C(f'({tg_label})', 'teal' if tg_token else 'grey')}",
                    "Done — back to main menu",
                ],
                default_idx=1,
            )
        except (KeyboardInterrupt, EOFError):
            return

        if channel.startswith("Done"):
            break
        elif channel.startswith("Telegram"):
            _setup_telegram_channel(cfg)
            save_config(cfg)


def _setup_telegram_channel(cfg: dict) -> None:
    """Interactive Telegram bot setup."""
    from config import save_config

    _hr("·", "grey")
    print(_C("  Telegram Bot Setup", "cyan", "bold"))
    print(_C("  Create a bot via @BotFather on Telegram and paste the token below.\n", "grey"))

    cur_token = cfg.get("telegram_token", "")

    # ── Token ─────────────────────────────────────────────────────────────────
    if cur_token:
        try:
            action = _select_menu(
                f"Token already set ({cur_token[:12]}…)",
                ["Keep existing token", "Replace token", "Remove Telegram integration"],
                default_idx=0,
            )
        except (KeyboardInterrupt, EOFError):
            return
        if action.startswith("Remove"):
            cfg.pop("telegram_token", None)
            cfg.get("messaging", {}).get("telegram", {}).pop("chat_id", None)
            print(_C("  ✓  Telegram integration removed.\n", "green"))
            return
        elif action.startswith("Replace"):
            cur_token = ""

    if not cur_token:
        try:
            token = _prompt_secret("  Bot token (from @BotFather): ").strip()
        except (KeyboardInterrupt, EOFError):
            return
        if not token:
            print(_C("  Cancelled — token not changed.\n", "grey"))
            return
        cfg["telegram_token"] = token
        cur_token = token
        print(_C("  ✓  Token saved.\n", "green"))

    # ── Verify token & get bot info ───────────────────────────────────────────
    print(_C("  Verifying token with Telegram API…", "grey"))
    try:
        import requests as _req
        r = _req.get(f"https://api.telegram.org/bot{cur_token}/getMe", timeout=8)
        if r.ok and r.json().get("ok"):
            bot = r.json()["result"]
            print(_C(f"  ✓  Bot: @{bot.get('username', '?')}  ({bot.get('first_name', '')})\n", "green"))
        else:
            print(_C(f"  ⚠  Token invalid: {r.text[:120]}\n", "yellow"))
    except Exception as e:
        print(_C(f"  ⚠  Could not verify: {e}\n", "yellow"))

    # ── Chat ID ───────────────────────────────────────────────────────────────
    cur_chat = cfg.get("messaging", {}).get("telegram", {}).get("chat_id", "")
    print(_C("  To get your Chat ID: send any message to your bot on Telegram,", "grey"))
    print(_C("  then press Enter and we'll fetch it automatically — or enter it manually.\n", "grey"))

    try:
        chat_input = _prompt(f"  Chat ID [{cur_chat or 'auto-detect'}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return

    if not chat_input:
        # Auto-detect from getUpdates
        try:
            import requests as _req
            r = _req.get(f"https://api.telegram.org/bot{cur_token}/getUpdates", timeout=8)
            if r.ok:
                updates = r.json().get("result", [])
                if updates:
                    chat_input = str(updates[-1]["message"]["chat"]["id"])
                    print(_C(f"  ✓  Auto-detected Chat ID: {chat_input}\n", "green"))
                else:
                    print(_C("  ⚠  No messages found. Send a message to your bot first, then re-run setup.\n", "yellow"))
        except Exception as e:
            print(_C(f"  ⚠  Could not auto-detect: {e}\n", "yellow"))

    if chat_input:
        cfg.setdefault("messaging", {}).setdefault("telegram", {})["chat_id"] = chat_input

    # ── Auto-start option ─────────────────────────────────────────────────────
    try:
        start_now = _select_menu(
            "Start Telegram bot in background now?",
            ["Yes — start daemon now", "No — I'll start it manually"],
            default_idx=0,
        )
    except (KeyboardInterrupt, EOFError):
        return

    if start_now.startswith("Yes"):
        save_config(cfg)
        print(_C("  Starting Telegram daemon…\n", "grey"))
        try:
            from skills.telegram_daemon import start_telegram_daemon
            result = start_telegram_daemon()
            print(_C(f"  {result}\n", "green"))
        except Exception as e:
            print(_C(f"  ⚠  Could not start daemon: {e}\n  Run: koza telegram start\n", "yellow"))
    else:
        print(_C("  ✓  Telegram configured. Run: koza telegram start\n", "teal"))


def _setup_voice_mode(cfg: dict) -> None:
    """Configure voice mode."""
    from config import load_config

    _hr("·", "grey")
    print(_C("  Voice Mode", "cyan", "bold"))
    _hr("·", "grey")

    voice_enabled = cfg.get("voice", {}).get("enabled", False)
    if voice_enabled:
        try:
            voice_action = _select_menu(
                "Voice mode is currently enabled",
                ["Keep enabled / Reconfigure devices",
                 "Disable voice mode",
                 "Skip — no changes"],
                default_idx=2,
            )
        except (KeyboardInterrupt, EOFError):
            return
        if "Disable" in voice_action:
            cfg.setdefault("voice", {})["enabled"] = False
            print(_C("  ✓  Voice mode disabled.\n", "green"))
        elif "Skip" in voice_action:
            return
        else:
            from cli.voice_cmd import _do_setup
            _do_setup([])
            cfg.update(load_config())
    else:
        try:
            voice_action = _select_menu(
                "Voice mode is currently disabled",
                ["Enable & configure voice mode",
                 "Skip — no changes"],
                default_idx=1,
            )
        except (KeyboardInterrupt, EOFError):
            return
        if "Enable" in voice_action:
            from cli.voice_cmd import _do_setup
            _do_setup([])
            cfg.update(load_config())


# ── Provider command ──────────────────────────────────────────────────────────

def cmd_provider(args: list) -> None:
    """Show and switch the active provider/model.

    Usage:
      koza provider          — interactive menu to switch
      koza provider list     — list configured providers
      koza provider use NAME — set provider by name (e.g. openai, deepseek)
    """
    from config import load_config, save_config, config_exists
    if not config_exists():
        print(_C("  ✗  No config found. Run:  koza setup", "red"))
        return

    cfg = load_config()
    active_provider = cfg.get("provider", "")
    active_model    = cfg.get("model", "")

    # ── koza provider list ────────────────────────────────────────────────────
    if args and args[0] == "list":
        _hr("·", "grey")
        print(_C("  Configured Providers", "cyan", "bold"))
        _hr("·", "grey")
        providers_cfg = cfg.get("providers", {})
        for name, vals in providers_cfg.items():
            is_active = (name == active_provider)
            key = vals.get("api_key") or vals.get("token", "")
            auth = vals.get("auth", "api_key")
            if auth == "playwright":
                session_ok = _check_playwright_session()
                cred = _C("browser ✓", "green") if session_ok else _C("browser ✗", "red")
            elif auth == "cookie":
                cred = _C("cookie ✓", "green") if key else _C("cookie ✗", "red")
            else:
                cred = _C("key ✓", "green") if key else _C("—", "grey")
            marker = _C("◉ active", "teal") if is_active else _C("○", "grey")
            model_str = f"  {_C(active_model, 'white')}" if is_active else ""
            print(f"  {marker}  {_C(f'{name:<14}', 'cyan')}  {cred}{model_str}")
        print()
        print(f"  {_C('Switch with:', 'grey')}  koza provider use <name>")
        print()
        return

    # ── koza provider use NAME ────────────────────────────────────────────────
    if args and args[0] == "use":
        target = args[1].lower() if len(args) > 1 else ""
        if not target:
            print(_C("  ⚠  Usage: koza provider use <name>", "yellow"))
            return
        providers_cfg = cfg.get("providers", {})
        match = next((k for k in providers_cfg if k == target or k.startswith(target)), None)
        if not match:
            print(_C(f"  ✗  Provider '{target}' not configured.", "red"))
            print(_C(f"  Configured: {', '.join(providers_cfg.keys())}", "grey"))
            return
        models = PROVIDER_MODELS.get(match, PROVIDER_MODELS.get(target, [""]))
        if models:
            print(_C(f"\n  Switching to {_C(match, 'cyan')} — pick a model:\n", "white"))
            models_with_other = models + [_OTHER]
            try:
                model_choice = _select_menu("Select model", models_with_other, default_idx=0)
            except (KeyboardInterrupt, EOFError):
                return
            new_model = _prompt("Enter model name") if model_choice == _OTHER else model_choice
        else:
            new_model = active_model
        cfg["provider"] = match
        cfg["model"]    = new_model
        save_config(cfg)
        print(_C(f"\n  ✅  Active provider → {match}  /  {new_model}\n", "green"))
        return

    # ── koza provider  (interactive menu) ────────────────────────────────────
    providers_cfg = cfg.get("providers", {})
    configured = list(providers_cfg.keys())
    if not configured:
        print(_C("  ✗  No providers configured. Run:  koza setup", "red"))
        return

    _hr("·", "grey")
    print(_C("  Switch Active Provider", "cyan", "bold"))
    _hr("·", "grey")
    print(f"  Current:  {_C(active_provider, 'teal')}  /  {_C(active_model, 'white')}\n")

    labels = []
    for name in configured:
        vals = providers_cfg[name]
        auth = vals.get("auth", "api_key")
        key  = vals.get("api_key") or vals.get("token", "")
        if auth == "playwright":
            cred = "browser"
        elif auth == "cookie":
            cred = "cookie"
        elif key:
            cred = "key ✓"
        elif name == "ollama":
            cred = "local"
        else:
            cred = "no key"
        marker = "◉ " if name == active_provider else "  "
        labels.append(f"{marker}{name}  ({cred})")

    try:
        chosen_label = _select_menu("Select provider", labels,
                                    default_idx=configured.index(active_provider) if active_provider in configured else 0)
    except (KeyboardInterrupt, EOFError):
        return

    chosen = configured[labels.index(chosen_label)]
    models = PROVIDER_MODELS.get(chosen, [""]) + [_OTHER]
    try:
        model_choice = _select_menu("Select model", models, default_idx=0)
    except (KeyboardInterrupt, EOFError):
        return
    new_model = _prompt("Enter model name") if model_choice == _OTHER else model_choice

    cfg["provider"] = chosen
    cfg["model"]    = new_model
    save_config(cfg)
    print(_C(f"\n  ✅  Active provider → {chosen}  /  {new_model}\n", "green"))
