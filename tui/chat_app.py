"""Koza Cockpit — Textual-powered terminal workspace."""
from __future__ import annotations

import time
from dataclasses import dataclass

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, RichLog, TabPane, TabbedContent

from core import Agent
from tui.event_adapter import stream_event_to_record


@dataclass
class TuiCommand:
    name: str
    description: str


COMMANDS: tuple[TuiCommand, ...] = (
    TuiCommand("/help", "Show command palette help"),
    TuiCommand("/reset", "Reset chat after saving the current session"),
    TuiCommand("/save", "Save current session"),
    TuiCommand("/sessions", "List saved sessions"),
    TuiCommand("/load <id>", "Load a saved session"),
    TuiCommand("/provider <name> [model]", "Switch provider/model for this TUI session"),
    TuiCommand("/tasks", "Switch to the Tasks tab"),
    TuiCommand("/agents", "Switch to the Agents tab"),
    TuiCommand("/memory <query>", "Search memory"),
    TuiCommand("/tracked <goal>", "Start a tracked coding task"),
    TuiCommand("/once <minutes> <instruction>", "Schedule one one-shot @agent follow-up"),
    TuiCommand("/status", "Refresh dashboard panels"),
)


class ChatApp(App):
    """Dense terminal cockpit for chat, tools, tasks, agents, memory, and config."""

    TITLE = "Koza Cockpit"
    CSS = """
    Screen { background: $background; }
    TabbedContent { height: 1fr; }
    #chat_grid { height: 1fr; }
    #chat_col { width: 2fr; min-width: 48; }
    #side_col { width: 1fr; min-width: 32; }
    RichLog {
        border: round $surface-lighten-2;
        padding: 0 1;
        height: 1fr;
    }
    #chat_log { border: round $accent; }
    #tool_log { border: round $warning; }
    #status_line {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    #chat_input {
        dock: bottom;
        height: 3;
        margin: 0 1 1 1;
    }
    .pane_title {
        height: 1;
        color: $accent;
        text-style: bold;
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("ctrl+c", "interrupt_or_quit", "Stop/Quit"),
        ("escape", "interrupt_or_quit", "Stop/Quit"),
        ("ctrl+p", "palette", "Palette"),
        ("ctrl+r", "refresh_all", "Refresh"),
        ("ctrl+s", "save_session", "Save"),
        ("ctrl+1", "switch_tab('chat')", "Chat"),
        ("ctrl+2", "switch_tab('tasks')", "Tasks"),
        ("ctrl+3", "switch_tab('agents')", "Agents"),
        ("ctrl+4", "switch_tab('memory')", "Memory"),
        ("ctrl+5", "switch_tab('config')", "Config"),
    ]

    status_text: reactive[str] = reactive("Ready")
    progress_pct: reactive[float] = reactive(0.0)

    def __init__(self, agent: Agent, cfg: dict):
        super().__init__()
        self.agent = agent
        self.cfg = cfg
        self._busy = False
        self._last_interrupt = 0.0
        self._response_parts: list[str] = []
        self._session_start = time.time()
        ui_cfg = cfg.get("ui", {}) if isinstance(cfg, dict) else {}
        self._refresh_interval = max(0.5, int(ui_cfg.get("refresh_interval_ms", 1500)) / 1000)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="tabs", initial="chat"):
            with TabPane("Chat", id="chat"):
                with Horizontal(id="chat_grid"):
                    with Vertical(id="chat_col"):
                        yield Label("Conversation", classes="pane_title")
                        yield RichLog(id="chat_log", highlight=True, markup=True, wrap=True)
                    with Vertical(id="side_col"):
                        yield Label("Tools & Activity", classes="pane_title")
                        yield RichLog(id="tool_log", highlight=True, markup=True, wrap=True)
                yield Input(placeholder="Ask Koza...  Ctrl+P for commands", id="chat_input")
            with TabPane("Tasks", id="tasks"):
                yield RichLog(id="tasks_log", highlight=True, markup=True, wrap=True)
            with TabPane("Agents", id="agents"):
                yield RichLog(id="agents_log", highlight=True, markup=True, wrap=True)
            with TabPane("Memory", id="memory"):
                yield RichLog(id="memory_log", highlight=True, markup=True, wrap=True)
            with TabPane("Config", id="config"):
                yield RichLog(id="config_log", highlight=True, markup=True, wrap=True)
        yield Label(id="status_line")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#chat_log", RichLog).write("[bold cyan]Koza Cockpit ready.[/]")
        self._write_palette()
        self._refresh_all()
        self.set_interval(self._refresh_interval, self._refresh_live_panels)
        self.query_one("#chat_input", Input).focus()

    def _update_status_line(self) -> None:
        try:
            elapsed = int(time.time() - self._session_start)
            provider = self.cfg.get("provider", "?")
            model = self.cfg.get("model") or provider
            if self._busy:
                pct = int(self.progress_pct)
                width = 10
                filled = int(pct * width / 100)
                empty = width - filled
                bar = "█" * filled + "░" * empty
                progress_part = f" | [cyan]Progress:[/] [{bar}] {pct}%"
            else:
                progress_part = ""
            self.query_one("#status_line", Label).update(
                f"{self.status_text}{progress_part} | {provider}/{model} | {elapsed // 60}m | Ctrl+P commands"
            )
        except Exception:
            pass

    def watch_status_text(self, value: str) -> None:
        self._update_status_line()

    def watch_progress_pct(self, value: float) -> None:
        self._update_status_line()

    @on(Input.Submitted, "#chat_input")
    def input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
            return
        self._send_message(text)

    def _handle_command(self, command: str) -> None:
        chat_log = self.query_one("#chat_log", RichLog)
        tool_log = self.query_one("#tool_log", RichLog)
        parts = command.split(maxsplit=2)
        name = parts[0].lower()
        if name in ("/help", "/"):
            self._write_palette()
        elif name == "/reset":
            self.agent.auto_save()
            self.agent.reset()
            chat_log.clear()
            chat_log.write("[green]Chat reset. Previous session auto-saved.[/]")
            self.status_text = "Reset"
        elif name == "/save":
            self.action_save_session()
        elif name == "/sessions":
            self._show_sessions()
        elif name == "/load":
            if len(parts) < 2 or not parts[1].isdigit():
                tool_log.write("[yellow]Usage: /load <session_id>[/]")
                return
            self._load_session(int(parts[1]))
        elif name == "/provider":
            self._switch_provider(command[len("/provider"):].strip())
        elif name == "/tasks":
            self.action_switch_tab("tasks")
        elif name == "/agents":
            self.action_switch_tab("agents")
        elif name == "/status":
            self._refresh_all()
            self.status_text = "Dashboard refreshed"
        elif name == "/memory":
            query = command[len("/memory"):].strip()
            self._refresh_memory(query or "")
            self.action_switch_tab("memory")
        elif name == "/tracked":
            goal = command[len("/tracked"):].strip()
            if not goal:
                tool_log.write("[yellow]Usage: /tracked <coding goal>[/]")
                return
            self._run_quick_tool("start_tracked_coding_task", goal=goal)
        elif name == "/once":
            if len(parts) < 3 or not parts[1].isdigit():
                tool_log.write("[yellow]Usage: /once <minutes> <instruction>[/]")
                return
            self._run_quick_tool(
                "create_once_cron",
                name="TUI follow-up",
                command=f"@agent: {parts[2]}",
                delay_minutes=int(parts[1]),
            )
        else:
            tool_log.write(f"[red]Unknown command:[/] {command}")

    def _show_sessions(self) -> None:
        try:
            from skills.session_memory import list_sessions
            self._append_tool("[bold cyan]Sessions[/]\n" + list_sessions(20))
        except Exception as exc:
            self._append_tool(f"[red]Session list failed:[/] {exc}")

    def _load_session(self, session_id: int) -> None:
        try:
            from skills.session_memory import load_session
            msgs = load_session(session_id)
            if not msgs:
                self._append_tool(f"[red]Session #{session_id} not found or empty.[/]")
                return
            sys_msg = self.agent.messages[0] if self.agent.messages and self.agent.messages[0].get("role") == "system" else None
            self.agent.messages = ([sys_msg] if sys_msg else []) + msgs
            self.query_one("#chat_log", RichLog).clear()
            self._append_chat(f"[green]Session #{session_id} loaded.[/]")
        except Exception as exc:
            self._append_tool(f"[red]Session load failed:[/] {exc}")

    def _switch_provider(self, spec: str) -> None:
        bits = spec.split()
        if not bits:
            self._append_tool("[yellow]Usage: /provider <name> [model][/]")
            return
        provider_name = bits[0]
        model_name = bits[1] if len(bits) > 1 else ""
        try:
            from providers.factory import get_provider
            self.cfg["provider"] = provider_name
            if model_name:
                self.cfg["model"] = model_name
            self.agent.provider = get_provider(self.cfg)
            self._append_tool(f"[green]Provider switched:[/] {provider_name} {self.cfg.get('model') or ''}")
            self._refresh_config()
        except Exception as exc:
            self._append_tool(f"[red]Provider switch failed:[/] {exc}")

    def _run_quick_tool(self, tool_name: str, **kwargs) -> None:
        from tools.registry import ALL_HANDLERS

        log = self.query_one("#tool_log", RichLog)
        handler = ALL_HANDLERS.get(tool_name)
        if not handler:
            log.write(f"[red]Tool not found:[/] {tool_name}")
            return
        try:
            result = handler(**kwargs)
            log.write(f"[bold cyan]{tool_name}[/]\n{result}")
            self._refresh_all()
        except Exception as exc:
            log.write(f"[red]{tool_name} failed:[/] {exc}")

    @work(thread=True)
    def _send_message(self, text: str) -> None:
        if self._busy:
            self.call_from_thread(self._interrupt_agent)
            return
        self._busy = True
        self._response_parts = []
        self.call_from_thread(setattr, self, "progress_pct", 0.0)
        self.call_from_thread(self._append_chat, f"[bold cyan]You:[/] {text}")
        self.call_from_thread(setattr, self, "status_text", "Thinking")
        try:
            for event in self.agent.stream_chat(text):
                if not isinstance(event, dict):
                    continue
                etype = event.get("type", "")
                if etype == "thinking":
                    self.call_from_thread(setattr, self, "progress_pct", 15.0)
                elif etype == "text":
                    current = self.progress_pct
                    if current < 80.0:
                        self.call_from_thread(setattr, self, "progress_pct", min(80.0, current + 1.0))
                elif etype == "tool_start":
                    self.call_from_thread(setattr, self, "progress_pct", 45.0)
                elif etype == "tool_done":
                    self.call_from_thread(setattr, self, "progress_pct", 75.0)

                channel, payload = stream_event_to_record(event)
                if channel == "status":
                    self.call_from_thread(setattr, self, "status_text", payload)
                elif channel == "tool":
                    self.call_from_thread(self._append_tool, payload)
                elif channel == "error":
                    self.call_from_thread(self._append_tool, f"[red]{payload}[/]")
                    self.call_from_thread(setattr, self, "status_text", "Error")
                elif channel == "chat":
                    self._response_parts.append(payload)
                    if "\n" in payload:
                        self.call_from_thread(self._flush_response_partial)
            self.call_from_thread(setattr, self, "progress_pct", 100.0)
            self.call_from_thread(self._flush_response_final)
        except Exception as exc:
            self.call_from_thread(self._append_tool, f"[red]Stream failed:[/] {exc}")
        finally:
            self._busy = False
            self.call_from_thread(setattr, self, "progress_pct", 0.0)
            self.call_from_thread(setattr, self, "status_text", "Ready")
            self.call_from_thread(self._refresh_all)

    def _append_chat(self, text: str) -> None:
        self.query_one("#chat_log", RichLog).write(text)

    def _append_tool(self, text: str) -> None:
        self.query_one("#tool_log", RichLog).write(text)

    def _flush_response_partial(self) -> None:
        text = "".join(self._response_parts)
        if not text.strip():
            return
        lines = text.splitlines(keepends=True)
        complete = "".join(lines[:-1])
        self._response_parts = [lines[-1]] if lines else []
        if complete.strip():
            self._append_chat(f"[bold green]Koza:[/] {complete.rstrip()}")

    def _flush_response_final(self) -> None:
        text = "".join(self._response_parts).strip()
        if text:
            self._append_chat(f"[bold green]Koza:[/] {text}")
        self._response_parts = []

    def _write_palette(self) -> None:
        log = self.query_one("#tool_log", RichLog)
        log.write("[bold cyan]Command Palette[/]")
        for cmd in COMMANDS:
            log.write(f"[cyan]{cmd.name:<22}[/] {cmd.description}")

    def _refresh_live_panels(self) -> None:
        active = self.query_one("#tabs", TabbedContent).active
        if active in {"tasks", "agents", "config"}:
            self._refresh_all()

    def _refresh_all(self) -> None:
        self._refresh_tasks()
        self._refresh_agents()
        self._refresh_memory("")
        self._refresh_config()

    def _refresh_tasks(self) -> None:
        log = self.query_one("#tasks_log", RichLog)
        try:
            from skills.kanban import list_tasks
            from skills.cron import list_crons
            log.clear()
            log.write("[bold cyan]Kanban[/]")
            log.write(list_tasks())
            log.write("\n[bold yellow]Cron / One-shot Jobs[/]")
            log.write(list_crons())
        except Exception as exc:
            log.write(f"[red]Tasks refresh failed:[/] {exc}")

    def _refresh_agents(self) -> None:
        log = self.query_one("#agents_log", RichLog)
        try:
            from skills.agents import list_subagents
            log.clear()
            log.write("[bold cyan]Sub-agents[/]")
            log.write(list_subagents())
        except Exception as exc:
            log.write(f"[red]Agents refresh failed:[/] {exc}")

    def _refresh_memory(self, query: str = "") -> None:
        log = self.query_one("#memory_log", RichLog)
        try:
            from skills.working_memory import wm_get
            from skills.shared_memory import memory_search, memory_list
            log.clear()
            log.write("[bold cyan]Working Memory[/]")
            log.write(wm_get())
            log.write("\n[bold cyan]Shared Memory[/]")
            log.write(memory_search(query, 20) if query else memory_list(limit=20))
        except Exception as exc:
            log.write(f"[red]Memory refresh failed:[/] {exc}")

    def _refresh_config(self) -> None:
        log = self.query_one("#config_log", RichLog)
        try:
            tg = self.cfg.get("messaging", {}).get("telegram", {})
            log.clear()
            log.write("[bold cyan]Runtime[/]")
            log.write(f"Provider : {self.cfg.get('provider', '')}")
            log.write(f"Model    : {self.cfg.get('model') or '(default)'}")
            log.write(f"Workspace: {self.cfg.get('workspace_path', '')}")
            log.write(f"DB       : {self.cfg.get('db_path', '')}")
            log.write(f"Telegram : {'configured' if tg.get('token') else 'not configured'}")
            services = ", ".join(self.cfg.get("_runtime", {}).get("services", [])) or "none"
            log.write(f"Services : {services}")
            log.write(f"UI       : {self.cfg.get('ui', {})}")
        except Exception as exc:
            log.write(f"[red]Config refresh failed:[/] {exc}")

    def _interrupt_agent(self) -> None:
        try:
            self.agent.interrupt()
            self.status_text = "Interrupting"
            self._append_tool("[yellow]Interrupt requested[/]")
        except Exception:
            pass

    def action_interrupt_or_quit(self) -> None:
        now = time.time()
        if self._busy:
            self._interrupt_agent()
            self._last_interrupt = now
            return
        if now - self._last_interrupt < 1.5:
            self.exit()
            return
        self._last_interrupt = now
        self.status_text = "Press again to quit"

    def action_palette(self) -> None:
        input_box = self.query_one("#chat_input", Input)
        input_box.value = "/"
        input_box.focus()
        self._write_palette()

    def action_refresh_all(self) -> None:
        self._refresh_all()
        self.status_text = "Dashboard refreshed"

    def action_save_session(self) -> None:
        result = self.agent.auto_save()
        self._append_tool(f"[green]{result}[/]")
        self.status_text = "Session saved"

    def action_switch_tab(self, tab_id: str) -> None:
        try:
            self.query_one("#tabs", TabbedContent).active = tab_id
            if tab_id in {"tasks", "agents", "memory", "config"}:
                self._refresh_all()
        except Exception:
            pass
