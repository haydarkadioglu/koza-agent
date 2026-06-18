import os
import sys
import subprocess
from pathlib import Path

# Set WebView2 arguments to disable accessibility loop/freezes on Windows
if os.name == 'nt':
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--disable-renderer-accessibility'

# Add project root to path so we can import modules
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


# ── Auto dependency installer ──────────────────────────────────────────────────

# Core GUI packages that MUST be present
_GUI_REQUIRED = [
    ("pywebview", "pywebview>=5.0.0"),
]

# On Linux, pywebview needs a backend (PySide6 or GTK).
# On Windows it uses WebView2 (built-in), so PySide6 is optional.
if os.name != 'nt':
    _GUI_REQUIRED.append(("PySide6", "PySide6>=6.0.0"))


def _pkg_available(import_name: str) -> bool:
    """Return True if the package can be imported."""
    import importlib.util
    return importlib.util.find_spec(import_name) is not None


def _pip_install(*packages: str) -> bool:
    """Install one or more pip packages. Returns True on success."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", *packages],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _ensure_gui_dependencies() -> bool:
    """
    Check that all GUI-required packages are installed.
    Automatically installs missing ones (with a brief console notice).
    Returns True if everything is ready, False if something couldn't be installed.
    """
    missing = []
    for import_name, pip_spec in _GUI_REQUIRED:
        if not _pkg_available(import_name):
            missing.append((import_name, pip_spec))

    if not missing:
        return True

    print("🔧 Koza: Installing missing GUI dependencies…")
    for import_name, pip_spec in missing:
        print(f"   ▸ Installing {pip_spec}…", end=" ", flush=True)
        ok = _pip_install(pip_spec)
        print("✓" if ok else "✗ (failed)")
        if not ok:
            print(f"\n   Could not install {pip_spec} automatically.")
            print("   Run manually:  pip install " + pip_spec)
            return False

    print("✅ Dependencies installed. Starting GUI…\n")
    return True


def _ensure_requirements() -> None:
    """
    Check all packages listed in requirements.txt and install any that are missing.
    Runs silently — only prints if something needs to be installed.
    """
    req_file = project_root / "requirements.txt"
    if not req_file.exists():
        return

    import importlib.util, re

    # Map pip package name → importable name (where they differ)
    _IMPORT_NAME_OVERRIDES = {
        "pywebview": "webview",
        "pyyaml": "yaml",
        "python-dotenv": "dotenv",
        "python-whois": "whois",
        "paho-mqtt": "paho",
        "google-genai": "google.genai",
        "google-auth": "google.auth",
        "google-api-python-client": "googleapiclient",
        "gemini-webapi": "gemini",
        "browser-cookie3": "browser_cookie3",
        "curl_cffi": "curl_cffi",
        "python-telegram-bot": "telegram",
        "apscheduler": "apscheduler",
        "orjson": "orjson",
        "packaging": "packaging",
        "pygments": "pygments",
        "pyfiglet": "pyfiglet",
        "spotipy": "spotipy",
        "openpyxl": "openpyxl",
        "PySide6": "PySide6",
        "playwright": "playwright",
    }

    missing_specs = []

    for raw_line in req_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Extract package name (before any version specifier)
        pip_name = re.split(r"[>=<!;]", line)[0].strip()
        if not pip_name:
            continue
        import_name = _IMPORT_NAME_OVERRIDES.get(pip_name, pip_name.replace("-", "_").lower())
        if not _pkg_available(import_name):
            missing_specs.append(line)

    if not missing_specs:
        return

    print(f"🔧 Koza: Installing {len(missing_specs)} missing package(s)…")
    for spec in missing_specs:
        print(f"   ▸ {spec}")
    
    ok = _pip_install(*missing_specs)
    if ok:
        print("✅ All packages installed.\n")
    else:
        print("⚠️  Some packages failed to install. GUI may still work.\n")


# ── GUI entry point ────────────────────────────────────────────────────────────

webview_window = None


def start_gui():
    global webview_window

    # 1. Auto-install any missing requirements
    _ensure_requirements()

    # 2. Ensure GUI-specific packages are present
    if not _ensure_gui_dependencies():
        print("\nGUI cannot start due to missing dependencies.")
        return

    try:
        import webview
    except ImportError:
        print("Error: pywebview library is not installed.")
        print("Please install it: pip install pywebview")
        return

    # Create webview window loading local static files
    html_path = Path(__file__).resolve().parent / "static" / "gui.html"

    if not html_path.exists():
        print(f"Error: GUI HTML file not found at {html_path}")
        return

    from ui.bridge import KozaBridge
    api_bridge = KozaBridge()

    icon_path = Path(__file__).resolve().parent / "static" / "icon.png"

    webview_window = webview.create_window(
        title="Koza Agent Cockpit",
        url=str(html_path),
        js_api=api_bridge,
        width=1200,
        height=800,
        min_size=(1000, 700),
        background_color="#0A0915"
    )

    def on_loaded():
        api_bridge.webview_window = webview_window

    webview_window.events.loaded += on_loaded

    icon_png_path = Path(__file__).resolve().parent / "static" / "icon.png"
    icon_ico_path = Path(__file__).resolve().parent / "static" / "icon.ico"

    # Use .ico on Windows to prevent System.Drawing.Icon crash, .png on Linux
    app_icon = str(icon_ico_path) if os.name == 'nt' else str(icon_png_path)

    # Set Windows AppUserModelID so taskbar icon ungroups from python.exe
    if os.name == 'nt':
        try:
            import ctypes
            myappid = 'koza.agent.gui'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                if icon_ico_path.exists():
                    hicon = ctypes.windll.user32.LoadImageW(0, str(icon_ico_path), 1, 0, 0, 0x0010)
                    if hicon:
                        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, hicon)
                        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, hicon)
        except Exception:
            pass

    # Run the native webview application
    try:
        webview.start(debug=False, icon=app_icon)
    except TypeError:
        # Fallback if older pywebview doesn't accept icon argument
        webview.start(debug=False)


if __name__ == "__main__":
    start_gui()
