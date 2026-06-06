import json
import threading

class ChatMixin:
    def send_chat_message(self, message):
        """Asynchronously stream the agent's response to the client."""
        def run():
            try:
                for event in self.agent.stream_chat(message):
                    if self.webview_window:
                        # Serialize and push event to Javascript
                        payload = json.dumps(event)
                        self.webview_window.evaluate_js(f"receiveChatEvent({payload})")
            except Exception as e:
                if self.webview_window:
                    err_event = json.dumps({"type": "error", "message": str(e)})
                    self.webview_window.evaluate_js(f"receiveChatEvent({err_event})")
            finally:
                if self.webview_window:
                    done_event = json.dumps({"type": "done"})
                    self.webview_window.evaluate_js(f"receiveChatEvent({done_event})")

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    def interrupt_chat(self):
        self.agent.interrupt()
        return {"status": "interrupted"}

    def reset_chat(self):
        self.agent.reset()
        return {"status": "reset"}
