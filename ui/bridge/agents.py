import json
import time
import logging
from skills.agents.background import BackgroundTaskManager, TaskStatus
from skills.agents._registry import _subagents
from skills.agents import spawn_subagent, start_tracked_coding_task

logger = logging.getLogger(__name__)

class AgentsMixin:
    def get_background_tasks(self):
        try:
            tasks = []
            # 1. Fetch CodingSession tasks from DB
            try:
                from skills.agents.background import _conn
                with _conn() as conn:
                    rows = conn.execute(
                        "SELECT id, goal, status, created_at, started_at, finished_at, current_persona FROM background_tasks ORDER BY id DESC"
                    ).fetchall()
                for r in rows:
                    elapsed = 0.0
                    if r["started_at"]:
                        end = r["finished_at"] or time.time()
                        elapsed = end - r["started_at"]
                    tasks.append({
                        "id": r["id"],
                        "type": "coding",
                        "goal": r["goal"],
                        "status": r["status"],
                        "elapsed_seconds": round(elapsed, 1),
                        "current_persona": r["current_persona"] or "",
                    })
            except Exception as e:
                logger.error(f"Error querying background_tasks: {e}")

            # 2. Fetch subagents
            bg_ids = {t["id"] for t in tasks}
            for ag in _subagents.values():
                if ag["id"] not in bg_ids:
                    elapsed = round(time.time() - ag.get("started", time.time()), 1)
                    tasks.append({
                        "id": ag["id"],
                        "type": "subagent",
                        "goal": ag.get("goal", ""),
                        "status": ag.get("status", "pending"),
                        "elapsed_seconds": elapsed,
                        "current_persona": "",
                    })
            return {"status": "success", "data": tasks}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_background_task_details(self, task_id):
        try:
            # 1. First check if it is a CodingSession task in memory
            from skills.agents.background import _background_tasks, _tasks_lock
            with _tasks_lock:
                task = _background_tasks.get(task_id)
            
            if task:
                # Get events from memory
                events = task.event_queue.get_last_n(200)
                logs = []
                for ev in events:
                    etype = ev.get("type", "")
                    if etype == "status":
                        logs.append(f"[{ev.get('persona', '')}] {ev.get('message', '')}")
                    elif etype == "persona_tool":
                        phase = ev.get("phase", "")
                        logs.append(f"  Tool: {ev.get('tool', '')} ({phase})")
                    elif etype == "done":
                        logs.append(f"✓ Done: {ev.get('summary', '')}")
                    elif etype == "error_recorded":
                        logs.append(f"⚠ Error: {ev.get('error', {}).get('description', '')}")
                
                # Check for output/summary
                summary = task.summary
                if not summary and task.status == TaskStatus.DONE:
                    summary = "Done"
                elif not summary and task.error_message:
                    summary = f"Error: {task.error_message}"

                return {
                    "status": "success",
                    "data": {
                        "id": task.id,
                        "type": "coding",
                        "goal": task.goal,
                        "status": task.status.value,
                        "logs": "\n".join(logs),
                        "summary": summary or task.error_message or ""
                    }
                }
            
            # 2. Check database for background_tasks
            try:
                from skills.agents.background import _conn
                with _conn() as conn:
                    row = conn.execute(
                        "SELECT id, goal, status, summary, error_message FROM background_tasks WHERE id = ?",
                        (task_id,)
                    ).fetchone()
                if row:
                    summary = row["summary"]
                    if not summary and row["status"] == "error":
                        summary = f"Error: {row['error_message']}"
                    return {
                        "status": "success",
                        "data": {
                            "id": row["id"],
                            "type": "coding",
                            "goal": row["goal"],
                            "status": row["status"],
                            "logs": summary or row["error_message"] or "",
                            "summary": summary or row["error_message"] or ""
                        }
                    }
            except Exception as e:
                logger.error(f"Error querying background_tasks details: {e}")

            # 3. Check subagents registry
            ag = _subagents.get(task_id)
            if ag:
                # Format subagent messages as logs
                logs = []
                for msg in ag.get("messages", []):
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    tool_calls = msg.get("tool_calls", None)
                    if role == "user":
                        logs.append(f"[User/Goal]: {content}")
                    elif role == "assistant":
                        if content:
                            logs.append(f"[Agent]: {content}")
                        if tool_calls:
                            for tc in tool_calls:
                                func = tc.get("function", {})
                                logs.append(f"  [Tool Call]: {func.get('name')}({func.get('arguments')})")
                    elif role == "tool":
                        name = msg.get("name", "")
                        logs.append(f"  [Tool Result ({name})]: {content[:400]}")
                
                # If no logs but goal exists
                if not logs:
                    logs.append(f"[Goal]: {ag.get('goal', '')}")
                    
                result = ag.get("result", "")
                if result:
                    logs.append(f"\n[Final Result]:\n{result}")

                return {
                    "status": "success",
                    "data": {
                        "id": ag.get("id"),
                        "type": "subagent",
                        "goal": ag.get("goal"),
                        "status": ag.get("status"),
                        "logs": "\n".join(logs),
                        "summary": result
                    }
                }

            return {"status": "error", "message": f"Task {task_id} not found."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def cancel_background_task(self, task_id):
        try:
            res = BackgroundTaskManager.cancel_task(task_id)
            if res:
                return {"status": "success", "message": f"Cancellation requested for task {task_id}."}
            return {"status": "error", "message": f"Task {task_id} could not be cancelled or not found."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def start_background_task(self, goal, mode="subagent", checklist="", capabilities=""):
        try:
            if mode == "coding":
                # Start tracked coding task
                res = start_tracked_coding_task(goal, checklist=checklist, followup_minutes=10, capabilities=capabilities)
                return {"status": "success", "message": res}
            else:
                # Spawn subagent in background
                res = spawn_subagent(goal, capabilities=capabilities, wait=False)
                return {"status": "success", "message": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def run_kanban_task(self, task_id, capabilities=""):
        try:
            from skills.kanban import run_kanban_task
            res = run_kanban_task(int(task_id), capabilities)
            if res.startswith("ERROR"):
                return {"status": "error", "message": res}
            return {"status": "success", "message": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}
