"""CLI command: koza coding — multi-persona coding mode.

Commands:
  koza coding          — start coding mode interactive session
  koza coding status   — show error memory and last session info
  koza coding clear    — clear error memory
"""
import sys
import shutil
from cli.ui import _C, _hr, _print_error, _spinner_start, _spinner_stop

# ── Persona display config ─────────────────────────────────────────────────────

_PERSONA_STYLE = {
    "Team Lead":     ("🎯", "yellow"),
    "team lead":     ("🎯", "yellow"),
    "Backend":       ("🔧", "cyan"),
    "backend":       ("🔧", "cyan"),
    "Frontend":      ("🎨", "magenta"),
    "frontend":      ("🎨", "magenta"),
    "Test Engineer": ("🧪", "green"),
    "test engineer": ("🧪", "green"),
    "test":          ("🧪", "green"),
}

_PERSONA_BOX_COLOR = {
    "Team Lead":     "yellow",
    "Backend":       "cyan",
    "Frontend":      "magenta",
    "Test Engineer": "green",
}


def _box_color(persona: str) -> str:
    return _PERSONA_BOX_COLOR.get(persona, "grey")


def _persona_icon(persona: str) -> str:
    return _PERSONA_STYLE.get(persona, _PERSONA_STYLE.get(persona.lower(), ("⚙", "grey")))[0]


def _print_coding_banner() -> None:
    tw = shutil.get_terminal_size((100, 24)).columns
    _hr()
    print()
    print(_C("  ╔═ Coding Mode ", "yellow", "bold") + _C("═" * (tw - 17), "gold"))
    print(_C("  ║", "yellow") + "  " +
          _C("🎯 Team Lead", "yellow") + "  " +
          _C("🔧 Backend", "cyan") + "  " +
          _C("🎨 Frontend", "magenta") + "  " +
          _C("🧪 Test Engineer", "green"))
    print(_C("  ╚" + "═" * (tw - 4), "yellow"))
    print()
    print(_C("  Type your task — the team handles the rest.", "grey"))
    print(_C("  /mode off  to return to normal  |  Ctrl+C to exit\n", "grey"))
    _hr()


# ── Streaming renderer with stateful persona box ───────────────────────────────

class _CodingRenderer:
    """Keeps track of which persona box is currently open and renders events."""

    def __init__(self):
        self._active_persona: str = ""
        self._box_open: bool = False
        self._tw: int = shutil.get_terminal_size((100, 24)).columns

    def _open_box(self, persona: str) -> None:
        """Print a colored persona header box."""
        if self._box_open:
            self._close_box()
        color = _box_color(persona)
        icon = _persona_icon(persona)
        label = f"  {icon} {persona} "
        pad = self._tw - len(label) - 2
        print()
        print(_C(f"  ╭─ {icon} {persona} ", color, "bold") + _C("─" * max(pad, 2), color))
        sys.stdout.write(_C("  │ ", color))
        sys.stdout.flush()
        self._active_persona = persona
        self._box_open = True

    def _close_box(self) -> None:
        if not self._box_open:
            return
        color = _box_color(self._active_persona)
        print()
        print(_C("  ╰─", color))
        self._box_open = False
        self._active_persona = ""

    def _write_token(self, token: str) -> None:
        color = _box_color(self._active_persona)
        if "\n" in token:
            parts = token.split("\n")
            for i, part in enumerate(parts):
                if part:
                    sys.stdout.write(part)
                if i < len(parts) - 1:
                    sys.stdout.write("\n" + _C("  │ ", color))
        else:
            sys.stdout.write(token)
        sys.stdout.flush()

    def render(self, event: dict) -> None:
        etype = event.get("type", "")

        if etype == "status":
            _spinner_stop()
            self._close_box()
            persona = event.get("persona", "")
            msg = event.get("message", "")
            icon = _persona_icon(persona)
            color = _box_color(persona)
            print(f"\n  {_C(icon, color)} {_C(persona, color, 'bold')}  {_C(msg, 'grey')}", flush=True)

        elif etype == "plan":
            _spinner_stop()
            self._close_box()
            plan = event.get("plan", {})
            tasks = plan.get("tasks", [])
            tw = shutil.get_terminal_size((100, 24)).columns
            print()
            print(_C("  ┌─ 📋 Plan: ", "yellow", "bold") + _C(plan.get("title", ""), "white"))
            print(_C(f"  │  {plan.get('goal', '')}", "grey"))
            print(_C("  │", "yellow"))
            for t in tasks:
                pname = t.get("persona", "?").title()
                icon = _persona_icon(pname)
                dep = f"  ← {t['depends_on']}" if t.get("depends_on") else ""
                print(_C(f"  │  [{t['id']}] {icon} {pname:<12}", "yellow") +
                      _C(f"  {t['description'][:55]}{dep}", "grey"))
            print(_C("  └" + "─" * (tw - 4), "yellow"))
            print()

        elif etype == "persona_thinking":
            persona = event.get("persona", "")
            icon = _persona_icon(persona)
            color = _box_color(persona)
            _spinner_start(_C(f"  {icon} {persona}", color, "bold") + _C("  thinking…", "grey"))

        elif etype == "persona_token":
            persona = event.get("persona", "")
            token = event.get("token", "")
            _spinner_stop()
            if persona != self._active_persona:
                self._open_box(persona)
            self._write_token(token)

        elif etype == "persona_tool":
            persona = event.get("persona", "")
            tool = event.get("tool", "")
            phase = event.get("phase", "")
            color = _box_color(persona)
            if phase == "start":
                _spinner_start(_C(f"  ⚙  {tool}…", "grey"))
            else:
                _spinner_stop()
                elapsed = event.get("elapsed", 0)
                print(_C(f"  ✓  {tool}  {elapsed:.2f}s", "green"), flush=True)

        elif etype == "error_recorded":
            self._close_box()
            err = event.get("error", {})
            print(_C(f"\n  📌  Error recorded: {err.get('description', '')[:70]}", "red"))

        elif etype == "done":
            _spinner_stop()
            self._close_box()
            print()
            _hr("═", "gold")
            print(_C("\n  ✅  Done\n", "green", "bold"))

        elif etype == "interrupted":
            _spinner_stop()
            self._close_box()
            print(_C("\n  (interrupted)", "grey"))


def cmd_coding(args: list) -> None:
    """koza coding — multi-persona coding mode."""
    from config import load_config, config_exists

    if not config_exists():
        print(_C("  ✗  No config. Run:  koza setup\n", "red"))
        return

    if args and args[0] == "status":
        _cmd_status()
        return

    if args and args[0] == "clear":
        _cmd_clear()
        return

    cfg = load_config()

    # ── Feature gate: coding_mode.enabled ──────────────────────────────────────
    if not cfg.get("coding_mode", {}).get("enabled", False):
        print(_C("  ℹ  Coding session is currently disabled.", "yellow"))
        print(_C("  Koza handles coding directly. Use spawn_subagent() for delegation.", "grey"))
        return

    try:
        from skills.agents.coding_mode import CodingSession
    except ImportError as e:
        _print_error(e)
        return

    session = CodingSession(cfg, cfg["db_path"],
                            max_retries=cfg.get("coding_mode", {}).get("max_retries", 3))

    _print_coding_banner()
    renderer = _CodingRenderer()

    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.patch_stdout import patch_stdout as _pt_patch

        pt_session = PromptSession(history=InMemoryHistory())

        with _pt_patch():
            while True:
                try:
                    user_input = pt_session.prompt(
                        HTML("<ansiyellow><b>  🎯 Task  › </b></ansiyellow>")
                    ).strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit"):
                    break
                if user_input in ("/mode off", "/exit"):
                    break

                print()
                renderer = _CodingRenderer()  # fresh renderer per task
                try:
                    for event in session.run(user_input):
                        renderer.render(event)
                except KeyboardInterrupt:
                    session.interrupt()
                    renderer.render({"type": "interrupted"})
                    continue

    except ImportError:
        while True:
            try:
                user_input = input(_C("\n  🎯 Task  › ", "yellow", "bold")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input or user_input.lower() in ("exit", "quit", "/mode off"):
                break
            renderer = _CodingRenderer()
            try:
                for event in session.run(user_input):
                    renderer.render(event)
            except KeyboardInterrupt:
                session.interrupt()
                renderer.render({"type": "interrupted"})

    print(_C("\n  Coding session ended.\n", "yellow"))
    _hr()


def _cmd_status() -> None:
    print(_C("\n  📌  Error Memory is session-scoped — start  koza coding  to view it live.\n", "grey"))


def _cmd_clear() -> None:
    print(_C("  ✓  Error memory is session-scoped and clears automatically on each new task run.\n", "green"))
