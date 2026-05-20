"""Interactive plain CLI loop."""
import sys
import re as _re
import shutil
import time

from cli.ui import (
    _C, _hr, _print_error, _print_inline_help, _print_banner,
    _spinner_start, _spinner_stop, _render_md, _select_menu,
)


def _plain_cli(agent, cfg: dict) -> None:
    _print_banner(cfg)

    session_start = time.time()
    total_tokens = 0

    # Token limits per provider (rough estimates)
    _TOKEN_LIMITS = {
        "deepseek": 64_000, "openai": 128_000, "anthropic": 200_000,
        "gemini": 1_000_000, "ollama": 32_000,
    }
    provider_name = cfg.get("provider", "")
    model_name = cfg.get("model") or provider_name
    token_limit = _TOKEN_LIMITS.get(provider_name, 32_000)

    # ── Tool permission system ────────────────────────────────────────────────
    # Tools that are always auto-allowed (read-only / non-destructive)
    _SAFE_TOOLS = {
        "web_search", "fetch_url", "list_dir", "read_file", "wm_add", "wm_get",
        "memory_recall", "memory_search", "memory_list", "recall_sessions",
        "list_sessions", "list_tasks", "list_crons", "list_subagents",
        "get_subagent_status", "github_search_code", "github_list_prs",
        "github_repo_info", "pandas_query", "matplotlib_plot",
    }
    _session_allowed: set = set()
    _permanent_allowed: set = set(cfg.get("allowed_tools", []))
    _session_allow_all = [False]  # mutable flag for closure

    def _ask_permission(name: str, args: dict) -> bool:
        if _session_allow_all[0]:
            return True
        if name in _SAFE_TOOLS or name in _session_allowed or name in _permanent_allowed:
            return True
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
                ["Allow (this session)", "Allow all tools (this session)", "Allow permanently", "Allow (once)", "Deny"],
                default_idx=0,
            )
        except (KeyboardInterrupt, EOFError):
            return False

        if choice == "Allow (this session)":
            _session_allowed.add(name)
            return True
        elif choice == "Allow all tools (this session)":
            _session_allow_all[0] = True
            print(_C("  ✓  Bu oturumda tüm tool'lar otomatik izinli.\n", "green"))
            return True
        elif choice == "Allow permanently":
            _permanent_allowed.add(name)
            try:
                from config import load_config, save_config
                c = load_config()
                existing = set(c.get("allowed_tools", []))
                existing.add(name)
                c["allowed_tools"] = sorted(existing)
                save_config(c)
            except Exception:
                pass
            return True
        elif choice == "Allow (once)":
            return True
        else:
            print(_C(f"  ✗  {name} denied.\n", "red"))
            return False

    agent.permission_callback = _ask_permission

    # Inject launch CWD into the agent's system prompt so model knows where it is
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
        pct = min(100, int(total_tokens / token_limit * 100))
        bar_w = 12
        filled = int(bar_w * pct / 100)
        bar = "█" * filled + "░" * (bar_w - filled)
        tok_str = f"{total_tokens//1000}K/{token_limit//1000}K" if total_tokens >= 1000 else f"{total_tokens}/{token_limit//1000}K"
        tw = shutil.get_terminal_size((100, 24)).columns
        line = (
            f"  {_C(model_name, 'cyan')}  {_C('│', 'grey')}  "
            f"{_C(tok_str, 'white')}  {_C('│', 'grey')}  "
            f"[{_C(bar, 'green' if pct < 70 else 'yellow' if pct < 90 else 'red')}]  "
            f"{_C(f'{pct}%', 'grey')}  {_C('│', 'grey')}  "
            f"{_C(s_time, 'grey')}"
        )
        print(_C("─" * tw, "grey"))
        print(line)
        print(_C("─" * tw, "grey"))

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
        if user_input.lower() in ("exit", "quit"):
            _hr()
            print(_C("\n  Goodbye! 👋\n", "yellow"))
            _hr()
            break
        if user_input == "/reset":
            agent.reset()
            total_tokens = 0
            print(_C("  ✓  Chat reset.\n", "green"))
            continue
        if user_input == "/kanban":
            from cli.commands import cmd_kanban
            cmd_kanban([])
            continue
        if user_input == "/memory":
            from skills.working_memory import wm_get_context
            ctx = wm_get_context()
            _hr("·", "grey")
            print(ctx or _C("  (working memory is empty)", "dim"))
            _hr("·", "grey")
            continue
        if user_input in ("/help", "/?"):
            _print_inline_help()
            continue

        # Rough token estimate for user message (4 chars ≈ 1 token)
        total_tokens += max(1, len(user_input) // 4)

        # ── Streaming response with live status ──────────────────────────────
        t_start = time.time()
        text_started = False
        full_response = ""

        try:
            for event in agent.stream_chat(user_input):
                if not isinstance(event, dict):
                    continue

                etype = event.get("type")

                if etype == "thinking":
                    if not text_started:
                        _spinner_start("  Koza is thinking…")

                elif etype == "tool_start":
                    _spinner_stop()
                    name = event["name"]
                    args = event.get("args", {})
                    arg_str = ", ".join(f"{k}={repr(v)}" for k, v in list(args.items())[:2])
                    print(
                        _C(f"  ⚙  {name}", "cyan") +
                        (_C(f"  ({arg_str})", "grey") if arg_str else ""),
                        flush=True
                    )
                    _spinner_start(f"  Running {name}…")

                elif etype == "tool_done":
                    _spinner_stop()
                    name = event["name"]
                    elapsed = event.get("elapsed", 0)
                    result = str(event.get("result", ""))
                    lines = [l for l in result.splitlines() if l.strip()]
                    summary = lines[0][:80] + ("…" if len(lines[0]) > 80 else "") if lines else "(no output)"
                    extra = _C(f"  +{len(lines)-1} lines", "grey") if len(lines) > 1 else ""
                    print(
                        _C(f"  ✓  {name}", "green") +
                        _C(f"  {elapsed:.2f}s", "grey") +
                        _C(f"  → {summary}", "white") + extra,
                        flush=True
                    )

                elif etype == "text":
                    token = event.get("token", "")
                    if not text_started:
                        _spinner_stop()
                        text_started = True
                    full_response += token
                    total_tokens += max(1, len(token) // 4)

        except KeyboardInterrupt:
            _spinner_stop()
            print(_C("\n  (interrupted)", "grey"))
            continue
        except Exception as exc:
            _spinner_stop()
            print()
            _print_error(exc)
            continue

        _spinner_stop()
        if text_started and full_response.strip():
            elapsed = time.time() - t_start
            tw = shutil.get_terminal_size((100, 24)).columns
            # ── Render buffered response with markdown ────────────────────────
            rendered_lines = _render_md(full_response).splitlines()
            print()
            print(_C("  ╭─ Koza ", "yellow", "bold") + _C("─" * (tw - 10), "gold"))
            for rline in rendered_lines:
                # Strip ANSI to measure actual display length for padding
                plain_len = len(_re.sub(r"\x1b\[[^m]*m", "", rline))
                if plain_len == 0 and not rline.strip():
                    print(_C("  │", "yellow"))
                else:
                    print(_C("  │ ", "yellow") + rline)
            print(_C("  ╰─", "yellow") + _C(f"  {elapsed:.1f}s", "grey"))
            print()
            _status_bar()
        print()
