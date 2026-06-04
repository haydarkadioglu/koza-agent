"""Interactive plain CLI loop — sticky-bottom input with always-on prompt.

The prompt stays pinned at the bottom while the agent streams output above it.
Pressing Enter during processing interrupts the running request.
"""
import sys
import shutil
import time
import threading

from cli.ui import (
    _C, _hr, _print_error, _print_inline_help, _print_banner,
    _spinner_stop,
    _select_menu,
)

# ── prompt_toolkit availability ───────────────────────────────────────────────
try:
    from prompt_toolkit.application import get_app_or_none
    _HAS_PT = True
except ImportError:
    _HAS_PT = False


def _render_session_history(layout, messages: list[dict], max_lines: int = 500) -> None:
    """Render the recent conversation into the output pane.

    Prompt_toolkit owns its own scrollable buffer, so terminal scrollback is not
    enough after a restart/redraw. Keep the last visible transcript lines in the
    pane instead of restoring only a few truncated messages.
    """
    rendered: list[str] = []
    line_budget = max(1, max_lines)

    for msg in reversed(messages):
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        if not content:
            continue
        label = "You" if role == "user" else "Koza"
        color = "blue" if role == "user" else "teal"
        body_lines = content.splitlines() or [content]
        block = [_C(f"  {label}: ", color, "bold") + body_lines[0]]
        block.extend(_C("  │ ", color) + line for line in body_lines[1:])
        block.append("")
        block_line_count = len(block)
        if rendered and len(rendered) + block_line_count > line_budget:
            break
        rendered[:0] = block

    if rendered:
        layout.append_output(_C("  ── Recent conversation ──\n", "grey"))
        layout.append_output("\n".join(rendered[-line_budget:]).rstrip() + "\n")
        layout.append_output(_C("  ── End of history ──\n\n", "grey"))


def _plain_cli(agent, cfg: dict) -> None:
    _print_banner(cfg)

    import atexit

    session_start = time.time()
    total_tokens  = 0

    _TOKEN_LIMITS = {
        "deepseek": 64_000, "openai": 128_000, "anthropic": 200_000,
        "gemini": 1_000_000, "ollama": 32_000, "groq": 128_000,
        "openrouter": 128_000,
    }
    provider_name = cfg.get("provider", "")
    model_name    = cfg.get("model") or provider_name
    token_limit   = _TOKEN_LIMITS.get(provider_name, 32_000)

    # Mode label shown in status bar (resolved after background services start)
    _mode_label: list[str] = [""]  # mutable cell updated after service detection

    # ── Start background services (Telegram, cron, sync) ──────────────────────
    _active_services = []

    def _start_background_services():
        """Start Telegram bot, cron scheduler, and sync in background threads."""
        # Telegram bot — only start if no daemon is already running
        # (prevents "Conflict: terminated by other getUpdates request" error)
        from koza_daemon import get_daemon_port
        daemon_running = get_daemon_port() is not None

        token = (
            cfg.get("telegram_token", "").strip()
            or cfg.get("messaging", {}).get("telegram", {}).get("token", "").strip()
        )
        if token and not daemon_running:
            try:
                from bots.telegram import start_bot_thread

                def _agent_factory(channel: str = ""):
                    from providers.factory import get_provider
                    from core import Agent
                    return Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg, channel=channel)

                if start_bot_thread(_agent_factory, cfg):
                    _active_services.append("telegram")
            except Exception:
                pass
        elif token and daemon_running:
            # Daemon already handles Telegram — don't start a second instance
            _active_services.append("telegram (daemon)")

        # Cron scheduler (APScheduler)
        try:
            from skills.cron_scheduler import get_scheduler
            get_scheduler()  # starts if not already running
            _active_services.append("cron")
        except Exception:
            pass

    _start_background_services()

    # Determine mode label for status bar
    try:
        from koza_daemon import get_daemon_port
        if get_daemon_port() is not None:
            # Show which background services are active
            _svc_names = [s.replace(" (daemon)", "") for s in _active_services]
            if _svc_names:
                _mode_label[0] = "🔗 " + "+".join(_svc_names)
            else:
                _mode_label[0] = "🔗 bg"
        elif _active_services:
            _svc_names = [s.replace(" (daemon)", "") for s in _active_services]
            _mode_label[0] = "💻 " + "+".join(_svc_names)
        else:
            _mode_label[0] = "💻 interactive"
    except Exception:
        _mode_label[0] = "💻 interactive"

    # ── Sub-agent completion notifier (CLI) ───────────────────────────────────
    def _cli_subagent_notify(agent_id: str, status: str, goal: str, result: str) -> None:
        """Called by SubAgentNotifier when a background sub-agent finishes."""
        icon = "✅" if status == "done" else "❌"
        msg = (
            f"\n{icon} Alt-agent tamamlandı [{agent_id}] ({status})\n"
            f"   Görev: {goal}\n"
            f"   Özet:  {result[:200]}\n"
            f"   Detay için: get_subagent_status('{agent_id}')\n"
        )
        layout = _ui_layout[0]
        if layout is not None:
            layout.append_output(msg)
        else:
            print(msg)

    try:
        from skills.agents.notifier import SubAgentNotifier
        SubAgentNotifier.register(_cli_subagent_notify)
        SubAgentNotifier.start()
    except Exception:
        pass


    def _atexit_spawn_services():
        if _active_services:
            try:
                from koza_daemon import start_services_background
                start_services_background(cfg)
            except Exception:
                pass

    atexit.register(_atexit_spawn_services)

    # Windows: catch console close event (X button, logoff, shutdown)
    if sys.platform == "win32":
        try:
            import signal as _sig
            def _win_break_handler(signum, frame):
                _atexit_spawn_services()
                sys.exit(0)
            _sig.signal(_sig.SIGBREAK, _win_break_handler)
        except (OSError, ValueError, AttributeError):
            pass

    # ── Shared processing state ───────────────────────────────────────────────
    _processing     = threading.Event()   # set while agent is running
    _proc_thread    = [None]              # current background thread
    _coding_mode_on = [False]             # True while coding mode session is active

    # ── Tool permission system ────────────────────────────────────────────────
    from cli.permissions import make_permission_callback
    _SAFE_TOOLS = set()       # kept for backward compat (unused here)
    _session_allowed: set = set()    # unused — managed inside make_permission_callback
    _permanent_allowed: set = set()  # unused — managed inside make_permission_callback
    _session_allow_all = [False]     # unused — managed inside make_permission_callback

    agent.permission_callback = make_permission_callback(cfg)

    # Inject CWD into system prompt
    from skills.shell import get_cwd as _get_cwd
    _launch_cwd = _get_cwd()
    if agent.messages and agent.messages[0]["role"] == "system":
        agent.messages[0]["content"] += (
            f"\n\n**Current working directory:** `{_launch_cwd}`\n"
            "All relative paths resolve from here. Use run_command with 'cd <path>' to change directory."
        )

    def _status_bar():
        elapsed = int(time.time() - session_start)
        h, m = divmod(elapsed // 60, 60)
        s_time = f"{h}h {m:02d}m" if h else f"{m}m"
        pct    = min(100, int(total_tokens / token_limit * 100))
        bar_w  = 12
        bar    = "█" * int(bar_w * pct / 100) + "░" * (bar_w - int(bar_w * pct / 100))
        tok_str = f"{total_tokens//1000}K/{token_limit//1000}K" if total_tokens >= 1000 else f"{total_tokens}/{token_limit//1000}K"
        tw = shutil.get_terminal_size((100, 24)).columns
        line = (
            f"  {_C(model_name, 'cyan')}  {_C('│', 'grey')}  "
            f"{_C(tok_str, 'white')}  {_C('│', 'grey')}  "
            f"[{_C(bar, 'green' if pct < 70 else 'yellow' if pct < 90 else 'red')}]  "
            f"{_C(f'{pct}%', 'grey')}  {_C('│', 'grey')}  {_C(s_time, 'grey')}"
        )
        print(_C("─" * tw, "grey"))
        print(line)
        print(_C("─" * tw, "grey"))

    # ── Plain layout adapter for fallback (non-prompt_toolkit) mode ──────────

    class _PlainLayout:
        """Lightweight layout adapter that writes directly to stdout.

        Implements the same interface as ChatLayout (append_output, set_status,
        clear_output) so StreamRenderer can be used in the fallback CLI path.
        """

        def append_output(self, text: str) -> None:
            sys.stdout.write(text)
            sys.stdout.flush()

        def set_status(self, text: str) -> None:
            # In plain mode, status bar is printed on finalize via _status_bar()
            pass

        def clear_output(self) -> None:
            pass

        def set_prompt_indicator(self, busy: bool) -> None:
            pass

    _plain_layout = _PlainLayout()

    # ── Streaming processor (runs in background thread) ───────────────────────

    def _process(user_input: str) -> None:
        nonlocal total_tokens
        _processing.set()
        t_start = time.time()

        from cli.ui import StreamRenderer
        renderer = StreamRenderer(
            _plain_layout,
            model_name=model_name,
            token_limit=token_limit,
            session_start=session_start,
            mode=_mode_label[0],
        )
        # Carry over accumulated token count from previous requests
        renderer._total_tokens = total_tokens

        try:
            for event in agent.stream_chat(user_input):
                if not isinstance(event, dict):
                    continue
                renderer.handle_event(event)
                if event.get("type") == "interrupted":
                    break
        except Exception as exc:
            renderer._spinner.stop()
            print()
            _print_error(exc)
        finally:
            elapsed = time.time() - t_start
            had_response = bool(renderer._full_response.strip())
            renderer.finalize(elapsed)
            total_tokens = renderer._total_tokens
            _processing.clear()

        # Print status bar after response completes
        if had_response:
            print()
            _status_bar()

    # ── UI references (set when prompt_toolkit UI is initialized) ────────────
    _ui_layout = [None]      # ChatLayout instance (or None in fallback mode)
    _ui_renderer = [None]    # StreamRenderer instance (or None in fallback mode)
    _ui_dispatcher = [None]  # InputDispatcher instance (or None in fallback mode)

    # ── Inline command handler ────────────────────────────────────────────────
    def _handle_inline(user_input: str) -> bool:
        """Returns True if input was a slash command (consumed)."""
        nonlocal total_tokens
        if user_input.lower() in ("exit", "quit"):
            # If background services are active, spawn mini-daemon to keep them alive
            if _active_services:
                try:
                    from koza_daemon import start_services_background
                    start_services_background(cfg)
                    _hr()
                    print(_C("\n  Goodbye! 👋", "yellow"))
                    print(_C(f"  Background services running: {', '.join(_active_services)}", "grey"))
                    print(_C("  Stop with: koza quit\n", "grey"))
                    _hr()
                except Exception:
                    _hr()
                    print(_C("\n  Goodbye! 👋\n", "yellow"))
                    _hr()
            else:
                _hr()
                print(_C("\n  Goodbye! 👋\n", "yellow"))
                _hr()
            return None  # signal exit
        if user_input == "/clear":
            layout = _ui_layout[0]
            renderer = _ui_renderer[0]
            if layout is not None:
                layout.clear_output()
                _render_session_history(layout, agent.messages, max_lines=500)
                layout.append_output(_C("  ✓  Screen refreshed from conversation history.\n", "grey"))
                if renderer is not None:
                    layout.set_status(renderer._format_status(_C("● Idle", "green")))
            else:
                print(_C("  ✓  Screen refreshed.\n", "green"))
            return True
        if user_input == "/reset":
            agent.reset()
            total_tokens = 0
            layout = _ui_layout[0]
            renderer = _ui_renderer[0]
            if layout is not None:
                # prompt_toolkit mode: clear output pane and show confirmation there
                layout.clear_output()
                if renderer is not None:
                    renderer._reset()
                    renderer._total_tokens = 0
                layout.append_output(_C("  ✓  Chat reset.\n", "green"))
                layout.set_status(renderer._format_status(_C("● Idle", "green")) if renderer else "")
            else:
                # Fallback mode: use print
                print(_C("  ✓  Chat reset.\n", "green"))
            return True
        if user_input == "/kanban":
            layout = _ui_layout[0]
            if layout is not None:
                from config import load_config as _lc
                _cfg = _lc()
                from skills.kanban import init_db, list_tasks
                from skills.cron_db import init_db as cron_init
                from skills.cron import list_crons
                init_db(_cfg["db_path"])
                cron_init(_cfg["db_path"])
                lines = []
                lines.append(_C("  KANBAN  ·  Tasks", "bold", "yellow"))
                lines.append(_C("─" * 60, "gold"))
                lines.append(list_tasks())
                lines.append(_C("─" * 60, "gold"))
                lines.append(_C("  CRON JOBS", "bold", "cyan"))
                lines.append(_C("─" * 60, "gold"))
                lines.append(list_crons())
                layout.append_output("\n".join(lines) + "\n")
            else:
                from cli.commands import cmd_kanban
                cmd_kanban([])
            return True
        if user_input == "/memory":
            from skills.working_memory import wm_get_context
            ctx = wm_get_context()
            layout = _ui_layout[0]
            if layout is not None:
                lines = []
                lines.append(_C("·" * 60, "grey"))
                lines.append(ctx or _C("  (working memory is empty)", "dim"))
                lines.append(_C("·" * 60, "grey"))
                layout.append_output("\n".join(lines) + "\n")
            else:
                _hr("·", "grey")
                print(ctx or _C("  (working memory is empty)", "dim"))
                _hr("·", "grey")
            return True
        if user_input in ("/help", "/?"):
            layout = _ui_layout[0]
            if layout is not None:
                lines = []
                lines.append(_C("\n  Commands", "bold"))
                cmds = [
                    ("/help",     "Show this help"),
                    ("/sessions", "Browse / load / delete saved sessions"),
                    ("/save [title]", "Save current session"),
                    ("/title [name]", "Rename current session"),
                    ("/clear",    "Refresh screen from recent history"),
                    ("/retry",    "Resend last message"),
                    ("/undo",     "Remove last exchange"),
                    ("/history",  "Show recent conversation"),
                    ("/provider", "Switch LLM provider"),
                    ("/model [name]", "Show or change model"),
                    ("/kanban",   "Show Kanban board & cron jobs"),
                    ("/memory",   "Show working memory"),
                    ("/tools",    "List available tool groups"),
                    ("/plugins",  "List installed plugins"),
                    ("/skills",   "List saved skills"),
                    ("/compress", "Compress conversation context"),
                    ("/reset",    "Clear conversation history"),
                    ("/mode coding", "Activate coding mode"),
                    ("exit",      "Quit Koza"),
                ]
                for cmd, desc in cmds:
                    lines.append(f"  {_C(cmd, 'cyan'):<28}  {desc}")
                lines.append("")
                layout.append_output("\n".join(lines) + "\n")
            else:
                _print_inline_help()
            return True
        if user_input.startswith("/mode"):
            parts = user_input.split(None, 1)
            mode = parts[1].lower().strip() if len(parts) > 1 else ""
            if mode == "coding":
                _coding_mode_on[0] = True
                # Enable coding mode on dispatcher if available
                if _ui_dispatcher[0] is not None:
                    _ui_dispatcher[0].enable_coding_mode()
                    layout = _ui_layout[0]
                    if layout is not None:
                        layout.append_output(
                            _C("  ✓  Coding mode activated. Multi-persona orchestration enabled.\n", "green")
                        )
                        layout.append_output(
                            _C("  ℹ  Use /mode off to return to normal chat.\n", "grey")
                        )
                else:
                    print(_C("  ✓  Coding mode activated. Multi-persona orchestration enabled.\n", "green"))
                    print(_C("  ℹ  Use /mode off to return to normal chat.\n", "grey"))
                return True
            elif mode == "off":
                _coding_mode_on[0] = False
                # Disable coding mode on dispatcher if available
                if _ui_dispatcher[0] is not None:
                    _ui_dispatcher[0].disable_coding_mode()
                    layout = _ui_layout[0]
                    if layout is not None:
                        layout.append_output(
                            _C("  ✓  Coding mode deactivated. Back to normal chat.\n", "green")
                        )
                else:
                    print(_C("  ✓  Coding mode deactivated. Back to normal chat.\n", "green"))
                return True
            else:
                if _ui_layout[0] is not None:
                    _ui_layout[0].append_output(
                        _C(f"  Unknown mode: {mode!r}. Available: coding, off\n", "red")
                    )
                else:
                    print(_C(f"  Unknown mode: {mode!r}. Available: coding, off\n", "red"))
                return True
        if user_input == "/provider":
            from cli.setup import cmd_provider
            cmd_provider([])
            # Reload config and recreate agent with new provider
            from config import load_config as _reload_cfg
            new_cfg = _reload_cfg()
            if new_cfg.get("provider"):
                try:
                    from providers.factory import get_provider
                    new_provider = get_provider(new_cfg)
                    agent.provider = new_provider
                    agent.messages = [agent.messages[0]]  # keep system prompt, clear history
                    nonlocal model_name, token_limit
                    model_name = new_cfg.get("model") or new_cfg.get("provider", "")
                    token_limit = _TOKEN_LIMITS.get(new_cfg.get("provider", ""), 32_000)
                    if _ui_renderer[0]:
                        _ui_renderer[0]._model_name = model_name
                        _ui_renderer[0]._token_limit = token_limit
                    layout = _ui_layout[0]
                    if layout:
                        layout.append_output(_C(f"  ✓  Provider switched to {model_name}\n", "green"))
                    else:
                        print(_C(f"  ✓  Provider switched to {model_name}\n", "green"))
                except Exception as e:
                    if _ui_layout[0]:
                        _ui_layout[0].append_output(_C(f"  ✗  Failed: {e}\n", "red"))
                    else:
                        print(_C(f"  ✗  Failed: {e}\n", "red"))
            return True

        # ── /save [title] ── manually save current session ──────────────────
        if user_input.startswith("/save"):
            parts = user_input.split(None, 1)
            save_title = parts[1].strip() if len(parts) > 1 else ""
            result = agent.auto_save(title=save_title)
            layout = _ui_layout[0]
            msg = _C(f"  ✓  {result}\n", "green") if result else _C("  ✗  Save failed.\n", "red")
            if layout is not None:
                layout.append_output(msg)
            else:
                print(msg)
            return True

        # ── /sessions ── browse / load / delete sessions ─────────────────────
        if user_input == "/sessions":
            import time as _time
            from skills.session_memory import get_session_rows, delete_session as _del_session, load_session as _load_session
            rows = get_session_rows(limit=20)
            layout = _ui_layout[0]

            def _out(txt):
                if layout is not None:
                    layout.append_output(txt)
                else:
                    print(txt, end="")

            if not rows:
                _out(_C("  ℹ  No saved sessions.\n", "grey"))
                return True

            # Build list display
            lines = [_C("\n  Saved Sessions\n", "bold")]
            for r in rows:
                ts = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(r["started"]))
                summary = f"  {r['summary'][:60]}" if r.get("summary") else ""
                rid = r["id"]
                lines.append(f"  {_C(f'#{rid}', 'cyan')}  {_C(ts, 'grey')}  {r['title']}{summary}\n")
            _out("\n".join(lines) + "\n")

            # Build selection menu
            labels = []
            for r in rows:
                ts = _time.strftime("%m-%d %H:%M", _time.localtime(r["started"]))
                labels.append(f"#{r['id']}  {ts}  {r['title'][:45]}")
            labels.append("— Cancel —")

            try:
                choice = _select_menu("Select session", labels, default_idx=len(labels) - 1)
            except (KeyboardInterrupt, EOFError):
                return True

            if choice == "— Cancel —":
                return True

            sid = int(choice.split()[0].lstrip("#"))

            try:
                action = _select_menu(f"Session #{sid}", ["Load (resume)", "Delete", "Cancel"], default_idx=0)
            except (KeyboardInterrupt, EOFError):
                return True

            if action.startswith("Load"):
                msgs = _load_session(sid)
                if not msgs:
                    _out(_C(f"  ✗  Session #{sid} not found or empty.\n", "red"))
                    return True
                # Restore messages into agent (keep system prompt)
                sys_msg = agent.messages[0] if agent.messages and agent.messages[0].get("role") == "system" else None
                agent.messages = ([sys_msg] if sys_msg else []) + msgs
                agent._context_summary = ""
                if _ui_renderer[0]:
                    _ui_renderer[0]._total_tokens = 0
                user_msgs = [m for m in msgs if m.get("role") in ("user", "assistant")]
                _out(_C(f"  ✓  Session #{sid} loaded ({len(user_msgs)} messages). Continue chatting!\n", "green"))
                # Show last 5 messages as preview
                for m in user_msgs[-5:]:
                    role_label = _C("  You:  ", "blue") if m["role"] == "user" else _C("  Koza: ", "teal")
                    content = (m.get("content") or "")[:120]
                    _out(role_label + content + "\n")
                _out("\n")
            elif action.startswith("Delete"):
                try:
                    confirm = input(_C(f"  Delete session #{sid}? Type 'yes': ", "red")).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    _out(_C("  Cancelled.\n", "grey"))
                    return True
                if confirm == "yes":
                    _out(_C(f"  {_del_session(sid)}\n", "green"))
                else:
                    _out(_C("  Cancelled.\n", "grey"))
            return True

        # ── /title [name] ── rename current session ──────────────────────────
        if user_input.startswith("/title"):
            parts = user_input.split(None, 1)
            new_title = parts[1].strip() if len(parts) > 1 else ""
            if new_title:
                session_id = getattr(agent, "_session_id", None)
                if session_id:
                    from skills.session_memory import _conn
                    with _conn() as conn:
                        conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (new_title, session_id))
                    _out(_C(f"  ✓  Session renamed to: {new_title}\n", "green"))
                else:
                    _out(_C("  ℹ  No active session to rename.\n", "grey"))
            else:
                _out(_C("  Usage: /title <session name>\n", "grey"))
            return True

        # ── /retry ── resend last user message ────────────────────────────────
        if user_input == "/retry":
            # Find last user message and resend
            msgs = agent.messages
            last_user = None
            for m in reversed(msgs):
                if m.get("role") == "user" and m.get("content"):
                    last_user = m
                    break
            if last_user:
                # Remove assistant's last response and send again
                for i in range(len(msgs) - 1, -1, -1):
                    if msgs[i].get("role") == "assistant":
                        del msgs[i]
                        break
                _out(_C("  🔄 Retrying last message...\n", "yellow"))
                return False  # Let the main loop process it
            _out(_C("  ℹ  No previous user message to retry.\n", "grey"))
            return True

        # ── /undo ── remove last exchange ────────────────────────────────────
        if user_input == "/undo":
            msgs = agent.messages
            removed = 0
            for i in range(len(msgs) - 1, -1, -1):
                role = msgs[i].get("role")
                if role in ("user", "assistant"):
                    del msgs[i]
                    removed += 1
                if removed >= 2:  # Removed one assistant + one user
                    break
            _out(_C(f"  ↩️  Last exchange undone ({removed} messages removed).\n", "green"))
            return True

        # ── /model [name] ── show or change model ────────────────────────────
        if user_input.startswith("/model"):
            parts = user_input.split(None, 1)
            if len(parts) > 1:
                model_name_input = parts[1].strip()
                from config import load_config as _reload_cfg
                new_cfg = _reload_cfg()
                from providers.factory import get_provider
                try:
                    new_provider = get_provider(new_cfg, override_model=model_name_input)
                    agent.provider = new_provider
                    _out(_C(f"  ✓  Model changed to: {model_name_input}\n", "green"))
                except Exception as e:
                    _out(_C(f"  ✗  Failed to change model: {e}\n", "red"))
            else:
                _out(_C(f"  Current model: {model_name}\n", "cyan"))
                _out(_C("  Usage: /model <model_name> (e.g. /model gpt-4o)\n", "grey"))
            return True

        # ── /history ── show recent conversation ──────────────────────────────
        if user_input == "/history":
            msgs = agent.messages
            user_msgs = [(m.get("role"), m.get("content", "")[:200]) for m in msgs
                         if m.get("role") in ("user", "assistant") and m.get("content")]
            lines = [_C(f"\n  Recent history ({len(user_msgs)} messages):\n", "bold")]
            for role, content in user_msgs[-15:]:
                label = _C("  You:  ", "blue") if role == "user" else _C("  Koza: ", "teal")
                lines.append(label + content.replace("\n", " ")[:180])
            lines.append("")
            layout = _ui_layout[0]
            if layout is not None:
                layout.append_output("\n".join(lines))
            else:
                print("\n".join(lines))
            return True

        # ── /plugins ── list plugins ─────────────────────────────────────────
        if user_input == "/plugins":
            try:
                from skills.plugin_loader import plugin_list
                result = plugin_list()
            except ImportError:
                result = "  ℹ  Plugin system not available."
            layout = _ui_layout[0]
            if layout is not None:
                layout.append_output(result + "\n")
            else:
                print(result)
            return True

        # ── /skills ── list skills ───────────────────────────────────────────
        if user_input == "/skills":
            try:
                from skills.skill_ecosystem import skill_list
                result = skill_list()
            except ImportError:
                result = "  ℹ  Skill system not available."
            layout = _ui_layout[0]
            if layout is not None:
                layout.append_output(result + "\n")
            else:
                print(result)
            return True

        # ── /tools ── list available tool groups ─────────────────────────────
        if user_input == "/tools":
            from core import _TOOL_GROUPS
            lines = [_C("\n  Available tool groups:\n", "bold")]
            for group, tools in sorted(_TOOL_GROUPS.items()):
                lines.append(f"  {_C(group, 'cyan'):<14} {len(tools)} tools")
            lines.append(_C(f"\n  Total: {sum(len(v) for v in _TOOL_GROUPS.values())} tools\n", "grey"))
            layout = _ui_layout[0]
            if layout is not None:
                layout.append_output("\n".join(lines) + "\n")
            else:
                print("\n".join(lines))
            return True

        # ── /compress ── manually compress context ─────────────────────────
        if user_input == "/compress":
            try:
                agent._ctx.maybe_build_rolling_summary()
                agent._trim_messages()
                _out(_C("  ✓  Context compressed.\n", "green"))
            except Exception as e:
                _out(_C(f"  ✗  Compression failed: {e}\n", "red"))
            return True

        # ── google-login / /google-login ── OAuth login ──────────────────────
        if user_input in ("google-login", "/google-login"):
            _out(_C("\n  🔑 Google OAuth login baslatiliyor...\n", "cyan"))
            try:
                from providers.google_oauth_provider import run_oauth_login
                if run_oauth_login():
                    _out(_C("  ✅ Google hesabina baglandi. Provider'i kullanmak icin /model gemini-2.5-pro\n", "green"))
                else:
                    _out(_C("  ❌ Baglanti basarisiz.\n", "red"))
            except Exception as e:
                _out(_C(f"  ❌ Hata: {e}\n", "red"))
            return True

        # ── codex-login / /codex-login ── Codex login ────────────────────────
        if user_input in ("codex-login", "/codex-login"):
            _out(_C("\n  🅾️  OpenAI Codex login baslatiliyor...\n", "cyan"))
            try:
                from providers.codex_provider import cmd_codex_login
                result = cmd_codex_login()
                _out(_C(f"  {result}\n", "green") if "✅" in result or "ℹ️" in result else _C(f"  {result}\n", "yellow"))
            except Exception as e:
                _out(_C(f"  ❌ Hata: {e}\n", "red"))
            return True

        # ── email-setup / /email-setup ── Email configuration ────────────────
        if user_input in ("email-setup", "/email-setup"):
            _out(_C("\n  📧 Email setup baslatiliyor...\n", "cyan"))
            try:
                from skills.email_skill import email_setup
                result = email_setup()
                _out(_C(f"  {result}\n", "green"))
            except Exception as e:
                _out(_C(f"  ❌ Hata: {e}\n", "red"))
            return True

        # ── email-log / /email-log ── Show sent email log ────────────────────
        if user_input in ("email-log", "/email-log"):
            try:
                from skills.email_skill import email_log
                result = email_log()
            except ImportError:
                result = "  ℹ  Email log not available."
            layout = _ui_layout[0]
            if layout is not None:
                layout.append_output(result + "\n")
            else:
                print(result)
            return True

        return False

    # ── Main loop — prompt_toolkit Application (split-pane UI) ──────────────────
    if _HAS_PT:
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from cli.ui import ChatLayout, StreamRenderer
        from cli.input_dispatcher import InputDispatcher

        layout = ChatLayout(on_submit=lambda t: None)  # placeholder

        # Derive provider auth mode for status badge
        _provider_auth = cfg.get("providers", {}).get(provider_name, {}).get("auth", "")
        if not _provider_auth and provider_name.startswith("gemini"):
            _provider_auth = cfg.get("providers", {}).get("gemini", {}).get("auth", "")

        renderer = StreamRenderer(
            layout,
            model_name=model_name,
            token_limit=token_limit,
            session_start=session_start,
            mode=_mode_label[0],
            provider_auth=_provider_auth,
        )
        coding_enabled = cfg.get("coding_mode", {}).get("enabled", False)
        dispatcher = InputDispatcher(agent, layout, renderer, coding_enabled=coding_enabled)

        # Expose layout/renderer/dispatcher to _handle_inline for slash commands
        _ui_layout[0] = layout
        _ui_renderer[0] = renderer
        _ui_dispatcher[0] = dispatcher

        def on_submit(text: str) -> None:
            text = text.strip()
            if not text:
                dispatcher.submit(text)  # empty-Enter interrupt
                return
            # Slash hint: lone "/" shows available commands
            if text == "/":
                _SLASH_CMDS = [
                    "/help", "/sessions", "/save", "/title", "/clear", "/retry", "/undo",
                    "/provider", "/model", "/kanban", "/memory", "/tools",
                    "/plugins", "/skills", "/compress", "/reset",
                    "/mode coding", "/mode off",
                ]
                layout.append_output(
                    _C("  Commands: ", "grey")
                    + _C("  ".join(_SLASH_CMDS), "cyan") + "\n"
                )
                return
            # Check slash commands first
            cmd = _handle_inline(text)
            if cmd is None:
                # exit/quit — close the application
                app.exit()
                return
            if cmd:
                # Command was handled, don't send to agent
                return
            # Normal message — render and dispatch
            renderer.render_user_message(text)
            dispatcher.submit(text)

        layout.on_submit = on_submit

        kb = KeyBindings()

        @kb.add('c-c')
        def _handle_ctrl_c(event):
            """Ctrl+C: interrupt agent if busy, exit if idle."""
            if dispatcher.is_busy():
                if dispatcher._coding_mode and dispatcher._coding_session:
                    dispatcher._coding_session.interrupt()
                else:
                    agent.interrupt()
                # Immediate UX feedback — don't wait for agent to actually stop
                dispatcher._show_interrupting_status()
            else:
                event.app.exit()

        @kb.add('c-l')
        def _handle_ctrl_l(event):
            """Ctrl+L: refresh output pane from recent conversation history."""
            layout.clear_output()
            _render_session_history(layout, agent.messages, max_lines=500)
            layout.append_output(_C("  ✓  Screen refreshed from conversation history.\n", "grey"))

        app = Application(
            layout=layout.create_layout(),
            full_screen=False,
            key_bindings=kb,
        )
        layout._app = app
        layout.set_status(renderer._format_status(_C("● Idle", "green")))

        # Render previous session history in output pane.
        # Keep enough context visible after app restarts instead of showing only
        # a handful of truncated messages.
        _render_session_history(layout, agent.messages, max_lines=500)

        try:
            app.run()
        finally:
            # Auto-save session on exit
            try:
                agent.auto_save()
            except Exception:
                pass
            # Ensure background services persist after ANY exit
            # (terminal close, Ctrl+C while idle, app crash, etc.)
            if _active_services:
                try:
                    from koza_daemon import start_services_background
                    start_services_background(cfg)
                except Exception:
                    pass
        return

    # ── Fallback: simple blocking loop (no prompt_toolkit) ────────────────────

    # Register SIGINT handler to ensure cancel_event is set within 100ms of
    # Ctrl+C, regardless of what the main thread is doing at that moment.
    import signal as _signal

    def _sigint_handler(signum, frame):
        """Immediately interrupt the agent on Ctrl+C (< 100ms guarantee)."""
        if _processing.is_set():
            agent.interrupt()
            # Don't exit — let the fallback loop handle the interrupted state
            return
        # Not processing — raise KeyboardInterrupt for normal exit handling
        raise KeyboardInterrupt

    _signal.signal(_signal.SIGINT, _sigint_handler)

    while True:
        try:
            user_input = input(
                _C("\n  ", "grey") + _C("●", "cyan", "bold") + _C(" You  › ", "cyan")
            ).strip()
        except (EOFError, KeyboardInterrupt):
            if _processing.is_set():
                agent.interrupt()
                if _proc_thread[0]:
                    _proc_thread[0].join(timeout=5)
                    if _proc_thread[0].is_alive():
                        # Zombie thread — force-clear state to prevent permanent hang
                        import logging as _logging
                        _logging.getLogger(__name__).warning(
                            "Agent thread still alive after 5s timeout — "
                            "force-clearing processing state (zombie thread)"
                        )
                        _processing.clear()
                        agent._busy = False
                continue
            _hr()
            print(_C("\n  ✨ Görüşürüz! 👋\n", "cyan"))
            print(_C("  🦎 Koza kapandı.\n", "grey"))
            _hr()
            # Spawn background services before exiting
            if _active_services:
                try:
                    from koza_daemon import start_services_background
                    start_services_background(cfg)
                    print(_C(f"  Background services running: {', '.join(_active_services)}", "grey"))
                    print(_C("  Stop with: koza quit\n", "grey"))
                except Exception:
                    pass
            break

        if not user_input:
            continue
        # Slash hint in fallback mode too
        if user_input == "/":
            print(_C("  Commands: /help /sessions /save /title /clear /retry /undo /provider /model /kanban /memory /tools /plugins /skills /compress /reset", "grey"))
            continue
        cmd = _handle_inline(user_input)
        if cmd is None:
            break
        if cmd:
            continue

        # If agent is busy streaming, interrupt current stream first
        if agent._busy:
            agent.interrupt()
            print(_C("  ⏳  Interrupting current stream…", "grey"))

        # Wait for any previous processing to finish before starting new one
        # (the stream_lock inside agent.stream_chat ensures proper sequencing)
        if _proc_thread[0] and _proc_thread[0].is_alive():
            print(_C("  ⏳  Waiting for previous request to finish…", "grey"))
            _proc_thread[0].join(timeout=5.0)
            if _proc_thread[0].is_alive():
                # Zombie thread — force-clear state to prevent permanent hang
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "Agent thread still alive after 5s timeout — "
                    "force-clearing processing state (zombie thread)"
                )
                _processing.clear()
                agent._busy = False

        total_tokens += max(1, len(user_input) // 4)
        _proc_thread[0] = threading.Thread(
            target=_process, args=(user_input,), daemon=True
        )
        _proc_thread[0].start()
