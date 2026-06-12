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

    def has_api_key(self, provider):
        """Return whether a real (non-empty) API key is saved for a provider."""
        try:
            cfg = load_config()
            key = cfg.get("providers", {}).get(provider, {}).get("api_key", "")
            return {"has_key": bool(key and key.strip())}
        except Exception as e:
            return {"has_key": False, "error": str(e)}

    def test_api_key(self, provider, api_key):
        """Test whether the given API key works for the specified provider.
        Saves the key first, then makes a minimal test call, reverts on failure."""
        try:
            cfg = load_config()
            old_key = cfg.get("providers", {}).get(provider, {}).get("api_key", "")
            # Temporarily write the key so get_provider uses it
            cfg.setdefault("providers", {}).setdefault(provider, {})["api_key"] = api_key
            save_config(cfg)

            # Resolve the internal provider name
            provider_name_map = {
                "gemini api": "gemini",
                "gemini cli": "gemini",
            }
            test_provider = provider_name_map.get(provider, provider)

            try:
                test_cfg = dict(cfg)
                test_cfg["provider"] = provider
                prov = get_provider(test_cfg)
                # Make a cheap single-token call
                result = ""
                for event in prov.stream_chat([{"role": "user", "content": "Hi"}], {}):
                    if isinstance(event, dict) and event.get("type") == "text":
                        result += event.get("token", "")
                    if len(result) > 0:
                        break
                return {"status": "success", "message": "Connection successful ✓"}
            except Exception as e:
                # Revert key on failure
                cfg.setdefault("providers", {}).setdefault(provider, {})["api_key"] = old_key
                save_config(cfg)
                return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

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

    def update_provider_and_model(self, provider, model):
        """Update both provider and model and reinitialize the agent once."""
        try:
            self.cfg = load_config()
            self.cfg["provider"] = provider
            self.cfg["model"] = model
            save_config(self.cfg)
            
            p = get_provider(self.cfg)
            self.agent = Agent(p, db_path=self.db_path, cfg=self.cfg, channel="gui")
            self.agent.permission_callback = self._gui_permission_callback
            
            return {"status": "success", "message": "Provider and model updated successfully"}
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

    def get_google_oauth_status(self):
        """Check if Google OAuth is connected and return email/project status."""
        try:
            from providers.google_oauth_provider import _load_tokens
            tokens = _load_tokens()
            if tokens:
                refresh = tokens.get("refresh", "")
                project_id = ""
                if "|" in refresh:
                    project_id = refresh.split("|")[1]
                return {
                    "connected": True,
                    "email": tokens.get("email", "unknown"),
                    "project_id": project_id
                }
            return {"connected": False}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    def logout_google_oauth(self):
        """Disconnect Google OAuth and delete tokens."""
        try:
            from providers.google_oauth_provider import TOKEN_PATH
            if TOKEN_PATH.exists():
                TOKEN_PATH.unlink()
            return {"status": "success"}
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

    def get_anthropic_oauth_status(self):
        """Check if Anthropic OAuth is connected and return status."""
        try:
            from providers.anthropic_oauth_provider import _load_tokens
            tokens = _load_tokens()
            if tokens:
                return {
                    "connected": True,
                    "email": tokens.get("email", "connected")
                }
            return {"connected": False}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    def logout_anthropic_oauth(self):
        """Disconnect Anthropic OAuth and delete tokens."""
        try:
            from providers.anthropic_oauth_provider import TOKEN_PATH
            if TOKEN_PATH.exists():
                TOKEN_PATH.unlink()
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def run_anthropic_oauth(self):
        """Start Anthropic OAuth login in a background thread."""
        def run():
            try:
                from providers.anthropic_oauth_provider import run_oauth_login
                success = run_oauth_login()
                if self.webview_window:
                    res = json.dumps({"status": "success" if success else "failed"})
                    self.webview_window.evaluate_js(f"onAnthropicOAuthCompleted({res})")
            except Exception as e:
                if self.webview_window:
                    res = json.dumps({"status": "error", "message": str(e)})
                    self.webview_window.evaluate_js(f"onAnthropicOAuthCompleted({res})")
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
