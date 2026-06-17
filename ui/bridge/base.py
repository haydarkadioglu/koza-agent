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
        
        # Auto-load the most recent session history
        last_session = session_memory.load_last_session()
        if last_session:
            sys_msg = self.agent.messages[0] if self.agent.messages and self.agent.messages[0].get("role") == "system" else None
            self.agent.messages = ([sys_msg] if sys_msg else []) + last_session
            
            # Set the active session ID so auto-save updates the same session
            rows = session_memory.get_session_rows(limit=1)
            if rows:
                self.agent._active_session_id = rows[0]["id"]
        
        # UI Permission callbacks
        self.agent.permission_callback = self._gui_permission_callback
        
        # Permission state tracking
        self._perm_event = threading.Event()
        self._perm_allowed = False
        self._turbo_mode = False
        self.webview_window = None  # To be set after creating the webview window

    def _gui_permission_callback(self, name: str, args: dict) -> bool:
        """Called by the agent thread when a tool requires permission."""
        if getattr(self, "_turbo_mode", False):
            return True
            
        if not self.cfg.get("tool_approval", False):
            return True
            
        from cli.permissions import SAFE_TOOLS
        if name in SAFE_TOOLS:
            return True
            
        self._perm_event.clear()
        self._perm_allowed = False
        self._perm_args = None
        
        # Trigger modal in the frontend
        if self.webview_window:
            payload = json.dumps({"name": name, "args": args})
            self.webview_window.evaluate_js(f"requestToolPermission({payload})")
            
        # Wait for user input from GUI (timeout after 120 seconds)
        success = self._perm_event.wait(timeout=120)
        if success and self._perm_allowed:
            if self._perm_args is not None:
                # Update arguments in-place
                args.clear()
                args.update(self._perm_args)
            return True
        return False

    def resolve_permission(self, allowed: bool, edited_args_json: str = None):
        """Called by JS to resume the blocked agent thread."""
        self._perm_allowed = allowed
        if allowed and edited_args_json:
            try:
                self._perm_args = json.loads(edited_args_json)
            except Exception:
                self._perm_args = None
        else:
            self._perm_args = None
        self._perm_event.set()

    def set_turbo_mode(self, enabled: bool):
        """Called by JS to toggle auto-allow for all tools."""
        self._turbo_mode = enabled
        return {"status": "success", "enabled": enabled}
