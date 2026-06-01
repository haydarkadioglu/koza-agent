"""Setup helper functions — API key validation, Playwright login, media config."""
import os
import shutil
import subprocess

from cli.ui import _C, _prompt_secret


def _validate_api_key(provider: str, api_key: str, model: str = "") -> tuple[bool, str]:
    """Test an API key by making a lightweight request to the provider.

    Returns (success: bool, message: str).
    """
    from cli.ui import _spinner_start, _spinner_stop

    # Provider → (base_url, test_model)
    _ENDPOINTS = {
        "openai":     ("https://api.openai.com/v1", "gpt-4o"),
        "anthropic":  (None, "claude-haiku-4-5"),
        "deepseek":   ("https://api.deepseek.com/v1", "deepseek-chat"),
        "groq":       ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
        "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
        "gemini api": (None, ""),
        "gemini":     (None, ""),
        "github":     ("https://models.inference.ai.azure.com", "gpt-4o"),
        "kimi":       ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
        "minimax":    ("https://api.minimax.io/v1", "MiniMax-Text-01"),
        "zai":        ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    }

    if provider not in _ENDPOINTS:
        return True, "skipped (no validation for this provider)"

    _spinner_start("  Testing API key…")

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model=_ENDPOINTS["anthropic"][1],
                max_tokens=5,
                messages=[{"role": "user", "content": "hi"}],
            )
            _spinner_stop()
            return True, "valid"

        elif provider in ("gemini api", "gemini"):
            from google import genai
            client = genai.Client(api_key=api_key)
            list(client.models.list())
            _spinner_stop()
            return True, "valid"

        else:
            # OpenAI-compatible providers
            from openai import OpenAI
            base_url, test_model = _ENDPOINTS[provider]
            kwargs = {"api_key": api_key, "base_url": base_url}
            if provider == "openrouter":
                kwargs["default_headers"] = {
                    "HTTP-Referer": "https://github.com/haydarkadioglu/koza-agent",
                    "X-Title": "Koza Agent",
                }
            client = OpenAI(**kwargs)
            client.models.list()
            _spinner_stop()
            return True, "valid"

    except Exception as e:
        _spinner_stop()
        err_msg = str(e)
        if "401" in err_msg or "auth" in err_msg.lower() or "invalid" in err_msg.lower():
            return False, "invalid API key"
        elif "403" in err_msg or "permission" in err_msg.lower():
            return False, "access denied — check your plan/permissions"
        elif "connection" in err_msg.lower() or "timeout" in err_msg.lower():
            return False, f"connection error — {err_msg[:80]}"
        else:
            return False, err_msg[:100]


def _playwright_gemini_login() -> bool:
    """Open a persistent Playwright browser session for Gemini login."""
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
    profile_dir = os.path.join(os.path.expanduser("~"), ".koza", "gemini_browser")
    prefs = os.path.join(profile_dir, "Default", "Preferences")
    return os.path.isfile(prefs)


def _google_adc_login_interactive() -> bool:
    """Run an interactive local Google login flow (opens browser) for ADC."""
    print(_C("\n  Opening Google login flow for Gemini CLI / ADC...\n", "grey"))

    if shutil.which("gcloud"):
        try:
            subprocess.run(
                ["gcloud", "auth", "application-default", "login"],
                check=True,
            )
            print(_C("  ✓  Google ADC login completed.\n", "green"))
            return True
        except subprocess.CalledProcessError as e:
            print(_C(f"  ⚠  gcloud login failed: {e}\n", "yellow"))

    if shutil.which("gemini"):
        try:
            subprocess.run(["gemini", "auth", "login"], check=True)
            print(_C("  ✓  Gemini CLI login completed.\n", "green"))
            return True
        except subprocess.CalledProcessError as e:
            print(_C(f"  ⚠  Gemini CLI login failed: {e}\n", "yellow"))

    print(_C("  ✗  No login tool found.", "red"))
    print(_C("  Install Google Cloud CLI (gcloud) or Gemini CLI, then retry.\n", "yellow"))
    return False


def _check_antigravity_running(base_url: str = "http://localhost:5188") -> bool:
    """Return True if Antigravity Manager is reachable at base_url."""
    try:
        import urllib.request
        req = urllib.request.urlopen(f"{base_url}/v1/models", timeout=2)
        return req.status == 200
    except Exception:
        return False


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
