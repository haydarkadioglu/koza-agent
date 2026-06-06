import json
import threading
from config import load_config, save_config
from providers.factory import get_provider
from core import Agent

class ConfigMixin:
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
                if self.webview_window:
                    res = json.dumps({"status": "success" if success else "failed"})
                    self.webview_window.evaluate_js(f"onOAuthCompleted({res})")
            except Exception as e:
                if self.webview_window:
                    res = json.dumps({"status": "error", "message": str(e)})
                    self.webview_window.evaluate_js(f"onOAuthCompleted({res})")
        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    def run_gemini_browser_login(self):
        """Start Playwright Gemini browser session in a background thread."""
        def run():
            try:
                from cli.setup_helpers import _playwright_gemini_login
                _playwright_gemini_login()
                if self.webview_window:
                    self.webview_window.evaluate_js("onGeminiBrowserLoginCompleted({\"status\": \"success\"})")
            except Exception as e:
                if self.webview_window:
                    res = json.dumps({"status": "error", "message": str(e)})
                    self.webview_window.evaluate_js(f"onGeminiBrowserLoginCompleted({res})")
        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    def get_daemon_status(self):
        """Return whether background daemon services are running."""
        try:
            from koza_daemon import get_daemon_port, PID_FILE
            port = get_daemon_port()
            active = port is not None
            pid = None
            if active and PID_FILE.exists():
                try:
                    pid = int(PID_FILE.read_text().strip())
                except Exception:
                    pass
            return {"status": "success", "active": active, "pid": pid}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def toggle_daemon(self, enable):
        """Start or stop the background services daemon."""
        try:
            if enable:
                from koza_daemon import start_as_background
                success = start_as_background()
                return {"status": "success" if success else "error", "message": "Daemon started" if success else "Failed to start daemon"}
            else:
                from cli.daemon import cmd_quit
                cmd_quit([])
                return {"status": "success", "message": "Daemon stopped"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
