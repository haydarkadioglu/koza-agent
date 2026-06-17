"""Setup wizard and provider command."""
import os
import sys

from cli.ui import (
    _C, _hr, _config_path, _select_menu, _prompt, _prompt_secret,
)
from cli.setup_constants import PROVIDERS, PROVIDER_MODELS, NEEDS_KEY, _OTHER
from cli.setup_helpers import (
    _validate_api_key, _playwright_gemini_login,
    _check_playwright_session,
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
        tw_sid    = cfg.get("messaging", {}).get("twilio", {}).get("account_sid", "")
        msg_status = ""
        if tg_token:
            msg_status = f"Telegram ✓" + (f"  chat:{tg_chat}" if tg_chat else "  (no chat_id)")
        if tw_sid:
            msg_status = (msg_status + "  " if msg_status else "") + "Twilio ✓"
        voice_cfg = cfg.get("voice", {})
        stt_cfg = voice_cfg.get("stt", {}) if isinstance(voice_cfg.get("stt"), dict) else {}
        tts_cfg = voice_cfg.get("tts", {}) if isinstance(voice_cfg.get("tts"), dict) else {}
        voice_status = ""
        if voice_cfg.get("enabled"):
            voice_status = (
                f"STT:{stt_cfg.get('provider', voice_cfg.get('stt_model', 'local_whisper'))} "
                f"TTS:{tts_cfg.get('provider', 'kokoro' if voice_cfg.get('use_kokoro') else 'system')}"
            )

        import platform
        from pathlib import Path
        is_windows = (platform.system() == "Windows")
        mingit_status = "✓ installed" if (Path.home() / ".Koza" / "git" / "bin" / "bash.exe").exists() else "not installed"

        sections = [
            f"Primary Provider    {_status(f'{cur_provider} / {cur_model}' if cur_provider else '')}",
            f"Fallback Provider   {_status(cur_fallback)}",
            f"Media (Image/Video) {_status(cur_media or cur_provider)}",
            f"Messaging Channels  {_status(msg_status)}",
            f"Twilio Setup        {_status('✓ configured' if tw_sid else '')}",
            f"Multi-host Sync     {_status(cfg.get('multi_host', {}).get('mode', 'single') if cfg.get('multi_host', {}).get('mode', 'single') != 'single' else '')}",
            f"Voice / STT / TTS   {_status(voice_status or 'disabled')}",
        ]
        if is_windows:
            sections.append(f"Portable MinGit     {_status(mingit_status)}")
        sections.append("Done — save & exit")

        try:
            default_idx = len(sections) - 1
            section = _select_menu("Configure section", sections, default_idx=default_idx)
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

        # ── Twilio Setup ──────────────────────────────────────────────────────
        elif section.startswith("Twilio"):
            _setup_twilio(cfg)

        # ── Multi-host Sync ───────────────────────────────────────────────────
        elif section.startswith("Multi"):
            from cli.commands import cmd_sync
            from config import load_config
            cmd_sync(["setup"])
            # Reload multi_host from disk — cmd_sync saves its own copy
            cfg["multi_host"] = load_config().get("multi_host", cfg.get("multi_host", {}))

        # ── Voice / STT / TTS ─────────────────────────────────────────────────
        elif section.startswith("Voice"):
            _setup_voice_mode(cfg)

        # ── Portable MinGit ───────────────────────────────────────────────────
        elif section.startswith("Portable MinGit"):
            _setup_portable_mingit()

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
    if cur_provider == "gemini":
        cur_provider_choice = "gemini api"
    else:
        cur_provider_choice = cur_provider
    default_idx = PROVIDERS.index(cur_provider_choice) if cur_provider_choice in PROVIDERS else 0
    try:
        provider_choice = _select_menu("Select provider", PROVIDERS, default_idx=default_idx)
    except (KeyboardInterrupt, EOFError):
        return

    if provider_choice == "gemini api":
        provider = "gemini"; gemini_auth = "api_key"
    else:
        provider = provider_choice; gemini_auth = "api_key"

    models = PROVIDER_MODELS.get(provider_choice, [""]) + [_OTHER]
    try:
        model_choice = _select_menu("Select model", models, default_idx=0)
    except (KeyboardInterrupt, EOFError):
        return
    model = _prompt("Enter model name") if model_choice == _OTHER else model_choice

    api_key = ""

    if provider_choice in NEEDS_KEY:
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
    if provider == "google-oauth":
        print(_C("\n  🔑 Starting Google OAuth login...\n", "cyan"))
        from providers.google_oauth_provider import run_oauth_login
        if run_oauth_login():
            print(_C("  ✅ Connected to Google account.\n", "green"))
        else:
            print(_C("  ⚠  Connection failed. Continuing setup.\n", "yellow"))
    if provider == "anthropic-oauth":
        print(_C("\n  🔑 Starting Anthropic OAuth login...\n", "cyan"))
        from providers.anthropic_oauth_provider import run_oauth_login
        if run_oauth_login():
            print(_C("  ✅ Connected to Anthropic account.\n", "green"))
        else:
            print(_C("  ⚠  Connection failed. Continuing setup.\n", "yellow"))
    openrouter_url = ""
    if provider == "openrouter":
        existing_url = cfg.get("providers", {}).get("openrouter", {}).get("base_url", "")
        custom = _prompt(
            "Custom base URL (Enter to use openrouter.ai default)",
            default=existing_url or "",
        )
        openrouter_url = custom.strip() or ""

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
    if provider == "openrouter" and openrouter_url:
        cfg.setdefault("providers", {}).setdefault("openrouter", {})["base_url"] = openrouter_url
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
    """Configure messaging channels (Telegram, Discord, Twilio, etc.)."""
    from config import save_config

    _hr("·", "grey")
    print(_C("  Messaging Channels", "cyan", "bold"))
    _hr("·", "grey")

    while True:
        tg_token = cfg.get("telegram_token", "") or cfg.get("providers", {}).get("telegram", {}).get("token", "")
        tg_chat  = cfg.get("messaging", {}).get("telegram", {}).get("chat_id", "")
        tg_label = f"✓ token set  chat_id:{tg_chat}" if tg_token else "not configured"

        tw_sid   = cfg.get("messaging", {}).get("twilio", {}).get("account_sid", "")
        tw_label = f"✓ SID:{tw_sid[:8]}…" if tw_sid else "not configured"

        try:
            channel = _select_menu(
                "Select channel to configure",
                [
                    f"Telegram          {_C(f'({tg_label})', 'teal' if tg_token else 'grey')}",
                    f"Twilio (SMS/WA)   {_C(f'({tw_label})', 'teal' if tw_sid else 'grey')}",
                    "Done — back to main menu",
                ],
                default_idx=2,
            )
        except (KeyboardInterrupt, EOFError):
            return

        if channel.startswith("Done"):
            break
        elif channel.startswith("Telegram"):
            _setup_telegram_channel(cfg)
            save_config(cfg)
        elif channel.startswith("Twilio"):
            _setup_twilio(cfg)
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
            from koza_daemon import start_services_background, get_daemon_port
            if get_daemon_port() is not None:
                print(_C("  ✓  Daemon already running.\n", "teal"))
            else:
                ok = start_services_background(cfg)
                if ok:
                    print(_C("  ✅ Telegram bot started in background.\n", "green"))
                else:
                    print(_C("  ⚠  Could not start. Run: koza\n", "yellow"))
        except Exception as e:
            print(_C(f"  ⚠  Could not start daemon: {e}\n  Run: koza\n", "yellow"))
    else:
        print(_C("  ✓  Telegram configured. Run: koza telegram start\n", "teal"))


def _setup_twilio(cfg: dict) -> None:
    """Interactive Twilio setup — Account credentials + SMS / WhatsApp / Voice."""
    from config import save_config

    _hr("·", "grey")
    print(_C("  Twilio Setup", "cyan", "bold"))
    print(_C("  SMS · WhatsApp · Voice calls · Phone Lookup\n", "grey"))
    print(_C("  Get your credentials from: https://console.twilio.com\n", "grey"))
    _hr("·", "grey")

    tw_cfg = cfg.setdefault("messaging", {}).setdefault("twilio", {})

    cur_sid = tw_cfg.get("account_sid", "")
    if cur_sid:
        try:
            action = _select_menu(
                f"Twilio already configured (SID: {cur_sid[:8]}…)",
                ["Keep existing credentials", "Update credentials", "Remove Twilio integration"],
                default_idx=0,
            )
        except (KeyboardInterrupt, EOFError):
            return
        if action.startswith("Remove"):
            cfg["messaging"].pop("twilio", None)
            print(_C("  ✓  Twilio integration removed.\n", "green"))
            save_config(cfg)
            return
        elif action.startswith("Update"):
            cur_sid = ""

    if not cur_sid:
        print(_C("  ── Account Credentials ──────────────────────────────────────\n", "grey"))
        try:
            sid = _prompt("  Account SID (ACxxxxx): ").strip()
            if not sid:
                print(_C("  Cancelled.\n", "grey"))
                return
            auth = _prompt_secret("  Auth Token: ").strip()
            if not auth:
                print(_C("  Cancelled.\n", "grey"))
                return
        except (KeyboardInterrupt, EOFError):
            return
        tw_cfg["account_sid"] = sid
        tw_cfg["auth_token"]  = auth
        cur_sid = sid

    # ── SMS From number ───────────────────────────────────────────────────────
    print(_C("  ── SMS / Voice Caller ID ────────────────────────────────────\n", "grey"))
    cur_from = tw_cfg.get("from_number", "")
    try:
        from_num = _prompt(f"  Twilio phone number for SMS/Voice (E.164) [{cur_from or 'e.g. +14155551234'}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        from_num = ""
    if from_num:
        tw_cfg["from_number"] = from_num
    elif not cur_from:
        print(_C("  ⚠  No SMS/Voice number set. SMS and calls won't work without it.\n", "yellow"))

    # ── WhatsApp ──────────────────────────────────────────────────────────────
    print(_C("  ── WhatsApp (optional) ──────────────────────────────────────\n", "grey"))
    print(_C("  Leave blank to skip WhatsApp. Use Sandbox or approved sender.\n", "grey"))
    cur_wa_from = tw_cfg.get("wa_from", "")
    cur_wa_to   = tw_cfg.get("wa_to",   "")
    try:
        wa_from = _prompt(f"  WhatsApp sender number [{cur_wa_from or 'e.g. +14155238886'}]: ").strip()
        wa_to   = _prompt(f"  Default WhatsApp recipient [{cur_wa_to or 'optional'}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        wa_from = wa_to = ""
    if wa_from:
        tw_cfg["wa_from"] = wa_from
    if wa_to:
        tw_cfg["wa_to"] = wa_to

    save_config(cfg)
    print(_C("  ✓  Twilio credentials saved.\n", "green"))

    # ── Test connection ───────────────────────────────────────────────────────
    try:
        test_choice = _select_menu(
            "Test Twilio connection now?",
            ["Yes — verify account credentials", "No — skip test"],
            default_idx=0,
        )
    except (KeyboardInterrupt, EOFError):
        test_choice = "No"

    if test_choice.startswith("Yes"):
        print(_C("  Connecting to Twilio API…\n", "grey"))
        try:
            from twilio.rest import Client as _TwClient
            c = _TwClient(tw_cfg["account_sid"], tw_cfg["auth_token"])
            acc = c.api.accounts(tw_cfg["account_sid"]).fetch()
            bal = c.api.accounts(tw_cfg["account_sid"]).balance.fetch()
            print(_C(f"  ✓  Account: {acc.friendly_name}  ({acc.status})", "green"))
            print(_C(f"  ✓  Balance: {bal.balance} {bal.currency}\n", "green"))
        except ImportError:
            print(_C("  ⚠  twilio package not installed. Run: pip install twilio\n", "yellow"))
        except Exception as e:
            print(_C(f"  ✗  Connection failed: {e}\n", "red"))

    # ── Optional: send a test SMS ─────────────────────────────────────────────
    sms_from = tw_cfg.get("from_number", "")
    if sms_from:
        try:
            sms_choice = _select_menu(
                "Send a test SMS?",
                ["Yes — send test SMS", "No — skip"],
                default_idx=1,
            )
        except (KeyboardInterrupt, EOFError):
            sms_choice = "No"

        if sms_choice.startswith("Yes"):
            try:
                test_to = _prompt("  Send test SMS to (E.164, e.g. +905551234567): ").strip()
            except (KeyboardInterrupt, EOFError):
                test_to = ""
            if test_to:
                try:
                    from twilio.rest import Client as _TwClient
                    c = _TwClient(tw_cfg["account_sid"], tw_cfg["auth_token"])
                    m = c.messages.create(body="Koza Agent — Twilio test ✅", from_=sms_from, to=test_to)
                    print(_C(f"  ✅ SMS sent! SID: {m.sid}\n", "green"))
                except Exception as e:
                    print(_C(f"  ✗  SMS failed: {e}\n", "red"))


def _setup_voice_mode(cfg: dict) -> None:
    """Configure voice mode."""
    from cli.voice_cmd import configure_voice

    configure_voice(cfg, save=False)


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
                cookie_ok = bool(vals.get("cookie_1psid", ""))
                cred = _C("cookie ✓", "green") if cookie_ok else _C("cookie ✗", "red")
            elif auth == "adc":
                cred = _C("cli/adc", "teal")
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
        elif auth == "adc":
            cred = "cli/adc"
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


def _setup_portable_mingit() -> None:
    """Prompt, download and extract Portable MinGit for Windows."""
    import urllib.request
    import zipfile
    from pathlib import Path
    
    _hr("·", "grey")
    print(_C("  Portable MinGit Setup (Windows Command Isolation)", "cyan", "bold"))
    print(_C("  Koza can download MinGit to run shell commands in a POSIX bash shell.", "grey"))
    print(_C("  This provides shell environment consistency across platforms.\n", "grey"))
    
    target_dir = Path.home() / ".Koza" / "git"
    bash_exe = target_dir / "bin" / "bash.exe"
    
    if bash_exe.exists():
        print(_C(f"  ✓  MinGit is already installed at: {target_dir}\n", "green"))
        reinstall = _prompt("Do you want to reinstall/update it?", default="n", choices=["y", "n"])
        if reinstall.lower() != "y":
            return
            
    confirm = _prompt("Download and extract Portable MinGit (~45MB)?", default="y", choices=["y", "n"])
    if confirm.lower() != "y":
        return
        
    url = "https://github.com/git-for-windows/git/releases/download/v2.44.0.windows.1/MinGit-2.44.0-64-bit.zip"
    zip_path = Path.home() / ".Koza" / "mingit.zip"
    
    print(_C(f"  Downloading MinGit from Git-for-Windows releases…\n  URL: {url}", "grey"))
    try:
        # Download with simple progress updates
        def progress_hook(count, block_size, total_size):
            percent = int(count * block_size * 100 / total_size)
            percent = min(100, percent)
            sys.stdout.write(f"\r  Progress: {percent}%")
            sys.stdout.flush()
            
        urllib.request.urlretrieve(url, str(zip_path), reporthook=progress_hook)
        print(_C("\n  ✓  Download complete.", "green"))
        
        print(_C(f"  Extracting to: {target_dir}…", "grey"))
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(target_dir)
            
        if zip_path.exists():
            zip_path.unlink()
            
        if bash_exe.exists():
            print(_C(f"  ✅  Portable MinGit successfully installed!\n", "green"))
        else:
            print(_C(f"  ✗  Extraction failed: bin/bash.exe not found under {target_dir}.\n", "red"))
    except Exception as e:
        print(_C(f"  ✗  Installation failed: {e}\n", "red"))
