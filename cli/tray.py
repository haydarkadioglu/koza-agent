import os
import sys
import threading
from pathlib import Path

def start_tray_icon(shutdown_event: threading.Event):
    try:
        import pystray
        from PIL import Image
    except ImportError:
        # pystray or Pillow not installed, fallback to simple loop
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=1.0)
        return

    def quit_action(icon, item):
        icon.stop()
        shutdown_event.set()

    def open_ui_action(icon, item):
        import subprocess
        # Try to launch the UI
        ui_script = Path(__file__).resolve().parent.parent / "koza_run.py"
        subprocess.Popen([sys.executable, str(ui_script), "ui"], 
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    try:
        # Load icon image
        icon_path = Path(__file__).resolve().parent.parent / "icon.ico"
        if icon_path.exists():
            image = Image.open(icon_path)
        else:
            # Create a dummy image if icon not found
            image = Image.new('RGB', (64, 64), color=(73, 109, 137))
            
        menu = pystray.Menu(
            pystray.MenuItem("Open Koza UI", open_ui_action, default=True),
            pystray.MenuItem("Quit", quit_action)
        )
        
        icon = pystray.Icon("koza_daemon", image, "Koza Services", menu)
        
        # We start a thread to monitor shutdown_event so we can stop the icon externally
        def monitor_shutdown():
            while not shutdown_event.is_set():
                shutdown_event.wait(timeout=1.0)
            icon.stop()
            
        threading.Thread(target=monitor_shutdown, daemon=True).start()
        
        # This is a blocking call and must run in the main thread on some platforms
        icon.run()
    except Exception as e:
        # Fallback if tray fails (e.g. no display server on linux)
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=1.0)
