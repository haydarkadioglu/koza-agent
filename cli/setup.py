"""Setup wizard and provider command."""
import os
import sys

from cli.ui import (
    _C, _hr, _config_path, _select_menu, _prompt, _prompt_secret,
    _extract_gemini_cookies,
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


def _playwright_gemini_login() -> tuple[str, str]:
    """Extract Gemini cookies from the running browser session.

    Strategy:
    1. Try browser_cookie3 (reads from running Chrome/Edge/Firefox directly)
    2. If that fails (no session), open a fresh Playwright Chromium for manual login
    """
    # ── Step 1: try reading from running browser ──────────────────────────────
    print(_C("\n  Checking for existing Google session in your browser…\n", "grey"))
    psid, psidts, found_browser = _extract_gemini_cookies()

    if psid:
        print(_C(f"  ✓  Found active Google session in {found_browser}!\n", "green"))
        return psid, psidts

    # ── Step 2: no session found — open fresh Chromium for manual login ───────
    print(_C("  ℹ  No active session found in any browser.", "grey"))
    print(_C("  Opening a fresh browser window — please log in to your Google account.\n", "grey"))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(_C("  ⚠  playwright not installed. Run: pip install playwright && playwright install chromium", "yellow"))
        return "", ""

    psid = psidts = ""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False, slow_mo=50)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto("https://gemini.google.com", wait_until="domcontentloaded", timeout=20000)

            print(_C("  ● Log in to your Google account in the browser.", "cyan"))
            print(_C("  ● When you see the Gemini chat screen, press Enter here.\n", "grey"))
            try:
                input(_C("  Press Enter when logged in › ", "yellow"))
            except (EOFError, KeyboardInterrupt):
                browser.close()
                return "", ""

            cookies = ctx.cookies("https://gemini.google.com")
            browser.close()

            for c in cookies:
                if c["name"] == "__Secure-1PSID":
                    psid = c["value"]
                elif c["name"] == "__Secure-1PSIDTS":
                    psidts = c["value"]

    except Exception as e:
        print(_C(f"  ⚠  Browser login failed: {e}", "yellow"))
        return "", ""

    if psid:
        print(_C("  ✓  Cookies captured successfully!\n", "green"))
    else:
        print(_C("  ✗  Could not find __Secure-1PSID — make sure you logged in fully.\n", "red"))

    return psid, psidts


def cmd_setup(args: list) -> None:
    """Interactive plain-terminal setup wizard."""
    from config import save_config, default_config

    _hr()
    print(_C("\n  ✦  K O Z A   A G E N T  ·  Setup Wizard\n", "bold", "yellow"))
    print(_C("  Configure your LLM provider. Press Enter to accept defaults.\n", "grey"))

    # ── Provider ──────────────────────────────────────────────────────────────
    _hr("·", "grey")
    print(_C("  Primary Provider", "cyan", "bold"))
    _hr("·", "grey")
    try:
        provider_choice = _select_menu("Select provider", PROVIDERS, default_idx=0)
    except (KeyboardInterrupt, EOFError):
        sys.exit(0)

    # Normalise to internal provider name
    if provider_choice == "gemini api":
        provider = "gemini"
        gemini_auth = "api_key"
    elif provider_choice == "gemini cookie":
        provider = "gemini"
        gemini_auth = "cookie"
    else:
        provider = provider_choice
        gemini_auth = "api_key"

    models = PROVIDER_MODELS.get(provider_choice, [""]) + [_OTHER]
    try:
        model_choice = _select_menu("Select model", models, default_idx=0)
    except (KeyboardInterrupt, EOFError):
        sys.exit(0)
    if model_choice == _OTHER:
        model = _prompt("Enter model name")
        while not model:
            model = _prompt("Enter model name")
    else:
        model = model_choice

    api_key = ""
    gemini_cookie_1psid   = ""
    gemini_cookie_1psidts = ""

    if provider == "gemini" and gemini_auth == "cookie":
        # Step 1: try browser_cookie3 — reads Chrome/Edge/Firefox SQLite directly,
        #         works even when the browser is already open (no process launch needed)
        print(_C("\n  Extracting Google session cookies from your browser…\n", "grey"))
        auto_1psid, auto_1psidts, auto_browser = _extract_gemini_cookies()

        if auto_1psid:
            print(_C(f"  ✓  Active Google session found in {auto_browser}!\n", "green"))
            gemini_cookie_1psid   = auto_1psid
            gemini_cookie_1psidts = auto_1psidts
        else:
            # Chrome locks its cookie DB while running — browser_cookie3 can't read it.
            # Guide the user to paste cookies manually from DevTools.
            print(_C("  ⚠  Could not read cookies from your browser automatically.", "yellow"))
            print(_C("  (Chrome locks its cookie database while it is running)\n", "grey"))
            try:
                choice = _select_menu(
                    "How do you want to provide cookies?",
                    [
                        "Paste cookie from DevTools (recommended)",
                        "Open a fresh browser window to log in",
                    ],
                    default_idx=0,
                )
            except (KeyboardInterrupt, EOFError):
                sys.exit(0)

            if "fresh browser" in choice:
                gemini_cookie_1psid, gemini_cookie_1psidts = _playwright_gemini_login()

            if not gemini_cookie_1psid:
                print(_C("\n  How to get your cookie from DevTools:", "cyan", "bold"))
                print(_C("  1. Open Chrome and go to gemini.google.com", "white"))
                print(_C("  2. Press F12 → Application tab → Cookies → https://gemini.google.com", "white"))
                print(_C("  3. Find __Secure-1PSID and copy its Value\n", "white"))
                gemini_cookie_1psid = _prompt_secret("Paste __Secure-1PSID value")
                while not gemini_cookie_1psid:
                    print(_C("  ⚠  Cookie value required.", "red"))
                    gemini_cookie_1psid = _prompt_secret("Paste __Secure-1PSID value")
                gemini_cookie_1psidts = _prompt_secret("Paste __Secure-1PSIDTS (optional, Enter to skip)")
    elif provider_choice in NEEDS_KEY:
        api_key = _prompt_secret(f"API key for {provider_choice}")
        while not api_key:
            print(_C(f"  ⚠  API key is required for {provider_choice}.", "red"))
            api_key = _prompt_secret(f"API key for {provider_choice}")

    ollama_url = "http://localhost:11434"
    if provider == "ollama":
        ollama_url = _prompt("Ollama base URL", default="http://localhost:11434")

    antigravity_url = "http://localhost:5188"
    if provider == "antigravity manager":
        print(_C("\n  Antigravity Tools LS — make sure it's running locally.", "grey"))
        print(_C("  Install: https://github.com/lbjlaq/Antigravity-Tools-LS\n", "grey"))
        antigravity_url = _prompt("Antigravity Tools LS URL", default="http://localhost:5188")

    # ── Fallback provider ─────────────────────────────────────────────────────
    _hr("·", "grey")
    print(_C("  Fallback Provider", "cyan", "bold"))
    print(_C("  Used automatically if primary provider fails or is unavailable.", "grey"))
    _hr("·", "grey")
    enable_fallback = _prompt("Enable fallback provider?", default="n", choices=["y", "n"])

    fallback_provider = ""
    fallback_model = ""
    fallback_key = ""
    if enable_fallback.lower() == "y":
        remaining = [p for p in PROVIDERS if p != provider_choice]
        try:
            fb_choice = _select_menu("Select fallback provider", remaining, default_idx=0)
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
        fallback_provider = "gemini" if fb_choice.startswith("gemini") else fb_choice
        fb_models = PROVIDER_MODELS.get(fb_choice, [""]) + [_OTHER]
        try:
            fb_model_choice = _select_menu("Select fallback model", fb_models, default_idx=0)
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
        if fb_model_choice == _OTHER:
            fallback_model = _prompt("Enter fallback model name")
        else:
            fallback_model = fb_model_choice
        if fb_choice in NEEDS_KEY:
            fallback_key = _prompt_secret(f"API key for {fb_choice} (optional if already set)")

    # ── Build config ──────────────────────────────────────────────────────────
    cfg = default_config()
    cfg["provider"] = provider
    cfg["model"] = model
    if provider == "gemini":
        cfg["providers"]["gemini"]["auth"] = gemini_auth
        if gemini_auth == "api_key" and api_key:
            cfg["providers"]["gemini"]["api_key"] = api_key
        elif gemini_auth == "cookie":
            cfg["providers"]["gemini"]["cookie_1psid"]   = gemini_cookie_1psid
            if gemini_cookie_1psidts:
                cfg["providers"]["gemini"]["cookie_1psidts"] = gemini_cookie_1psidts
    elif api_key:
        cfg["providers"][provider]["api_key"] = api_key
    if provider == "ollama":
        cfg["providers"]["ollama"]["base_url"] = ollama_url
    if provider == "antigravity manager":
        cfg["providers"].setdefault("antigravity manager", {})["base_url"] = antigravity_url
    if fallback_provider:
        cfg["fallback_provider"] = fallback_provider
        cfg["fallback_model"] = fallback_model
        if fallback_key:
            cfg["providers"].setdefault(fallback_provider, {})["api_key"] = fallback_key

    save_config(cfg)
    _hr()
    print(_C(f"\n  ✅  Config saved → {_config_path()}\n", "green"))
    _hr()

    # ── Multi-host setup ──────────────────────────────────────────────────────
    try:
        mh_choice = _prompt("Enable multi-host sync?", default="n", choices=["y", "n"])
    except (KeyboardInterrupt, EOFError):
        return
    if mh_choice.lower() == "y":
        from cli.commands import cmd_sync
        cmd_sync(["setup"])


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
            key = vals.get("api_key") or vals.get("token") or vals.get("cookie_1psid", "")
            auth = vals.get("auth", "api_key")
            if auth == "cookie":
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
        key  = vals.get("api_key") or vals.get("token") or vals.get("cookie_1psid", "")
        if auth == "cookie":
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
