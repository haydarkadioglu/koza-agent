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
    _SAFE_TOOLS = {
        "web_search", "fetch_url", "list_dir", "read_file", "wm_add", "wm_get",
        "wm_list", "wm_clear", "wm_get_context",
        "memory_recall", "memory_search", "memory_list", "memory_store",
        "recall_sessions", "list_sessions", "list_tasks", "list_crons", "list_subagents",
        "get_subagent_status", "subagent_get_result", "subagent_delete", "subagent_update",
        "github_search_code", "github_list_prs",
        "github_repo_info", "pandas_query", "matplotlib_plot",
        "list_projects", "list_capabilities", "get_weather", "get_time",
        "calculator", "search_files", "get_cwd",
        "run_command", "run_python", "run_node", "run_script",
        "write_file", "create_dir", "create_project",
        "spawn_subagent", "start_background_task", "get_background_status",
        "list_background_tasks", "cancel_background_task",
        "sync_status", "sync_now", "list_hosts",
    }
    _session_allowed:  set = set()
    _permanent_allowed: set = set(cfg.get("allowed_tools", []))
    _session_allow_all  = [False]

    def _show_permission_ui(name: str, args: dict) -> bool:
        """Render the permission prompt — always runs in terminal context."""
        arg_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in list(args.items())[:3])
        print()
        print(_C("  ┌─ Permission Required ", "yellow", "bold") + _C("─" * 40, "gold"))
        print(_C("  │  Tool  : ", "grey") + _C(name, "cyan", "bold"))
        if arg_preview:
            print(_C("  │  Args  : ", "grey") + _C(arg_preview, "white"))
        print(_C("  └" + "─" * 53, "yellow"))
        try:
            choice = _select_menu(
                "Allow this tool?",
                ["Allow (this session)", "Allow all tools (this session)",
                 "Allow permanently", "Allow (once)", "Deny"],
                default_idx=0,
            )
        except (KeyboardInterrupt, EOFError):
            return False
        if choice == "Allow (this session)":
            _session_allowed.add(name); return True
        if choice == "Allow all tools (this session)":
            _session_allow_all[0] = True
            print(_C("  ✓  Bu oturumda tüm tool'lar otomatik izinli.\n", "green"))
            return True
        if choice == "Allow permanently":
            _permanent_allowed.add(name)
            try:
                from config import load_config, save_config
                c = load_config()
                existing = set(c.get("allowed_tools", []))
                existing.add(name); c["allowed_tools"] = sorted(existing)
                save_config(c)
            except Exception:
                pass
            return True
        if choice == "Allow (once)":
            return True
        print(_C(f"  ✗  {name} denied.\n", "red"))
        return False

    def _ask_permission(name: str, args: dict) -> bool:
        if _session_allow_all[0]:
            return True
        if name in _SAFE_TOOLS or name in _session_allowed or name in _permanent_allowed:
            return True
        # Stop spinner before showing permission UI to avoid display corruption
        _spinner_stop()
        # If a prompt_toolkit Application is running, use run_in_terminal to
        # temporarily suspend the TUI, run the permission menu in raw terminal,
        # then resume the TUI. This prevents print() from a background thread
        # corrupting the prompt_toolkit display.
        pt_app = get_app_or_none() if _HAS_PT else None
        if pt_app is not None and pt_app.is_running and pt_app.loop is not None:
            import asyncio
            from prompt_toolkit.application import run_in_terminal

            result = [False]

            def _permission_in_terminal():
                result[0] = _show_permission_ui(name, args)

            # Schedule run_in_terminal on the app's event loop from this
            # background thread, then block until the UI interaction completes.
            # This bridges the background thread (where the agent runs) to the
            # main event loop thread (where prompt_toolkit UI lives).
            try:
                coro = run_in_terminal(_permission_in_terminal, render_cli_done=False)
                try:
                    future = asyncio.run_coroutine_threadsafe(coro, pt_app.loop)
                except Exception:
                    coro.close()
                    return False
                # Block the background thread until the permission UI finishes.
                # Timeout prevents permanent hang if the app exits mid-prompt.
                future.result(timeout=300)  # 5 min timeout for user response
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                # App was closed while waiting for permission — deny by default
                return False
            except TimeoutError:
                # User didn't respond within timeout — deny by default
                return False
            except Exception:
                # Event loop closed or other unexpected error — deny safely
                return False
            return result[0]
        # No prompt_toolkit app running — call permission UI directly (plain CLI)
        return _show_permission_ui(name, args)

    agent.permission_callback = _ask_permission

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
                    ("/provider", "Switch LLM provider"),
                    ("/kanban",   "Show Kanban board & cron jobs"),
                    ("/memory",   "Show working memory"),
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
        return False

    # ── Main loop — prompt_toolkit Application (split-pane UI) ──────────────────
    if _HAS_PT:
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from cli.ui import ChatLayout, StreamRenderer
        from cli.input_dispatcher import InputDispatcher

        layout = ChatLayout(on_submit=lambda t: None)  # placeholder
        renderer = StreamRenderer(
            layout,
            model_name=model_name,
            token_limit=token_limit,
            session_start=session_start,
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

        app = Application(
            layout=layout.create_layout(),
            full_screen=False,
            key_bindings=kb,
        )
        layout._app = app
        layout.set_status(renderer._format_status(_C("● Idle", "green")))

        # Render previous session history in output pane
        _prev_msgs = [m for m in agent.messages if m.get("role") in ("user", "assistant")]
        if len(_prev_msgs) > 0:
            layout.append_output(_C("  ── Previous session ──\n", "grey"))
            for m in _prev_msgs[-10:]:  # Show last 10 messages max
                if m["role"] == "user":
                    content = (m.get("content") or "")[:100]
                    layout.append_output(_C(f"  You: ", "blue") + content + "\n")
                elif m["role"] == "assistant":
                    content = (m.get("content") or "")[:150]
                    layout.append_output(_C(f"  Koza: ", "teal") + content + "\n")
            layout.append_output(_C("  ── End of history ──\n\n", "grey"))

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
                _C("\n  ● ", "yellow", "bold") + _C("You  › ", "cyan", "bold")
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
            print(_C("\n  Goodbye! 👋\n", "yellow"))
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
