import os
import sys
from pathlib import Path

# Set WebView2 arguments to disable accessibility loop/freezes on Windows
if os.name == 'nt':
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--disable-renderer-accessibility'

# Add project root to path so we can import modules
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from ui.bridge import KozaBridge

webview_window = None

def start_gui():
    global webview_window
    
    try:
        import webview
    except ImportError:
        print("Error: pywebview library is not installed.")
        print("Please install it running: pip install pywebview")
        return
        
    # Create webview window loading local static files
    html_path = Path(__file__).resolve().parent / "static" / "gui.html"
    
    if not html_path.exists():
        print(f"Error: GUI HTML file not found at {html_path}")
        return
        
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
    
    # Optional: in PyWebView, we often pass icon via start() if supported, or wait...
    # pywebview create_window DOES support icon if they are using pywebview>=5.0, but usually it's in webview.start(icon=...) 
    # Actually, pywebview's webview.start() might take `icon` or `webview.start(icon=str(icon_path))`.
    # No, let's just leave create_window as is and add icon to start.
    
    # Defer setting the webview window reference until loaded to avoid early accessibility queries
    def on_loaded():
        api_bridge.webview_window = webview_window

    webview_window.events.loaded += on_loaded
    
    icon_png_path = Path(__file__).resolve().parent / "static" / "icon.png"
    
    # Set Windows AppUserModelID so taskbar icon ungroups from python.exe
    if os.name == 'nt':
        try:
            import ctypes
            myappid = 'koza.agent.gui'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            
            # Also set console icon if any
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                icon_ico_path = Path(__file__).resolve().parent / "static" / "icon.ico"
                if icon_ico_path.exists():
                    hicon = ctypes.windll.user32.LoadImageW(0, str(icon_ico_path), 1, 0, 0, 0x0010)
                    if hicon:
                        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, hicon)
                        ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, hicon)
        except Exception:
            pass

    # Run the native webview application
    try:
        webview.start(debug=False, icon=str(icon_png_path))
    except TypeError:
        # Fallback if older pywebview doesn't accept icon argument
        webview.start(debug=False)

if __name__ == "__main__":
    start_gui()
