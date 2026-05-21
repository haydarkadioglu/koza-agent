"""CLI command: koza coding — multi-persona coding mode.

Commands:
  koza coding          — start coding mode interactive session
  koza coding status   — show error memory and last session info
  koza coding clear    — clear error memory
"""
import sys
import shutil
from cli.ui import _C, _hr, _print_error


# ── Persona display config ─────────────────────────────────────────────────────

_PERSONA_STYLE = {
    "Team Lead":    ("🎯", "yellow"),
    "team lead":    ("🎯", "yellow"),
    "Backend":      ("🔧", "cyan"),
    "backend":      ("🔧", "cyan"),
    "Frontend":     ("🎨", "magenta"),
    "frontend":     ("🎨", "magenta"),
    "Test Engineer":("🧪", "green"),
    "test engineer":("🧪", "green"),
    "test":         ("🧪", "green"),
}


def _persona_prefix(persona: str) -> str:
    icon, color = _PERSONA_STYLE.get(persona, _PERSONA_STYLE.get(persona.lower(), ("⚙", "grey")))
    return _C(f"  {icon} {persona:<14}", color, "bold")


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


def _render_coding_event(event: dict) -> None:
    """Render a single CodingSession event to the terminal."""
    etype = event.get("type", "")

    if etype == "status":
        persona = event.get("persona", "")
        msg     = event.get("message", "")
        print(f"\n{_persona_prefix(persona)} {_C(msg, 'grey')}", flush=True)

    elif etype == "plan":
        plan = event.get("plan", {})
        tasks = plan.get("tasks", [])
        print()
        print(_C("  📋 Plan:", "yellow", "bold"),
              _C(plan.get("title", ""), "white"))
        print(_C(f"     {plan.get('goal', '')}", "grey"))
        for t in tasks:
            pname = t.get("persona", "?").title()
            icon  = _PERSONA_STYLE.get(pname, ("⚙", "grey"))[0]
            print(_C(f"     [{t['id']}] {icon} {pname}: {t['description'][:60]}", "grey"))
        print()

    elif etype == "persona_token":
        persona = event.get("persona", "")
        token   = event.get("token", "")
        # First token of a new persona line → print prefix
        sys.stdout.write(token)
        sys.stdout.flush()

    elif etype == "persona_thinking":
        pass  # spinner handles this externally

    elif etype == "persona_tool":
        persona = event.get("persona", "")
        tool    = event.get("tool", "")
        phase   = event.get("phase", "")
        if phase == "start":
            print(_C(f"\r  ⚙  {tool}…", "grey") + " " * 20, flush=True)
        else:
            elapsed = event.get("elapsed", 0)
            print(_C(f"\r  ✓  {tool}  {elapsed:.2f}s", "green") + " " * 20, flush=True)

    elif etype == "error_recorded":
        err = event.get("error", {})
        print(_C(f"\n  📌 Error recorded: {err.get('description', '')[:60]}", "red"))

    elif etype == "done":
        print()
        _hr("═", "gold")
        print(_C("\n  ✅  Done\n", "green", "bold"))

    elif etype == "interrupted":
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

    try:
        from skills.agents.coding_mode import CodingSession
    except ImportError as e:
        _print_error(e)
        return

    session = CodingSession(cfg, cfg["db_path"],
                            max_retries=cfg.get("coding_mode", {}).get("max_retries", 3))

    _print_coding_banner()

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
                try:
                    for event in session.run(user_input):
                        _render_coding_event(event)
                except KeyboardInterrupt:
                    session.interrupt()
                    print(_C("\n  (interrupted)", "grey"))
                    continue

    except ImportError:
        # Fallback without prompt_toolkit
        while True:
            try:
                user_input = input(_C("\n  🎯 Task  › ", "yellow", "bold")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input or user_input.lower() in ("exit", "quit", "/mode off"):
                break
            try:
                for event in session.run(user_input):
                    _render_coding_event(event)
            except KeyboardInterrupt:
                session.interrupt()
                print(_C("\n  (interrupted)", "grey"))

    print(_C("\n  Coding session ended.\n", "yellow"))
    _hr()


def _cmd_status() -> None:
    """Show current session error memory (only meaningful while session is active)."""
    print(_C("\n  📌  Error Memory is session-scoped — start  koza coding  to view it live.\n", "grey"))


def _cmd_clear() -> None:
    """No-op: per-session memory clears automatically on each new run."""
    print(_C("  ✓  Error memory is session-scoped and clears automatically on each new task run.\n", "green"))
