"""Kanban TUI screen — standalone Kanban board view."""
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Label, Input, Button, Static
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual import on

from skills.kanban import list_tasks, create_task, move_task, delete_task, HANDLERS as kanban_handlers
from skills.cron import list_crons


COLUMN_ORDER = ["todo", "in_progress", "done", "auto"]
COLUMN_LABELS = {
    "todo": "📋 TODO",
    "in_progress": "⚙️  IN PROGRESS",
    "done": "✅ DONE",
    "auto": "🕐 AUTO (CRON)",
}
COLUMN_COLORS = {
    "todo": "cyan",
    "in_progress": "yellow",
    "done": "green",
    "auto": "magenta",
}


class KanbanApp(App):
    CSS = """
    Screen { background: $background; }
    #board { height: 1fr; layout: horizontal; }
    .column {
        width: 1fr;
        border: round $accent;
        margin: 0 1;
        padding: 0 1;
        height: 100%;
    }
    .col_title { text-align: center; text-style: bold; margin-bottom: 1; }
    .task_item { padding: 0 1; margin-bottom: 1; border: solid $surface-lighten-1; }
    #add_bar {
        height: 5;
        border: round $surface;
        margin: 0 1;
        padding: 1 2;
        dock: bottom;
    }
    #add_bar Input { width: 1fr; }
    #add_bar Button { width: 12; margin-left: 1; }
    #status { height: 1; dock: bottom; padding: 0 2; color: $text-muted; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="board"):
            for col in COLUMN_ORDER:
                with Vertical(classes="column", id=f"col_{col}"):
                    yield Label(COLUMN_LABELS[col], classes="col_title")
        with Horizontal(id="add_bar"):
            yield Input(placeholder="New task title...", id="new_task_input")
            yield Button("Add Task", variant="primary", id="add_task_btn")
            yield Button("Refresh", id="refresh_btn")
        yield Label("Press R to refresh | Ctrl+C to quit", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._render_board()

    def _render_board(self) -> None:
        import sqlite3
        from pathlib import Path
        from skills.kanban import _db_path, _conn

        for col in COLUMN_ORDER:
            container = self.query_one(f"#col_{col}", Vertical)
            # Remove old task widgets (keep the title label)
            for w in list(container.children)[1:]:
                w.remove()

        try:
            with _conn() as conn:
                rows = conn.execute(
                    "SELECT id, title, description, column FROM kanban_tasks ORDER BY id"
                ).fetchall()
        except Exception:
            rows = []

        for row in rows:
            task_id, title, desc, col = row
            if col not in COLUMN_ORDER:
                col = "todo"
            color = COLUMN_COLORS.get(col, "white")
            container = self.query_one(f"#col_{col}", Vertical)
            container.mount(
                Static(
                    f"[{color}]#{task_id}[/] {title}\n[dim]{desc[:50]}[/]",
                    classes="task_item",
                )
            )

        # Also add cron jobs to auto column
        try:
            from skills.cron import _db_path as cron_db, _conn as cron_conn
            with cron_conn() as conn:
                cron_rows = conn.execute("SELECT id, name, cron_expr FROM cron_jobs ORDER BY id").fetchall()
            container = self.query_one("#col_auto", Vertical)
            for r in cron_rows:
                container.mount(
                    Static(
                        f"[magenta]⏰ #{r[0]}[/] {r[1]}\n[dim]{r[2]}[/]",
                        classes="task_item",
                    )
                )
        except Exception:
            pass

    @on(Button.Pressed, "#add_task_btn")
    def add_task_pressed(self) -> None:
        title = self.query_one("#new_task_input", Input).value.strip()
        if title:
            create_task(title)
            self.query_one("#new_task_input", Input).clear()
            self._render_board()

    @on(Button.Pressed, "#refresh_btn")
    def refresh_pressed(self) -> None:
        self._render_board()

    def action_refresh(self) -> None:
        self._render_board()
