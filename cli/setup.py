"""Setup wizard and provider command."""
import os
import sys

from cli.ui import (
    _C, _hr, _config_path, _select_menu, _prompt, _prompt_secret,
)

PROVIDERS = ["ollama", "openai", "anthropic", "deepseek", "kimi", "minimax", "zai", "gemini api", "gemini cookie", "antigravity manager", "github"]
PROVIDER_MODELS = {
    "openai":              ["gpt-4.1", "gpt-4o", "gpt-4o-mini"],
    "anthropic":           ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
    "deepseek":            ["deepseek-chat", "deepseek-reasoner", "deepseek-coder-v2"],
    "kimi":                ["kimi-k2-0711-preview", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-latest"],
    "minimax":             ["MiniMax-M1", "MiniMax-Text-01", "abab6.5s-chat"],
    "zai":                 ["glm-z1-air", "glm-z1-flash", "glm-4-plus", "glm-4-air", "glm-4-flash"],
    "gemini api":          ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-flash-latest"],
    "gemini cookie":       ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash", "gemini-3.1-pro", "gemini-3-pro", "gemini-3-flash-thinking", "gemini-3-pro-plus", "gemini-3-flash-advanced", "gemini-3-pro-advanced"],
    "gemini":              ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-flash-latest"],
    "antigravity manager": ["gemini-3.1-pro-high", "gemini-3-flash-agent", "claude-sonnet-4-6", "claude-opus-4-6-thinking", "gpt-oss-120b-medium"],
    "ollama":              ["llama3.2", "mistral", "codellama"],
    "github":              ["gpt-4.1", "gpt-4o", "Meta-Llama-3.1-70B-Instruct"],
}
NEEDS_KEY = {"openai", "anthropic", "deepseek", "gemini api", "gemini", "github", "kimi", "minimax", "zai"}
_OTHER = "other — enter manually"


def _playwright_gemini_login() -> bool:
    """Open a persistent Playwright browser session for Gemini login.

    Returns True if the user confirmed login, False otherwise.
    """
    import os
    profile_dir = os.path.join(os.path.expanduser("~"), ".koza", "gemini_browser")
    os.makedirs(profile_dir, exist_ok=True)

    print(_C("\n  Opening browser — log in to your Google account.\n", "grey"))
    print(_C(f"  Session will be saved to: {profile_dir}\n", "grey"))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(_C("  ⚠  playwright not installed.", "yellow"))
        print(_C("  Run: pip install playwright && playwright install chromium\n", "yellow"))
        return False

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto("https://gemini.google.com/", timeout=30000)

            print(_C("  ● Log in to your Google account in the browser.", "cyan"))
            print(_C("  ● When you see the Gemini chat screen, press Enter here.\n", "grey"))
            try:
                input(_C("  Press Enter when logged in › ", "yellow"))
            except (EOFError, KeyboardInterrupt):
                browser.close()
                return False

            browser.close()
        print(_C("  ✓  Browser session saved!\n", "green"))
        return True
    except Exception as e:
        print(_C(f"  ⚠  Browser error: {e}\n", "yellow"))
        return False


def _check_playwright_session() -> bool:
    """Return True if a Gemini browser session profile already exists."""
    import os
    profile_dir = os.path.join(os.path.expanduser("~"), ".koza", "gemini_browser")
    # Check if the profile directory has any data (Chromium creates Default/Preferences on first launch)
    prefs = os.path.join(profile_dir, "Default", "Preferences")
    return os.path.isfile(prefs)


def _reload_and_patch_media(provider: str, auth: str, api_key: str = ""):
    """Patch the saved config with media_provider settings and return updated cfg."""
    from config import load_config, save_config
    cfg = load_config()
    cfg["media_provider"] = provider
    mp = cfg.setdefault("providers", {}).setdefault(f"{provider}_media", {})
    mp["auth"] = auth
    if api_key:
        mp["api_key"] = api_key
    save_config(cfg)
    return cfg


def cmd_setup(args: list) -> None:
    """Interactive plain-terminal setup wizard."""
    from config import save_config, default_config, config_exists, load_config

    _hr()
    print(_C("\n  ✦  K O Z A   A G E N T  ·  Setup Wizard\n", "bold", "yellow"))

    # ── Load or init config ───────────────────────────────────────────────────
    if config_exists():
        cfg = load_config()
        cur_provider = cfg.get("provider", "?")
        cur_model    = cfg.get("model", "?")
        cur_media    = cfg.get("media_provider", "")
        cur_fallback = cfg.get("fallback_provider", "")
        def _status(val):
            return _C(f"({val})", "teal") if val else _C("(not set)", "grey")
    else:
        cfg = default_config()
        cur_provider = cur_model = cur_media = cur_fallback = ""
        def _status(val):
            return _C("(not set)", "grey")

    # ── Section menu ──────────────────────────────────────────────────────────
    sections = [
        f"Primary Provider    {_status(f'{cur_provider} / {cur_model}' if cur_provider else '')}",
        f"Fallback Provider   {_status(cur_fallback)}",
        f"Media (Image/Video) {_status(cur_media or cur_provider)}",
        f"Multi-host Sync     {_status('enabled' if cfg.get('sync') else '')}",
        f"Voice Mode          {_status('enabled' if cfg.get('voice') else '')}",
        "Done — save & exit",
    ]

    print(_C("  Select sections to configure. Choose 'Done' when finished.\n", "grey"))

    # Track what changed so we can save once at the end
    provider        = cfg.get("provider", "")
    model           = cfg.get("model", "")
    gemini_auth     = cfg.get("providers", {}).get("gemini", {}).get("auth", "api_key")
    fallback_provider = cfg.get("fallback_provider", "")
    fallback_model    = cfg.get("fallback_model", "")

    while True:
        # Refresh status labels before each menu render
        cur_provider = cfg.get("provider", "")
        cur_model    = cfg.get("model", "")
        cur_media    = cfg.get("media_provider", "")
        cur_fallback = cfg.get("fallback_provider", "")
        sections = [
            f"Primary Provider    {_status(f'{cur_provider} / {cur_model}' if cur_provider else '')}",
            f"Fallback Provider   {_status(cur_fallback)}",
            f"Media (Image/Video) {_status(cur_media or cur_provider)}",
            f"Multi-host Sync     {_status('enabled' if cfg.get('sync') else '')}",
            f"Voice Mode          {_status('enabled' if cfg.get('voice', {}).get('enabled') else 'disabled')}",
            "Done — save & exit",
        ]
        try:
            section = _select_menu("Configure section", sections, default_idx=5)
        except (KeyboardInterrupt, EOFError):
            print(_C("\n  Cancelled.\n", "grey"))
            return

        # ── Done ──────────────────────────────────────────────────────────────
        if section.startswith("Done"):
            break

        # ── Primary Provider ──────────────────────────────────────────────────
        elif section.startswith("Primary"):
            _hr("·", "grey")
            print(_C("  Primary Provider", "cyan", "bold"))
            _hr("·", "grey")
            default_idx = PROVIDERS.index(cur_provider) if cur_provider in PROVIDERS else 0
            try:
                provider_choice = _select_menu("Select provider", PROVIDERS, default_idx=default_idx)
            except (KeyboardInterrupt, EOFError):
                continue

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
                continue
            model = _prompt("Enter model name") if model_choice == _OTHER else model_choice

            api_key = ""

            if provider == "gemini" and gemini_auth == "cookie":
                # Playwright persistent session — no cookies to paste
                session_ok = _check_playwright_session()
                if session_ok:
                    print(_C("  ✓  Gemini browser session found.\n", "green"))
                else:
                    print(_C("  ℹ  No Gemini browser session found.\n", "grey"))
                    try:
                        do_login = _select_menu(
                            "Set up Gemini browser session now?",
                            ["Yes — open browser to log in", "Skip — set up later via koza setup"],
                            default_idx=0,
                        )
                    except (KeyboardInterrupt, EOFError):
                        do_login = "Skip"
                    if "Yes" in do_login:
                        _playwright_gemini_login()
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
                # cookie auth: no credentials to store — Playwright session handles it
            elif api_key:
                cfg.setdefault("providers", {}).setdefault(provider, {})["api_key"] = api_key
            if provider == "ollama":
                cfg.setdefault("providers", {}).setdefault("ollama", {})["base_url"] = ollama_url
            if provider == "antigravity manager":
                cfg.setdefault("providers", {}).setdefault("antigravity manager", {})["base_url"] = antigravity_url
            print(_C(f"\n  ✓  Primary provider set to {provider} / {model}\n", "green"))

        # ── Fallback Provider ─────────────────────────────────────────────────
        elif section.startswith("Fallback"):
            _hr("·", "grey")
            print(_C("  Fallback Provider", "cyan", "bold"))
            print(_C("  Used automatically if primary provider fails.\n", "grey"))
            _hr("·", "grey")
            enable = _prompt("Enable fallback provider?", default="n", choices=["y", "n"])
            if enable.lower() == "y":
                cur_p = cfg.get("provider", "")
                remaining = [p for p in PROVIDERS if p != cur_p]
                try:
                    fb_choice = _select_menu("Select fallback provider", remaining, default_idx=0)
                except (KeyboardInterrupt, EOFError):
                    continue
                fb_prov = "gemini" if fb_choice.startswith("gemini") else fb_choice
                fb_models = PROVIDER_MODELS.get(fb_choice, [""]) + [_OTHER]
                try:
                    fb_model_choice = _select_menu("Select fallback model", fb_models, default_idx=0)
                except (KeyboardInterrupt, EOFError):
                    continue
                fb_model = _prompt("Enter fallback model name") if fb_model_choice == _OTHER else fb_model_choice
                fb_key = ""
                if fb_choice in NEEDS_KEY:
                    existing = cfg.get("providers", {}).get(fb_prov, {}).get("api_key", "")
                    if existing:
                        print(_C(f"  ✓  Existing key found for {fb_choice}.", "green"))
                    else:
                        fb_key = _prompt_secret(f"API key for {fb_choice} (optional if already set)")
                cfg["fallback_provider"] = fb_prov
                cfg["fallback_model"]    = fb_model
                if fb_key:
                    cfg.setdefault("providers", {}).setdefault(fb_prov, {})["api_key"] = fb_key
                print(_C(f"\n  ✓  Fallback set to {fb_prov} / {fb_model}\n", "green"))
            else:
                cfg.pop("fallback_provider", None)
                cfg.pop("fallback_model", None)
                print(_C("  ✓  Fallback disabled.\n", "green"))

        # ── Media Provider ────────────────────────────────────────────────────
        elif section.startswith("Media"):
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
                continue

            if "Skip" in media_action:
                continue
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

        # ── Multi-host Sync ───────────────────────────────────────────────────
        elif section.startswith("Multi"):
            from cli.commands import cmd_sync
            cmd_sync(["setup"])

        # ── Voice Mode ────────────────────────────────────────────────────────
        elif section.startswith("Voice"):
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
                    continue
                if "Disable" in voice_action:
                    cfg.setdefault("voice", {})["enabled"] = False
                    save_config(cfg)
                    print(_C("  ✓  Voice mode disabled.\n", "green"))
                elif "Skip" in voice_action:
                    continue
                else:
                    from cli.voice_cmd import _do_setup
                    _do_setup([])
                    cfg = load_config()  # reload after voice setup saves
            else:
                try:
                    voice_action = _select_menu(
                        "Voice mode is currently disabled",
                        ["Enable & configure voice mode",
                         "Skip — no changes"],
                        default_idx=1,
                    )
                except (KeyboardInterrupt, EOFError):
                    continue
                if "Enable" in voice_action:
                    from cli.voice_cmd import _do_setup
                    _do_setup([])
                    cfg = load_config()  # reload after voice setup saves


    # ── Save & exit ───────────────────────────────────────────────────────────
    save_config(cfg)
    _hr()
    print(_C(f"\n  ✅  Config saved → {_config_path()}\n", "green"))
    _hr()


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
                import os; session_ok = os.path.isfile(os.path.join(os.path.expanduser("~"), ".koza", "gemini_browser", "Default", "Preferences"))
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
        # Accept short names like "gemini" matching "gemini api"
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

    # Build display labels showing credential status
    labels = []
    for name in configured:
        vals = providers_cfg[name]
        auth = vals.get("auth", "api_key")
        key  = vals.get("api_key") or vals.get("token", "")
        if auth == "playwright":
            import os as _os; cred = "browser"
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
