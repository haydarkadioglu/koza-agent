import os
import sys
import json
import threading
from pathlib import Path

# Add project root to path so we can import modules
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import load_config, save_config
from providers.factory import get_provider
from core import Agent
import skills.kanban as kanban
import skills.session_memory as session_memory

# Global references
webview_window = None
agent_instance = None

class KozaBridge:
    def __init__(self):
        self.cfg = load_config()
        self.db_path = self.cfg["db_path"]
        
        # Initialize DBs
        kanban.init_db(self.db_path)
        session_memory.init_db(self.db_path)
        
        # Instantiate Agent
        provider = get_provider(self.cfg)
        self.agent = Agent(provider, db_path=self.db_path, cfg=self.cfg, channel="gui")
        
        # Disable CLI permissions prompt for GUI, or we can add a visual callback!
        # Let's write a simple callback that evaluates JS to ask the user on the screen.
        self.agent.permission_callback = self._gui_permission_callback
        
        # Permission state tracking
        self._perm_event = threading.Event()
        self._perm_allowed = False

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
        if webview_window:
            payload = json.dumps({"name": name, "args": args})
            webview_window.evaluate_js(f"requestToolPermission({payload})")
            
        # Wait for user input from GUI (timeout after 120 seconds)
        success = self._perm_event.wait(timeout=120)
        return self._perm_allowed if success else False

    def resolve_permission(self, allowed: bool):
        """Called by JS to resume the blocked agent thread."""
        self._perm_allowed = allowed
        self._perm_event.set()

    def get_config(self):
        self.cfg = load_config()
        # Clean config to mask keys for display
        display_cfg = json.loads(json.dumps(self.cfg))
        # Mask API keys
        providers = display_cfg.get("providers", {})
        for p, details in providers.items():
            for key in ("api_key", "token", "auth_token"):
                if key in details and details[key]:
                    details[key] = "********"
        return display_cfg

    def get_providers_metadata(self):
        """Return the CLI provider lists and model catalogs."""
        try:
            from cli.setup_constants import PROVIDERS, PROVIDER_MODELS, NEEDS_KEY
            return {
                "status": "success",
                "providers": PROVIDERS,
                "models": PROVIDER_MODELS,
                "needs_key": list(NEEDS_KEY)
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def update_config_value(self, section, key, value):
        """Update a specific configuration value and save it."""
        try:
            self.cfg = load_config()
            if section == "root":
                self.cfg[key] = value
            elif section in self.cfg:
                self.cfg[section][key] = value
            save_config(self.cfg)
            
            # Reinit agent if provider changed
            if key == "provider" or key == "model":
                provider = get_provider(self.cfg)
                self.agent = Agent(provider, db_path=self.db_path, cfg=self.cfg, channel="gui")
                self.agent.permission_callback = self._gui_permission_callback
                
            return {"status": "success", "message": "Config updated successfully"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def update_nested_config(self, dot_path, value):
        """Set a value in config.yaml using a dot-separated path (e.g. 'providers.openai.api_key')."""
        try:
            self.cfg = load_config()
            parts = dot_path.split('.')
            target = self.cfg
            for part in parts[:-1]:
                if part not in target or not isinstance(target[part], dict):
                    target[part] = {}
                target = target[part]
            target[parts[-1]] = value
            save_config(self.cfg)
            return {"status": "success", "message": f"Config {dot_path} updated"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def run_google_oauth(self):
        """Start Google OAuth login in a background thread."""
        def run():
            try:
                from providers.google_oauth_provider import run_oauth_login
                success = run_oauth_login()
                if webview_window:
                    res = json.dumps({"status": "success" if success else "failed"})
                    webview_window.evaluate_js(f"onOAuthCompleted({res})")
            except Exception as e:
                if webview_window:
                    res = json.dumps({"status": "error", "message": str(e)})
                    webview_window.evaluate_js(f"onOAuthCompleted({res})")
        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    def run_gemini_browser_login(self):
        """Start Playwright Gemini browser session in a background thread."""
        def run():
            try:
                from cli.setup_helpers import _playwright_gemini_login
                _playwright_gemini_login()
                if webview_window:
                    webview_window.evaluate_js("onGeminiBrowserLoginCompleted({\"status\": \"success\"})")
            except Exception as e:
                if webview_window:
                    res = json.dumps({"status": "error", "message": str(e)})
                    webview_window.evaluate_js(f"onGeminiBrowserLoginCompleted({res})")
        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}


    def get_sessions(self):
        try:
            rows = session_memory.get_session_rows(limit=50)
            return {"status": "success", "data": rows}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def load_session(self, session_id):
        try:
            session_id = int(session_id)
            msgs = session_memory.load_session(session_id)
            # Restore messages into agent
            sys_msg = self.agent.messages[0] if self.agent.messages and self.agent.messages[0].get("role") == "system" else None
            self.agent.messages = ([sys_msg] if sys_msg else []) + msgs
            self.agent._context_summary = ""
            
            # Filter user/assistant messages for presentation
            chat_history = [m for m in msgs if m.get("role") in ("user", "assistant")]
            return {"status": "success", "data": chat_history}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_session(self, session_id):
        try:
            session_id = int(session_id)
            res = session_memory.delete_session(session_id)
            return {"status": "success", "message": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_kanban_tasks(self):
        try:
            # Query the DB directly to get parsed dicts instead of formatted string
            with session_memory._conn() as conn:
                rows = conn.execute(
                    "SELECT id, title, description, column, created_at, updated_at FROM kanban_tasks ORDER BY id"
                ).fetchall()
            tasks = []
            for r in rows:
                tasks.append({
                    "id": r[0],
                    "title": r[1],
                    "description": r[2],
                    "column": r[3],
                    "created_at": r[4],
                    "updated_at": r[5]
                })
            return {"status": "success", "data": tasks}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def create_kanban_task(self, title, description="", column="todo"):
        try:
            res = kanban.create_task(title, description, column)
            return {"status": "success", "message": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def move_kanban_task(self, task_id, column):
        try:
            res = kanban.move_task(int(task_id), column)
            return {"status": "success", "message": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_kanban_task(self, task_id):
        try:
            res = kanban.delete_task(int(task_id))
            return {"status": "success", "message": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def send_chat_message(self, message):
        """Asynchronously stream the agent's response to the client."""
        def run():
            try:
                for event in self.agent.stream_chat(message):
                    if webview_window:
                        # Serialize and push event to Javascript
                        payload = json.dumps(event)
                        webview_window.evaluate_js(f"receiveChatEvent({payload})")
            except Exception as e:
                if webview_window:
                    err_event = json.dumps({"type": "error", "message": str(e)})
                    webview_window.evaluate_js(f"receiveChatEvent({err_event})")
            finally:
                if webview_window:
                    done_event = json.dumps({"type": "done"})
                    webview_window.evaluate_js(f"receiveChatEvent({done_event})")

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    def interrupt_chat(self):
        self.agent.interrupt()
        return {"status": "interrupted"}

    def reset_chat(self):
        self.agent.reset()
        return {"status": "reset"}

    def get_audio_devices(self):
        """Retrieve deduplicated list of audio input (mic) and output (speaker) devices."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            default_in  = sd.default.device[0]
            default_out = sd.default.device[1]
            
            seen_in, seen_out = set(), set()
            input_opts = []
            output_opts = []
            
            for i, d in enumerate(devices):
                name = d.get("name", "")
                if d.get("max_input_channels", 0) > 0 and name not in seen_in:
                    seen_in.add(name)
                    input_opts.append({"name": name, "id": i, "is_default": (i == default_in)})
                if d.get("max_output_channels", 0) > 0 and name not in seen_out:
                    seen_out.add(name)
                    output_opts.append({"name": name, "id": i, "is_default": (i == default_out)})
                    
            return {
                "status": "success",
                "input": input_opts,
                "output": output_opts
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}



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
    
    # Run the native webview application
    webview.start(debug=True)

if __name__ == "__main__":
    start_gui()
