import skills.session_memory as session_memory

class SessionMixin:
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
            self.agent._active_session_id = session_id
            
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
