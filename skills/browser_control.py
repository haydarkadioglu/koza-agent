"""Visible browser automation skill powered by Playwright."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


_permission_callback: Callable[[str, dict], bool] | None = None

_CRITICAL_PATTERNS = re.compile(
    r"\b("
    r"pay|payment|purchase|buy|checkout|order|delete|remove account|cancel subscription|"
    r"submit|send|post|publish|login|log in|sign in|sign up|register|"
    r"ödeme|satın al|satınalma|sipariş|sil|hesap sil|aboneliği iptal|"
    r"gönder|paylaş|yayınla|giriş yap|kayıt ol"
    r")\b",
    re.IGNORECASE,
)

_CAPTCHA_PATTERNS = re.compile(
    r"(captcha|recaptcha|hcaptcha|two[-\s]?factor|2fa|verification code|"
    r"doğrulama kodu|iki aşamalı|güvenlik kodu)",
    re.IGNORECASE,
)

_SEARCH_HINT_RE = re.compile(
    r"(?:search|ara|arama yap|look up|find)\s+(?:for\s+)?['\"]?(.+?)['\"]?$",
    re.IGNORECASE,
)


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "browser_task",
            "description": (
                "Open a visible browser and perform a high-level website task. "
                "Supports navigation, search/form filling, clicking by visible text, downloads, "
                "popups/new tabs, screenshots, and visible text extraction. Critical actions "
                "such as payment, deletion, login submit, posting, or sending require user approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "Natural-language task to perform in the browser.",
                    },
                    "start_url": {
                        "type": "string",
                        "default": "",
                        "description": "Optional URL to open before interpreting the instruction.",
                    },
                    "max_steps": {
                        "type": "integer",
                        "default": 25,
                        "description": "Maximum automation steps before stopping.",
                    },
                    "allow_downloads": {
                        "type": "boolean",
                        "default": True,
                        "description": "Allow and report file downloads.",
                    },
                    "use_existing_profile": {
                        "type": "boolean",
                        "default": True,
                        "description": "Try importing cookies from installed browsers into Koza's persistent profile.",
                    },
                },
                "required": ["instruction"],
            },
        },
    }
]


def set_permission_callback(callback: Callable[[str, dict], bool] | None) -> None:
    global _permission_callback
    _permission_callback = callback


def _home_koza_dir() -> Path:
    return Path.home() / ".Koza"


def _profile_dir() -> Path:
    return _home_koza_dir() / "browser_profile"


def _download_dir() -> Path:
    return _home_koza_dir() / "workspace" / "downloads"


def _screenshot_dir() -> Path:
    return _home_koza_dir() / "workspace" / "browser_screenshots"


def _find_chrome_executable() -> str:
    candidates = [
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("msedge"),
        shutil.which("msedge.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return ""


def _normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if re.match(r"^(https?://|file://|data:)", value, re.I):
        return value
    if "." in value and " " not in value:
        return f"https://{value}"
    return ""


def _extract_url(instruction: str, start_url: str = "") -> str:
    explicit = _normalize_url(start_url)
    if explicit:
        return explicit
    match = re.search(r"https?://\S+|(?:www\.)?[\w.-]+\.[a-z]{2,}(?:/\S*)?", instruction, re.I)
    return _normalize_url(match.group(0)) if match else ""


def _looks_critical(text: str) -> bool:
    return bool(_CRITICAL_PATTERNS.search(text or ""))


def _request_critical_permission(reason: str, instruction: str, url: str = "") -> bool:
    if not _looks_critical(reason + " " + instruction):
        return True
    if _permission_callback is None:
        return False
    return bool(_permission_callback("browser_critical_action", {
        "reason": reason,
        "instruction": instruction,
        "url": url,
    }))


def _cookie_domain_matches(cookie_domain: str, target_host: str) -> bool:
    if not target_host:
        return True
    domain = (cookie_domain or "").lstrip(".").lower()
    host = target_host.lower()
    return host == domain or host.endswith("." + domain)


def _import_browser_cookies(context, target_url: str) -> str:
    try:
        import browser_cookie3
    except ImportError:
        return "browser_cookie3 is not installed; skipped existing browser cookies."

    target_host = urlparse(target_url).hostname or ""
    loaders = [
        ("Chrome", browser_cookie3.chrome),
        ("Edge", browser_cookie3.edge),
        ("Firefox", browser_cookie3.firefox),
        ("Brave", browser_cookie3.brave),
        ("Opera", browser_cookie3.opera),
    ]
    converted = []
    loaded_from = []
    for label, loader in loaders:
        try:
            jar = loader()
        except Exception:
            continue
        count_before = len(converted)
        for cookie in jar:
            if not _cookie_domain_matches(cookie.domain, target_host):
                continue
            same_site = "Lax"
            converted.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path or "/",
                "expires": int(cookie.expires) if cookie.expires else -1,
                "httpOnly": bool(getattr(cookie, "has_nonstandard_attr", lambda _n: False)("HttpOnly")),
                "secure": bool(cookie.secure),
                "sameSite": same_site,
            })
            if len(converted) >= 250:
                break
        if len(converted) > count_before:
            loaded_from.append(label)
        if len(converted) >= 250:
            break

    if not converted:
        return "No matching browser cookies imported."
    try:
        context.add_cookies(converted)
        return f"Imported {len(converted)} cookie(s) from: {', '.join(loaded_from)}."
    except Exception as exc:
        return f"Cookie import failed: {exc}"


def _page_text(page, limit: int = 2500) -> str:
    try:
        text = page.inner_text("body", timeout=3000)
    except Exception:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _detect_blocker(page) -> str:
    text = _page_text(page, 4000)
    if _CAPTCHA_PATTERNS.search(text):
        return "Captcha/2FA/verification detected. Please complete it in the visible browser window, then run the task again if needed."
    return ""


def _find_primary_input(page):
    selectors = [
        "input[type='search']",
        "textarea[name='q']",
        "input[name='q']",
        "textarea",
        "input[type='text']",
        "input:not([type])",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible(timeout=1000):
                return loc
        except Exception:
            continue
    return None


def _extract_search_query(instruction: str) -> str:
    match = _SEARCH_HINT_RE.search(instruction)
    if match:
        return match.group(1).strip(" .'\"")
    quoted = re.findall(r"['\"]([^'\"]{2,})['\"]", instruction)
    if quoted:
        return quoted[-1]
    return ""


def _extract_click_text(instruction: str) -> str:
    patterns = [
        r"(?:click|tıkla|bas)\s+['\"]([^'\"]+)['\"]",
        r"(?:click|tıkla|bas)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction, re.I)
        if match:
            return match.group(1).strip(" .'\"")
    return ""


def _extract_upload_path(instruction: str) -> str:
    patterns = [
        r"(?:upload|yükle|dosya yükle)\s+['\"]([^'\"]+)['\"]",
        r"(?:upload|yükle|dosya yükle)\s+(\S+\.[\w]{1,12})",
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction, re.I)
        if match:
            path = Path(match.group(1)).expanduser()
            return str(path.resolve()) if path.exists() else str(path)
    return ""


def _extract_select_value(instruction: str) -> str:
    patterns = [
        r"(?:select|choose|seç)\s+['\"]([^'\"]+)['\"]",
        r"(?:select|choose|seç)\s+(.+?)(?:\s+(?:option|seçeneği|seçeneğini))?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction, re.I)
        if match:
            return match.group(1).strip(" .'\"")
    return ""


def _extract_checkbox_label(instruction: str) -> str:
    patterns = [
        r"(?:check|tick|işaretle|onayla)\s+['\"]([^'\"]+)['\"]",
        r"(?:check|tick|işaretle|onayla)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, instruction, re.I)
        if match:
            return match.group(1).strip(" .'\"")
    return ""


def _try_upload_file(page, path: str) -> str:
    if not path:
        return ""
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        return f"Upload skipped; file not found: {file_path}"
    try:
        loc = page.locator("input[type='file']").first
        if loc.count():
            loc.set_input_files(str(file_path), timeout=5000)
            return f"Uploaded file: {file_path}"
    except Exception as exc:
        return f"Upload failed: {exc}"
    return "Upload skipped; no file input found."


def _try_select_option(page, value: str) -> str:
    if not value:
        return ""
    try:
        loc = page.locator("select").first
        if loc.count() and loc.is_visible(timeout=1000):
            try:
                loc.select_option(label=value, timeout=5000)
            except Exception:
                loc.select_option(value=value, timeout=5000)
            return f"Selected option: {value}"
    except Exception as exc:
        return f"Select failed: {exc}"
    return ""


def _try_check_box(page, label: str) -> str:
    if not label:
        return ""
    try:
        loc = page.get_by_label(re.compile(re.escape(label), re.I)).first
        if loc.count() and loc.is_visible(timeout=1000):
            loc.check(timeout=5000)
            return f"Checked: {label}"
    except Exception:
        pass
    try:
        loc = page.get_by_text(re.compile(re.escape(label), re.I)).first
        if loc.count() and loc.is_visible(timeout=1000):
            loc.click(timeout=5000)
            return f"Clicked checkbox/label text: {label}"
    except Exception as exc:
        return f"Checkbox failed: {exc}"
    return ""


def _try_click_text(page, text: str) -> str:
    if not text:
        return ""
    selectors = [
        page.get_by_role("button", name=re.compile(re.escape(text), re.I)),
        page.get_by_role("link", name=re.compile(re.escape(text), re.I)),
        page.get_by_text(re.compile(re.escape(text), re.I)).first,
    ]
    for loc in selectors:
        try:
            if loc.count() and loc.is_visible(timeout=1500):
                loc.click(timeout=5000)
                return f"Clicked visible text: {text}"
        except Exception:
            continue
    return ""


def _run_simple_task(page, instruction: str, steps: list[str], max_steps: int) -> None:
    if len(steps) >= max_steps:
        return
    blocker = _detect_blocker(page)
    if blocker:
        steps.append(blocker)
        try:
            page.wait_for_timeout(30000)
        except Exception:
            pass
            return

    upload_path = _extract_upload_path(instruction)
    if upload_path and len(steps) < max_steps:
        steps.append(_try_upload_file(page, upload_path))

    checkbox_label = _extract_checkbox_label(instruction)
    if checkbox_label and len(steps) < max_steps:
        checked = _try_check_box(page, checkbox_label)
        if checked:
            steps.append(checked)

    select_value = _extract_select_value(instruction)
    if select_value and len(steps) < max_steps:
        selected = _try_select_option(page, select_value)
        if selected:
            steps.append(selected)

    search_query = _extract_search_query(instruction)
    if search_query and len(steps) < max_steps:
        loc = _find_primary_input(page)
        if loc is not None:
            loc.fill(search_query, timeout=5000)
            steps.append(f"Filled primary input with: {search_query}")
            try:
                loc.press("Enter", timeout=5000)
                steps.append("Pressed Enter.")
            except Exception as exc:
                steps.append(f"Enter press skipped: {str(exc).splitlines()[0]}")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                page.wait_for_timeout(2000)
            return

    click_text = _extract_click_text(instruction)
    if click_text and len(steps) < max_steps:
        if not _request_critical_permission(f"Click '{click_text}'", instruction, page.url):
            steps.append(f"Skipped critical click pending approval: {click_text}")
            return
        clicked = _try_click_text(page, click_text)
        if clicked:
            steps.append(clicked)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                page.wait_for_timeout(2000)


def browser_task(
    instruction: str,
    start_url: str = "",
    max_steps: int = 25,
    allow_downloads: bool = True,
    use_existing_profile: bool = True,
) -> str:
    """Run a conservative visible-browser task and return a compact report."""
    if not instruction.strip():
        return "ERROR: instruction is required."
    if _looks_critical(instruction) and not _request_critical_permission("Start critical browser task", instruction, start_url):
        return "Permission denied: critical browser task was not approved."

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "ERROR: playwright not installed. Run: pip install playwright && playwright install chromium"

    max_steps = max(1, min(int(max_steps or 25), 50))
    target_url = _extract_url(instruction, start_url)
    steps: list[str] = []
    downloads: list[str] = []
    screenshot_path = ""
    cookie_note = ""
    browser_note = ""

    _profile_dir().mkdir(parents=True, exist_ok=True)
    _download_dir().mkdir(parents=True, exist_ok=True)
    _screenshot_dir().mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as pw:
            chrome_path = _find_chrome_executable()
            launch_kwargs = {
                "headless": False,
                "accept_downloads": allow_downloads,
                "downloads_path": str(_download_dir()),
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if chrome_path:
                launch_kwargs["executable_path"] = chrome_path
                browser_note = f"Using system browser: {chrome_path}"
            else:
                browser_note = "Using Playwright Chromium fallback."

            context = pw.chromium.launch_persistent_context(str(_profile_dir()), **launch_kwargs)
            page = context.pages[0] if context.pages else context.new_page()

            if use_existing_profile and target_url:
                cookie_note = _import_browser_cookies(context, target_url)

            def _on_download(download):
                try:
                    suggested = download.suggested_filename or f"download_{int(time.time())}"
                    dest = _download_dir() / suggested
                    download.save_as(str(dest))
                    downloads.append(str(dest.resolve()))
                except Exception as exc:
                    downloads.append(f"ERROR saving download: {exc}")

            if allow_downloads:
                page.on("download", _on_download)

            def _on_popup(popup):
                try:
                    steps.append(f"New tab/popup opened: {popup.url}")
                except Exception:
                    steps.append("New tab/popup opened.")

            page.on("popup", _on_popup)

            if target_url:
                page.goto(target_url, timeout=30000, wait_until="domcontentloaded")
                steps.append(f"Opened: {target_url}")
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    page.wait_for_timeout(2000)
            else:
                steps.append("No start URL found; opened persistent browser profile only.")

            _run_simple_task(page, instruction, steps, max_steps)

            screenshot_path = str((_screenshot_dir() / f"browser_task_{int(time.time())}.png").resolve())
            page.screenshot(path=screenshot_path, full_page=True)
            visible_text = _page_text(page)
            final_url = page.url
            context.close()

        lines = [
            "Browser task finished.",
            f"Browser: {browser_note}",
        ]
        if cookie_note:
            lines.append(f"Session: {cookie_note}")
        lines.extend([
            f"Final URL: {final_url}",
            f"Screenshot: {screenshot_path}",
            "",
            "Steps:",
        ])
        lines.extend(f"- {step}" for step in steps)
        if downloads:
            lines.append("")
            lines.append("Downloads:")
            lines.extend(f"- {path}" for path in downloads)
        if visible_text:
            lines.append("")
            lines.append("Visible text:")
            lines.append(visible_text)
        return "\n".join(lines)
    except Exception as exc:
        return f"ERROR: browser_task failed: {exc}"


HANDLERS = {"browser_task": browser_task}
