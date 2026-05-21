"""Interactive plain CLI loop — sticky-bottom input with always-on prompt.

The prompt stays pinned at the bottom while the agent streams output above it.
Pressing Enter during processing interrupts the running request.
"""
import sys
import shutil
import time
import threading
import queue as _queue

from cli.ui import (
    _C, _hr, _print_error, _print_inline_help, _print_banner,
    _spinner_start, _spinner_stop, _spinner_set, _spinner_active_check,
    _select_menu,
)

# ── prompt_toolkit availability ───────────────────────────────────────────────
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.patch_stdout import patch_stdout as _pt_patch_stdout
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.application import get_app_or_none
    _HAS_PT = True
except ImportError:
    _HAS_PT = False


def _plain_cli(agent, cfg: dict) -> None:
    _print_banner(cfg)

    session_start = time.time()
    total_tokens  = 0

    _TOKEN_LIMITS = {
        "deepseek": 64_000, "openai": 128_000, "anthropic": 200_000,
        "gemini": 1_000_000, "ollama": 32_000,
    }
    provider_name = cfg.get("provider", "")
    model_name    = cfg.get("model") or provider_name
    token_limit   = _TOKEN_LIMITS.get(provider_name, 32_000)

    # ── Shared processing state ───────────────────────────────────────────────
    _processing  = threading.Event()   # set while agent is running
    _proc_thread = [None]              # current background thread

    # ── Tool permission system ────────────────────────────────────────────────
    _SAFE_TOOLS = {
        "web_search", "fetch_url", "list_dir", "read_file", "wm_add", "wm_get",
        "wm_list", "wm_clear", "wm_get_context",
        "memory_recall", "memory_search", "memory_list", "memory_store",
        "recall_sessions", "list_sessions", "list_tasks", "list_crons", "list_subagents",
        "get_subagent_status", "github_search_code", "github_list_prs",
        "github_repo_info", "pandas_query", "matplotlib_plot",
        "list_projects", "list_capabilities", "get_weather", "get_time",
        "calculator", "search_files", "get_cwd",
    }
    _session_allowed:  set = set()
    _permanent_allowed: set = set(cfg.get("allowed_tools", []))
    _session_allow_all  = [False]

    def _show_permission_ui(name: str, args: dict) -> bool:
        """Render the permission prompt — always runs in terminal context."""
        _spinner_stop()
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
        # When called from a background thread, use run_in_terminal so the
        # prompt_toolkit input bar is temporarily paused while we show the UI.
        app = get_app_or_none() if _HAS_PT else None
        if app is not None:
            result = [False]
            def _ui():
                result[0] = _show_permission_ui(name, args)
            app.run_in_terminal(_ui)
            return result[0]
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

    # ── Streaming processor (runs in background thread) ───────────────────────
    _TOOL_STATUS = {
        "web_search": "Searching the web", "fetch_url": "Fetching URL",
        "run_command": "Running command",   "run_python": "Running Python",
        "run_node": "Running Node.js",      "read_file": "Reading file",
        "write_file": "Writing file",       "list_dir": "Listing directory",
        "send_message": "Sending message",  "telegram_send": "Sending Telegram message",
        "discord_send": "Sending Discord message",
        "memory_store": "Saving to memory", "memory_recall": "Recalling memory",
        "github_search_code": "Searching GitHub",
        "github_create_issue": "Creating GitHub issue",
        "crypto_price": "Fetching crypto price", "stock_price": "Fetching stock price",
        "arxiv_search": "Searching arXiv", "wikipedia_search": "Searching Wikipedia",
        "get_config": "Checking config",   "set_config": "Updating config",
        "spawn_subagent": "Spawning sub-agent",
        "create_task": "Creating task",    "list_tasks": "Listing tasks",
    }

    def _process(user_input: str) -> None:
        nonlocal total_tokens
        _processing.set()
        t_start       = time.time()
        text_started  = False
        full_response = ""
        tw = shutil.get_terminal_size((100, 24)).columns

        def _open_box():
            """Print the Koza box header on first text token."""
            print()
            print(_C("  ╭─ Koza ", "yellow", "bold") + _C("─" * (tw - 10), "gold"))
            sys.stdout.write(_C("  │ ", "yellow"))
            sys.stdout.flush()

        def _write_token(token: str) -> None:
            """Write a streaming token, handling newlines with proper box indent."""
            if "\n" in token:
                parts = token.split("\n")
                for i, part in enumerate(parts):
                    if part:
                        sys.stdout.write(part)
                    if i < len(parts) - 1:
                        sys.stdout.write("\n" + _C("  │ ", "yellow"))
            else:
                sys.stdout.write(token)
            sys.stdout.flush()

        try:
            for event in agent.stream_chat(user_input):
                if not isinstance(event, dict):
                    continue
                etype = event.get("type")

                if etype == "interrupted":
                    _spinner_stop()
                    if text_started:
                        print()
                        print(_C("  ╰─", "yellow") + _C("  (interrupted)", "grey"))
                    else:
                        print(_C("\n  (interrupted)", "grey"))
                    break

                elif etype == "thinking":
                    if not text_started:
                        _spinner_start("  Thinking…")

                elif etype == "tool_start":
                    name    = event["name"]
                    args    = event.get("args", {})
                    arg_str = ", ".join(f"{k}={repr(v)}" for k, v in list(args.items())[:2])
                    label   = _TOOL_STATUS.get(name, f"Running {name}")
                    _spinner_set(f"  {label}…")
                    if not _spinner_active_check():
                        _spinner_start(f"  {label}…")
                    print(
                        "\r" + " " * 80 + "\r" +
                        _C(f"  ⚙  {name}", "cyan") +
                        (_C(f"  ({arg_str[:60]})", "grey") if arg_str else ""),
                        flush=True,
                    )

                elif etype == "tool_done":
                    _spinner_stop()
                    name    = event["name"]
                    elapsed = event.get("elapsed", 0)
                    result  = str(event.get("result", ""))
                    lines   = [l for l in result.splitlines() if l.strip()]
                    summary = (lines[0][:80] + ("…" if len(lines[0]) > 80 else "")) if lines else "(no output)"
                    extra   = _C(f"  +{len(lines)-1} lines", "grey") if len(lines) > 1 else ""
                    print(
                        _C(f"  ✓  {name}", "green") +
                        _C(f"  {elapsed:.2f}s", "grey") +
                        _C(f"  → {summary}", "white") + extra,
                        flush=True,
                    )
                    _spinner_start("  Thinking…")

                elif etype == "text":
                    token = event.get("token", "")
                    if not text_started:
                        _spinner_stop()
                        text_started = True
                        _open_box()
                    _write_token(token)
                    full_response += token
                    total_tokens  += max(1, len(token) // 4)

        except Exception as exc:
            _spinner_stop()
            print()
            _print_error(exc)
        finally:
            _spinner_stop()
            _processing.clear()

        if text_started and full_response.strip():
            elapsed = time.time() - t_start
            print()
            print(_C("  ╰─", "yellow") + _C(f"  {elapsed:.1f}s", "grey"))
            print()
            _status_bar()

    # ── Inline command handler ────────────────────────────────────────────────
    def _handle_inline(user_input: str) -> bool:
        """Returns True if input was a slash command (consumed)."""
        nonlocal total_tokens
        if user_input.lower() in ("exit", "quit"):
            _hr()
            print(_C("\n  Goodbye! 👋\n", "yellow"))
            _hr()
            return None  # signal exit
        if user_input == "/reset":
            agent.reset(); total_tokens = 0
            print(_C("  ✓  Chat reset.\n", "green"))
            return True
        if user_input == "/kanban":
            from cli.commands import cmd_kanban
            cmd_kanban([])
            return True
        if user_input == "/memory":
            from skills.working_memory import wm_get_context
            ctx = wm_get_context()
            _hr("·", "grey")
            print(ctx or _C("  (working memory is empty)", "dim"))
            _hr("·", "grey")
            return True
        if user_input in ("/help", "/?"):
            _print_inline_help()
            return True
        if user_input.startswith("/mode"):
            parts = user_input.split(None, 1)
            mode = parts[1].lower().strip() if len(parts) > 1 else ""
            if mode == "coding":
                print(_C("  Switching to Coding Mode…\n", "yellow"))
                from cli.coding_cmd import cmd_coding
                cmd_coding([])
                print(_C("  Back to normal mode.\n", "grey"))
                return True
            else:
                print(_C(f"  Unknown mode: {mode!r}. Try  /mode coding\n", "red"))
                return True
        return False

    # ── Main loop — prompt_toolkit (sticky bottom) ────────────────────────────
    if _HAS_PT:
        _pt_session = PromptSession(history=InMemoryHistory())

        def _prompt_text():
            if _processing.is_set():
                return HTML(
                    "<ansiyellow><b>  ⏎  Enter to interrupt › </b></ansiyellow>"
                )
            return HTML(
                "<ansigreen><b>  ● </b></ansigreen>"
                "<ansicyan><b>You  › </b></ansicyan>"
            )

        with _pt_patch_stdout():
            while True:
                try:
                    user_input = _pt_session.prompt(
                        _prompt_text,
                        refresh_interval=0.25,
                    ).strip()
                except KeyboardInterrupt:
                    if _processing.is_set():
                        agent.interrupt()
                        if _proc_thread[0]:
                            _proc_thread[0].join(timeout=3)
                    else:
                        _hr()
                        print(_C("\n  Goodbye! 👋\n", "yellow"))
                        _hr()
                        break
                    continue
                except EOFError:
                    _hr()
                    print(_C("\n  Goodbye! 👋\n", "yellow"))
                    _hr()
                    break

                # Enter pressed while processing → interrupt
                if _processing.is_set():
                    agent.interrupt()
                    if _proc_thread[0]:
                        _proc_thread[0].join(timeout=3)
                    continue

                if not user_input:
                    continue

                cmd = _handle_inline(user_input)
                if cmd is None:
                    break   # exit/quit
                if cmd:
                    continue

                total_tokens += max(1, len(user_input) // 4)
                _proc_thread[0] = threading.Thread(
                    target=_process, args=(user_input,), daemon=True
                )
                _proc_thread[0].start()

        # Wait for any running thread before returning
        if _proc_thread[0] and _proc_thread[0].is_alive():
            agent.interrupt()
            _proc_thread[0].join(timeout=3)
        return

    # ── Fallback: simple blocking loop (no prompt_toolkit) ────────────────────
    while True:
        try:
            user_input = input(
                _C("\n  ● ", "yellow", "bold") + _C("You  › ", "cyan", "bold")
            ).strip()
        except (EOFError, KeyboardInterrupt):
            _hr()
            print(_C("\n  Goodbye! 👋\n", "yellow"))
            _hr()
            break

        if not user_input:
            continue
        cmd = _handle_inline(user_input)
        if cmd is None:
            break
        if cmd:
            continue

        total_tokens += max(1, len(user_input) // 4)
        try:
            _process(user_input)
        except KeyboardInterrupt:
            _spinner_stop()
            agent.interrupt()
            print(_C("\n  (interrupted)", "grey"))
