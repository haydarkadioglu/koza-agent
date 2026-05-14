# Kanban & Cron

Koza has built-in task management (Kanban) and job scheduling (Cron) — both backed by SQLite and accessible from the TUI or via chat.

---

## Kanban

### Opening the Board
```bash
python main.py kanban
```

Or press the **Kanban** button in the TUI sidebar.

### Columns
| Column | Meaning |
|---|---|
| `todo` | Not started |
| `doing` | In progress |
| `done` | Completed |

### Tools (usable via chat)
| Tool | Description |
|---|---|
| `create_task(title, notes, column)` | Create a task in any column |
| `list_tasks()` | List all tasks with their status |
| `move_task(task_id, column)` | Move a task to todo/doing/done |
| `update_task(task_id, title, notes)` | Edit a task |
| `delete_task(task_id)` | Delete a task |

### Example
```
You: Create a task to write unit tests for the auth module
Koza: [calls create_task] ✅ Task #7 created: "Write unit tests for auth module" [todo]

You: Move task 7 to doing
Koza: [calls move_task] ✅ Task #7 → doing
```

### Data Storage
All tasks are stored in `~/.koza/koza.db` in the `kanban_tasks` table.

---

## Cron

Koza can schedule recurring jobs — stored in SQLite, registered with **APScheduler** for in-process execution, and optionally synced to the OS native scheduler.

### How It Works

```
create_cron("daily news", "fetch and summarize news", "0 9 * * *")
         │
         ├─ 1. Saved to kanban_tasks table (SQLite)
         ├─ 2. Registered with APScheduler (runs in-process)
         └─ 3. Synced to OS:
                 Linux/macOS → crontab
                 Windows     → Task Scheduler (schtasks)
```

### Cron Expression Format

```
┌──────── minute (0–59)
│ ┌─────── hour (0–23)
│ │ ┌────── day of month (1–31)
│ │ │ ┌───── month (1–12)
│ │ │ │ ┌──── day of week (0–6, Sun=0)
│ │ │ │ │
* * * * *
```

Common examples:

| Expression | Meaning |
|---|---|
| `0 9 * * *` | Every day at 09:00 |
| `*/15 * * * *` | Every 15 minutes |
| `0 8 * * 1` | Every Monday at 08:00 |
| `0 0 1 * *` | First day of every month at midnight |

### Tools
| Tool | Description |
|---|---|
| `create_cron(name, command, cron_expr, sync_system=True)` | Schedule a job |
| `list_crons()` | List all scheduled jobs |
| `delete_cron(job_id)` | Delete a job (also removes from OS scheduler) |

### Example via chat
```
You: Every day at 9am, search for AI news and summarize the top 5 stories
Koza: [calls create_cron]
        ✅ Cron job created (id=3): 'AI news summary' [0 9 * * *]
        → search for AI news and summarize the top 5 stories
        Also synced to Windows Task Scheduler as 'Koza_3_AI_news_summary'
```

### Disabling OS Sync
If you only want APScheduler (no OS scheduler sync):
```
create_cron(name, command, cron_expr, sync_system=False)
```

### Viewing Jobs
```bash
# Via chat
You: List my cron jobs

# Or check directly in the Kanban TUI
python main.py kanban
```

### Data Storage
Cron jobs: `~/.koza/koza.db` → `cron_jobs` table

### Windows Notes
- Cron expressions are translated to `schtasks` format
- Task names are prefixed with `Koza_<id>_`
- Requires PowerShell 7 (`pwsh`) for command execution

### Linux/macOS Notes
- Each job is added as a line in the user's crontab with a `# koza-cron-<id>` marker
- Deleting via Koza also removes the crontab entry
