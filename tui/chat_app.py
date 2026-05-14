"""Main Chat TUI — Textual-powered interactive chat with Koza Agent."""
import threading
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Label, TabbedContent, TabPane
from textual.containers import Container, Vertical, Horizontal
from textual import on, work
from textual.reactive import reactive

from core import Agent


class ChatApp(App):
    CSS = """
    Screen { background: $background; }
    #chat_log {
        border: round $accent;
        height: 1fr;
        margin: 0 1;
        padding: 0 1;
    }
    #tool_log {
        border: round $warning;
        height: 1fr;
        margin: 0 1;
        padding: 0 1;
        color: $warning;
    }
    #input_bar {
        height: 3;
        margin: 0 1 1 1;
        dock: bottom;
    }
    #input_bar Input { width: 1fr; }
    #send_btn { width: 10; }
    #status_bar {
        height: 1;
        background: $surface;
        padding: 0 2;
        dock: bottom;
        color: $text-muted;
    }
    .user_msg { color: $accent; text-style: bold; }
    .agent_msg { color: $text; }
    .tool_msg { color: $warning; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+r", "reset", "Reset chat"),
        ("ctrl+k", "switch_tab('kanban')", "Kanban"),
        ("ctrl+t", "switch_tab('chat')", "Chat"),
        ("ctrl+s", "save_session", "Save Session"),
        ("ctrl+h", "show_sessions", "Sessions"),
    ]

    status_text: reactive[str] = reactive("Ready")

    def __init__(self, agent: Agent):
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs", initial="chat"):
            with TabPane("💬 Chat", id="chat"):
                with Horizontal():
                    with Vertical():
                        yield Label("Chat", markup=False)
                        yield RichLog(id="chat_log", highlight=True, markup=True, wrap=True)
                    with Vertical():
                        yield Label("Tool Output", markup=False)
                        yield RichLog(id="tool_log", highlight=True, markup=True, wrap=True)
                with Horizontal(id="input_bar"):
                    yield Input(placeholder="Ask Koza anything...", id="chat_input")
            with TabPane("📋 Kanban", id="kanban"):
                yield RichLog(id="kanban_log", highlight=True, markup=True, wrap=True)
        yield Label(id="status_bar")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#chat_log", RichLog).write("[bold cyan]Koza Agent ready.[/] Type your message below.")
        self._refresh_kanban()

    def watch_status_text(self, value: str) -> None:
        try:
            self.query_one("#status_bar", Label).update(value)
        except Exception:
            pass

    @on(Input.Submitted, "#chat_input")
    def input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        self._send_message(text)

    @work(thread=True)
    def _send_message(self, text: str) -> None:
        chat_log = self.query_one("#chat_log", RichLog)
        tool_log = self.query_one("#tool_log", RichLog)

        self.call_from_thread(chat_log.write, f"[bold cyan]You:[/] {text}")
        self.call_from_thread(setattr, self, "status_text", "⏳ Thinking...")

        tool_buffer = []
        response_parts = []

        for token in self.agent.stream_chat(text):
            if token.startswith("\n🔧"):
                # Show "preparing session_search..." style status for recall tools
                if "recall_sessions" in token:
                    self.call_from_thread(setattr, self, "status_text", "🔍 preparing session_search...")
                elif "list_sessions" in token:
                    self.call_from_thread(setattr, self, "status_text", "📋 recall  session list...")
                self.call_from_thread(tool_log.write, token)
                tool_buffer.append(token)
            else:
                response_parts.append(token)

        full_response = "".join(response_parts).strip()
        if full_response:
            self.call_from_thread(chat_log.write, f"[bold green]Koza:[/] {full_response}")

        self.call_from_thread(setattr, self, "status_text", "Ready")

        # Refresh kanban if kanban tools were used
        if any("task" in t or "cron" in t for t in tool_buffer):
            self.call_from_thread(self._refresh_kanban)

    def _refresh_kanban(self) -> None:
        try:
            from skills.kanban import list_tasks
            from skills.cron import list_crons
            log = self.query_one("#kanban_log", RichLog)
            log.clear()
            log.write("[bold cyan]═══ KANBAN BOARD ═══[/]\n")
            log.write(list_tasks())
            log.write("\n\n[bold yellow]═══ CRON JOBS ═══[/]\n")
            log.write(list_crons())
        except Exception as e:
            pass

    def action_reset(self) -> None:
        self.agent.auto_save()  # auto-save before reset
        self.agent.reset()
        self.query_one("#chat_log", RichLog).clear()
        self.query_one("#chat_log", RichLog).write("[bold cyan]Chat reset. Session auto-saved.[/]")
        self.status_text = "Chat reset"

    def action_save_session(self) -> None:
        result = self.agent.auto_save()
        self.status_text = f"💾 {result}"
        self.query_one("#chat_log", RichLog).write(f"[dim]{result}[/]")

    def action_show_sessions(self) -> None:
        from skills.session_memory import list_sessions
        sessions = list_sessions(20)
        self.query_one("#tool_log", RichLog).write(
            f"[bold cyan]📁 Session History[/]\n{sessions}"
        )

    def action_switch_tab(self, tab_id: str) -> None:
        try:
            self.query_one("#tabs", TabbedContent).active = tab_id
            if tab_id == "kanban":
                self._refresh_kanban()
        except Exception:
            pass
