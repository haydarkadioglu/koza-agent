"""Setup wizard and provider command."""
import sys

from cli.ui import (
    _C, _hr, _config_path, _select_menu, _prompt, _prompt_secret,
    _extract_gemini_cookies,
)

PROVIDERS = ["ollama", "openai", "anthropic", "deepseek", "gemini api", "gemini cookie", "github"]
PROVIDER_MODELS = {
    "openai":         ["gpt-4.1", "gpt-4o", "gpt-4o-mini"],
    "anthropic":      ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
    "deepseek":       ["deepseek-chat", "deepseek-reasoner", "deepseek-coder-v2"],
    "gemini api":     ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview"],
    "gemini cookie":  ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview"],
    "gemini":         ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview"],
    "ollama":         ["llama3.2", "mistral", "codellama"],
    "github":         ["gpt-4.1", "gpt-4o", "Meta-Llama-3.1-70B-Instruct"],
}
NEEDS_KEY = {"openai", "anthropic", "deepseek", "gemini api", "gemini", "github"}
_OTHER = "other — enter manually"


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
        # Try auto-extract from browser first
        auto_1psid, auto_1psidts, auto_browser = _extract_gemini_cookies()
        if auto_1psid:
            print(_C(f"  ✓  Cookies found in {auto_browser}!", "green"))
            use_auto = _prompt("Use these cookies?", default="y", choices=["y", "n"])
            if use_auto.lower() == "y":
                gemini_cookie_1psid   = auto_1psid
                gemini_cookie_1psidts = auto_1psidts
        if not gemini_cookie_1psid:
            print(_C("  ℹ  Could not auto-extract. Make sure you're logged in to gemini.google.com", "grey"))
            print(_C("  ℹ  Or: DevTools (F12) → Application → Cookies → __Secure-1PSID", "grey"))
            gemini_cookie_1psid = _prompt_secret("Paste __Secure-1PSID cookie value")
            while not gemini_cookie_1psid:
                print(_C("  ⚠  Cookie value required.", "red"))
                gemini_cookie_1psid = _prompt_secret("Paste __Secure-1PSID cookie value")
            gemini_cookie_1psidts = _prompt_secret("Paste __Secure-1PSIDTS (optional, Enter to skip)")
    elif provider_choice in NEEDS_KEY:
        api_key = _prompt_secret(f"API key for {provider_choice}")
        while not api_key:
            print(_C(f"  ⚠  API key is required for {provider_choice}.", "red"))
            api_key = _prompt_secret(f"API key for {provider_choice}")

    ollama_url = "http://localhost:11434"
    if provider == "ollama":
        ollama_url = _prompt("Ollama base URL", default="http://localhost:11434")

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
    if fallback_provider:
        cfg["fallback_provider"] = fallback_provider
        cfg["fallback_model"] = fallback_model
        if fallback_key:
            cfg["providers"].setdefault(fallback_provider, {})["api_key"] = fallback_key

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
