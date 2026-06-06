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
    
    webview_window = webview.create_window(
        title="Koza Agent Cockpit",
        url=str(html_path),
        js_api=api_bridge,
        width=1200,
        height=800,
        min_size=(1000, 700),
        background_color="#0A0915"
    )
    
    # Defer setting the webview window reference until loaded to avoid early accessibility queries
    def on_loaded():
        api_bridge.webview_window = webview_window

    webview_window.events.loaded += on_loaded
    
    # Run the native webview application
    webview.start(debug=True)

if __name__ == "__main__":
    start_gui()
