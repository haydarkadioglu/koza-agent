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

    def get_app_version(self):
        """Returns the current Koza version."""
        try:
            from cli.ui import _get_version
            return {"status": "success", "version": _get_version()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def check_for_updates(self):
        """Check for updates on GitHub."""
        try:
            from cli.update_cmd import _check_latest_version
            latest, current = _check_latest_version()
            if not latest:
                return {
                    "status": "success",
                    "current": current,
                    "latest": current,
                    "update_available": False,
                    "message": "Could not check latest version (offline or API rate limit)."
                }
            from packaging.version import Version
            update_available = Version(latest) > Version(current)
            return {
                "status": "success",
                "current": current,
                "latest": latest,
                "update_available": update_available
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def update_app(self):
        """Performs a robust self-update by pulling from git and reinstalling packages."""
        try:
            import subprocess
            import sys
            import shutil
            
            project_dir = Path(__file__).resolve().parent.parent.parent
            git = shutil.which("git")
            
            if not git:
                return {"status": "error", "message": "git executable not found on system path."}
            
            # 1. Pull changes using autostash to preserve local modifications
            try:
                # Try pull with rebase and autostash
                git_result = subprocess.run(
                    [git, "pull", "--rebase", "--autostash"],
                    capture_output=True, text=True, cwd=str(project_dir), timeout=20
                )
                if git_result.returncode != 0:
                    # Fallback to standard git pull if autostash isn't supported or fails
                    git_result = subprocess.run(
                        [git, "pull"],
                        capture_output=True, text=True, cwd=str(project_dir), timeout=20
                    )
                
                git_output = f"STDOUT:\n{git_result.stdout}\nSTDERR:\n{git_result.stderr}"
                if git_result.returncode != 0:
                    return {"status": "error", "message": f"Git pull failed:\n{git_output}"}
            except Exception as e:
                return {"status": "error", "message": f"Git pull error: {str(e)}"}
            
            # 2. Reinstall package to check/resolve dependencies
            pip_installed = False
            pip_error = ""
            try:
                # Run pip install -e . to update dependencies
                pip_cmd = [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"]
                
                if sys.platform != "win32":
                    # For Linux/Mac, try standard first
                    pip_res = subprocess.run(pip_cmd, capture_output=True, text=True, cwd=str(project_dir), timeout=60)
                    if pip_res.returncode != 0 and "externally-managed-environment" in pip_res.stderr:
                        # Try with break system packages
                        pip_res = subprocess.run(
                            pip_cmd + ["--break-system-packages"],
                            capture_output=True, text=True, cwd=str(project_dir), timeout=60
                        )
                    pip_installed = (pip_res.returncode == 0)
                    if not pip_installed:
                        pip_error = pip_res.stderr
                else:
                    # Windows: files might be locked, so we run a detached process that installs in the background
                    import time
                    ps_cmd = f"Start-Sleep -Seconds 2; & '{sys.executable}' -m pip install -e '{project_dir}' --quiet"
                    subprocess.Popen(
                        ["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                    pip_installed = True  # assumed started successfully
            except Exception as e:
                pip_error = str(e)
            
            msg = f"Code pulled successfully from GitHub.\n\n{git_output.strip()}"
            if pip_installed:
                if sys.platform == "win32":
                    msg += "\n\nDependency updates are being applied in the background (Windows)."
                else:
                    msg += "\n\nDependencies and packages updated successfully."
            else:
                msg += f"\n\nWarning: Could not update dependencies automatically: {pip_error}\nYou may need to run 'pip install -e .' manually."
                
            return {"status": "success", "message": msg}
        except Exception as e:
            return {"status": "error", "message": str(e)}
