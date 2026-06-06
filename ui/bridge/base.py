import json
import threading
from pathlib import Path

from config import load_config, save_config
from providers.factory import get_provider
from core import Agent
import skills.kanban as kanban
import skills.session_memory as session_memory

class BridgeBase:
    def __init__(self):
        self.cfg = load_config()
        self.db_path = self.cfg["db_path"]
        
        # Initialize DBs
        kanban.init_db(self.db_path)
        session_memory.init_db(self.db_path)
        
        # Instantiate Agent
        provider = get_provider(self.cfg)
        self.agent = Agent(provider, db_path=self.db_path, cfg=self.cfg, channel="gui")
        
        # UI Permission callbacks
        self.agent.permission_callback = self._gui_permission_callback
        
        # Permission state tracking
        self._perm_event = threading.Event()
        self._perm_allowed = False
        self.webview_window = None  # To be set after creating the webview window

    def _gui_permission_callback(self, name: str, args: dict) -> bool:
        """Called by the agent thread when a tool requires permission."""
        if not self.cfg.get("tool_approval", False):
            return True
            
        from cli.permissions import SAFE_TOOLS
        if name in SAFE_TOOLS:
            return True
            
        self._perm_event.clear()
        self._perm_allowed = False
        
        # Trigger modal in the frontend
        if self.webview_window:
            payload = json.dumps({"name": name, "args": args})
            self.webview_window.evaluate_js(f"requestToolPermission({payload})")
            
        # Wait for user input from GUI (timeout after 120 seconds)
        success = self._perm_event.wait(timeout=120)
        return self._perm_allowed if success else False

    def resolve_permission(self, allowed: bool):
        """Called by JS to resume the blocked agent thread."""
        self._perm_allowed = allowed
        self._perm_event.set()
