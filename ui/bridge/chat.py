import json
import threading
import shutil
from pathlib import Path

class ChatMixin:
    def send_chat_message(self, message, image_path=None):
        """Asynchronously stream the agent's response to the client."""
        def run():
            try:
                full_response_tokens = []
                for event in self.agent.stream_chat(message, image_path=image_path):
                    if event.get("type") == "text":
                        full_response_tokens.append(event.get("token", ""))
                    if self.webview_window:
                        # Serialize and push event to Javascript
                        payload = json.dumps(event)
                        self.webview_window.evaluate_js(f"receiveChatEvent({payload})")
                
                # If voice mode is active, read the accumulated response out loud
                if getattr(self, "voice_loop_active", False):
                    full_response = "".join(full_response_tokens).strip()
                    if full_response:
                        if self.webview_window:
                            self.webview_window.evaluate_js("updateVoiceStatus('speaking')")
                        try:
                            from skills.voice import tts_speak_configured, normalize_voice_config
                            voice_cfg = normalize_voice_config(self.cfg)
                            output_device = voice_cfg.get("output_device")
                            tts_speak_configured(full_response, self.cfg, output_device=output_device)
                        except Exception as tts_err:
                            print(f"Voice TTS error: {tts_err}")
                        finally:
                            if self.webview_window:
                                self.webview_window.evaluate_js("updateVoiceStatus('listening')")
            except Exception as e:
                if self.webview_window:
                    err_event = json.dumps({"type": "error", "message": str(e)})
                    self.webview_window.evaluate_js(f"receiveChatEvent({err_event})")
            finally:
                if self.webview_window:
                    done_event = json.dumps({"type": "done"})
                    self.webview_window.evaluate_js(f"receiveChatEvent({done_event})")
                
                # Auto-save current session state
                try:
                    self.agent.auto_save()
                except Exception as ex:
                    print(f"Auto-save error: {ex}")
                
                # Spawn background self-improvement review asynchronously
                try:
                    from config import load_config
                    cfg_bg = load_config()
                    if cfg_bg.get("self_improvement", {}).get("enabled", True):
                        if self.agent.messages:
                            def _bg_review():
                                try:
                                    from skills.agents.evolution import run_self_improvement
                                    summary = run_self_improvement(cfg_bg["db_path"], self.agent.messages)
                                    print(f"Self-improvement review: {summary}")
                                except Exception as err:
                                    print(f"Self-improvement review error: {err}")
                            threading.Thread(target=_bg_review, daemon=True).start()
                except Exception as ex:
                    print(f"Failed to start self-improvement: {ex}")

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    def upload_file(self):
        """Open a native file dialog, copy the file to the workspace, and return its details."""
        if not self.webview_window:
            return {"status": "error", "message": "Window not initialized"}

        try:
            file_path = None
            import os
            
            # On Windows, use tkinter first to avoid pywebview's buggy WinForms dialog UnboundLocalError
            if os.name == 'nt':
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.withdraw()  # Hide the main tk window
                    root.attributes('-topmost', True)  # Show dialog on top
                    file_path = filedialog.askopenfilename(parent=root, title="Select File")
                    root.destroy()
                except Exception as tk_err:
                    print(f"[GUI] Tkinter dialog failed: {tk_err}, falling back to pywebview")
            
            if not file_path:
                # Fallback to pywebview's create_file_dialog
                result = self.webview_window.create_file_dialog(
                    dialog_type=0,
                    allow_multiple=False,
                    file_types=('All files (*.*)',)
                )
                if not result or len(result) == 0:
                    return {"status": "cancel"}
                file_path = result[0]

            if not file_path:
                return {"status": "cancel"}
            src = Path(file_path)
            
            # Find the active workspace directory
            workspace = self.cfg.get("workspace_path")
            if not workspace:
                workspace = str(Path.home() / ".Koza" / "workspace")
            
            dest_dir = Path(workspace)
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Ensure unique filename to prevent accidental collision
            dest_path = dest_dir / src.name
            
            # Copy file
            shutil.copy2(src, dest_path)
            
            # Check if it's an image
            is_image = src.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')
            
            return {
                "status": "success",
                "file": {
                    "name": src.name,
                    "path": str(dest_path.resolve()),
                    "is_image": is_image
                }
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def interrupt_chat(self):
        self.agent.interrupt()
        return {"status": "interrupted"}

    def reset_chat(self):
        self.agent.reset()
        self.agent._active_session_id = None
        return {"status": "reset"}

    def get_chat_history(self):
        """Returns the current conversation messages for the UI to display on load."""
        messages = []
        for msg in self.agent.messages:
            if msg.get("role") == "system":
                continue
            messages.append(msg)
        return {"status": "success", "messages": messages}
