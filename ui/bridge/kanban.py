import skills.kanban as kanban
import skills.session_memory as session_memory

class KanbanMixin:
    def get_kanban_tasks(self):
        try:
            # Query the DB directly to get parsed dicts instead of formatted string
            with session_memory._conn() as conn:
                rows = conn.execute(
                    "SELECT id, title, description, column, created_at, updated_at, agent_id FROM kanban_tasks ORDER BY id"
                ).fetchall()
            tasks = []
            for r in rows:
                tasks.append({
                    "id": r[0],
                    "title": r[1],
                    "description": r[2],
                    "column": r[3],
                    "created_at": r[4],
                    "updated_at": r[5],
                    "agent_id": r[6]
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
