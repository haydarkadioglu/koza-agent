"""Daemon connection commands."""
import sys
import os
import json

from cli.ui import (
    _C, _hr, _print_banner, _print_inline_help, _print_error,
    _spinner_start, _spinner_stop, _render_md, _select_menu,
)
from cli.chat import _plain_cli


def cmd_start(args: list) -> None:
    """Start Koza — launches daemon if needed, then connects CLI to it."""
    from config import load_config, config_exists
    if not config_exists():
        print(_C("  No config found. Running setup first…\n", "grey"))
        from cli.setup import cmd_setup
        cmd_setup([])

    # --standalone bypasses daemon (debug / single-process mode)
    if "--standalone" in args:
        try:
            cfg = load_config()
            from providers.factory import get_provider
            from core import Agent
            agent = Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg)
        except Exception as exc:
            _print_error(exc, fatal=True)
            return
        _plain_cli(agent, cfg)
        return

    cfg = load_config()

    from koza_daemon import get_daemon_port, start_as_background
    port = get_daemon_port()
    if not port:
        # Try to start daemon silently
        ok = start_as_background()
        if ok:
            port = get_daemon_port()

    if port:
        # Try to connect to daemon
        import socket as _sock
        try:
            test = _sock.create_connection(("127.0.0.1", port), timeout=3)
            test.close()
            _daemon_cli(port, cfg)
            return
        except Exception:
            pass

    # Daemon not available — fall back to standalone silently
    try:
        from providers.factory import get_provider
        from core import Agent
        agent = Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg)
    except Exception as exc:
        _print_error(exc, fatal=True)
        return
    _plain_cli(agent, cfg)


def cmd_status(args: list) -> None:
    """Show whether the Koza daemon is running."""
    from koza_daemon import get_daemon_port, PID_FILE
    port = get_daemon_port()
    if port:
        pid = PID_FILE.read_text().strip()
        print(_C(f"\n  ✓  Koza daemon running  (PID {pid}, port {port})\n", "green"))
    else:
        print(_C("\n  ✗  Koza daemon is not running. Start with: koza\n", "grey"))


def cmd_quit(args: list) -> None:
    """Stop the Koza daemon completely."""
    import socket as _sock, json as _json
    from koza_daemon import get_daemon_port
    port = get_daemon_port()
    if not port:
        print(_C("\n  Daemon is not running.\n", "grey"))
        return
    try:
        conn = _sock.create_connection(("127.0.0.1", port), timeout=5)
        conn.sendall((_json.dumps({"type": "quit"}) + "\n").encode())
        conn.settimeout(5)
        conn.recv(128)
        conn.close()
        print(_C("\n  ✓  Koza daemon stopped.\n", "green"))
    except Exception:
        # Force kill via PID
        try:
            from koza_daemon import PID_FILE
            pid = int(PID_FILE.read_text().strip())
            import signal as _sig
            os.kill(pid, _sig.SIGTERM)
            print(_C("\n  ✓  Koza daemon stopped (SIGTERM).\n", "green"))
        except Exception as e:
            print(_C(f"\n  ✗  Could not stop daemon: {e}\n", "red"))


def _daemon_cli(port: int, cfg: dict) -> None:
    """Interactive CLI loop connected to Koza daemon via localhost socket."""
    import re as _re
    import shutil
    import socket as _sock
    import time

    try:
        conn = _sock.create_connection(("127.0.0.1", port), timeout=5)
    except Exception as e:
        print(_C(f"\n  ✗  Could not connect to daemon: {e}\n", "red"))
        return

    _print_banner(cfg)

    # ── Recv thread ──────────────────────────────────────────────────────────
    import queue as _queue
    recv_q: _queue.Queue = _queue.Queue()

    def _recv():
        buf = ""
        conn.settimeout(0.5)
        while True:
            try:
                data = conn.recv(4096).decode("utf-8", errors="replace")
                if not data:
                    recv_q.put({"type": "_closed"})
                    return
                buf += data
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            recv_q.put(json.loads(line))
                        except Exception:
                            pass
            except _sock.timeout:
                continue
            except Exception:
                recv_q.put({"type": "_closed"})
                return

    import threading as _th
    _th.Thread(target=_recv, daemon=True).start()

    def _send(data: dict):
        try:
            conn.sendall((json.dumps(data, ensure_ascii=False) + "\n").encode())
        except Exception:
            pass

    # ── Permission helpers (shared with _plain_cli) ──────────────────────────
    _SAFE_TOOLS = {
        "web_search", "fetch_url", "list_dir", "read_file", "wm_add", "wm_get",
        "memory_recall", "memory_search", "memory_list", "recall_sessions",
        "list_sessions", "list_tasks", "list_crons", "list_subagents",
        "get_subagent_status", "github_search_code", "github_list_prs",
        "github_repo_info", "pandas_query", "matplotlib_plot",
        "get_config",
    }
    _session_allowed: set = set()
    _permanent_allowed: set = set(cfg.get("allowed_tools", []))
    _session_allow_all = [False]

    def _handle_permission(name: str, args: dict) -> bool:
        if _session_allow_all[0]:
            _send({"type": "permission_response", "allowed": True})
            return True
        if name in _SAFE_TOOLS or name in _session_allowed or name in _permanent_allowed:
            _send({"type": "permission_response", "allowed": True})
            return True
        _spinner_stop()
        arg_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in list(args.items())[:3])
        print()
        print(_C("  ┌─ Permission Required ", "yellow", "bold") + _C("─" * 40, "gold"))
        print(_C("  │  Tool  : ", "grey") + _C(name, "cyan", "bold"))
        if arg_preview:
            print(_C("  │  Args  : ", "grey") + _C(arg_preview, "white"))
        print(_C("  └" + "─" * 53, "yellow"))
        choice = _select_menu(
            "Allow this tool?",
            ["Allow (this session)", "Allow all tools (this session)",
             "Allow permanently", "Allow (once)", "Deny"],
            default_idx=0,
        )
        allowed = True
        if choice == "Allow (this session)":
            _session_allowed.add(name)
        elif choice == "Allow all tools (this session)":
            _session_allow_all[0] = True
            print(_C("  ✓  All tools allowed for this session.\n", "green"))
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
        elif choice == "Allow (once)":
            pass
        else:
            allowed = False
            print(_C(f"  ✗  {name} denied.\n", "red"))
        _send({"type": "permission_response", "allowed": allowed})
        return allowed

    # ── Status bar ───────────────────────────────────────────────────────────
    session_start = time.time()
    total_tokens  = 0
    _TOKEN_LIMITS = {
        "deepseek": 64_000, "openai": 128_000, "anthropic": 200_000,
        "gemini": 1_000_000, "ollama": 32_000,
    }
    provider_name = cfg.get("provider", "")
    model_name    = cfg.get("model") or provider_name
    token_limit   = _TOKEN_LIMITS.get(provider_name, 32_000)

    def _status_bar():
        elapsed = int(time.time() - session_start)
        h, m  = divmod(elapsed // 60, 60)
        s_time = f"{h}h {m:02d}m" if h else f"{m}m"
        pct   = min(100, int(total_tokens / token_limit * 100))
        bar_w = 12
        filled = int(bar_w * pct / 100)
        bar = "█" * filled + "░" * (bar_w - filled)
        tok_str = (f"{total_tokens//1000}K/{token_limit//1000}K"
                   if total_tokens >= 1000 else f"{total_tokens}/{token_limit//1000}K")
        tw = shutil.get_terminal_size((100, 24)).columns
        color = "green" if pct < 70 else "yellow" if pct < 90 else "red"
        print(_C("─" * tw, "grey"))
        print(
            f"  {_C(model_name,'cyan')}  {_C('│','grey')}  "
            f"{_C(tok_str,'white')}  {_C('│','grey')}  "
            f"[{_C(bar, color)}]  {_C(f'{pct}%','grey')}  "
            f"{_C('│','grey')}  {_C(s_time,'grey')}"
            f"  {_C('│','grey')}  {_C('daemon','teal')}"
        )
        print(_C("─" * tw, "grey"))

    # ── Main input loop ──────────────────────────────────────────────────────
    while True:
        try:
            user_input = input(
                _C("\n  ● ", "yellow", "bold") + _C("You  › ", "cyan", "bold")
            ).strip()
        except (EOFError, KeyboardInterrupt):
            _hr()
            print(_C("\n  Console closed. Koza keeps running in the background.\n", "teal"))
            print(_C("  Reconnect:  koza\n", "grey"))
            print(_C("  Quit fully: koza quit\n", "grey"))
            _hr()
            _send({"type": "disconnect"})
            break

        if not user_input:
            continue
        if user_input.lower() == "exit":
            _hr()
            print(_C("\n  Console closed. Koza keeps running in the background.\n", "teal"))
            print(_C("  Reconnect:  koza\n  Quit fully: koza quit\n", "grey"))
            _hr()
            _send({"type": "disconnect"})
            break
        if user_input.lower() in ("quit", "/quit"):
            print(_C("\n  Stopping Koza daemon…\n", "yellow"))
            _send({"type": "quit"})
            try:
                recv_q.get(timeout=5)
            except _queue.Empty:
                pass
            break
        if user_input == "/reset":
            print(_C("  ℹ  Reset not supported in daemon mode. Reconnect for a fresh session.\n", "grey"))
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

        total_tokens += max(1, len(user_input) // 4)
        _send({"type": "chat", "text": user_input})

        # ── Collect & render response ────────────────────────────────────────
        t_start      = time.time()
        text_started = False
        full_response = ""

        try:
            while True:
                try:
                    event = recv_q.get(timeout=120)
                except _queue.Empty:
                    print(_C("\n  ⚠  Response timeout.\n", "yellow"))
                    break

                etype = event.get("type")

                if etype == "_closed":
                    print(_C("\n  ✗  Daemon connection lost.\n", "red"))
                    return

                elif etype == "done":
                    break

                elif etype == "thinking":
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
                        flush=True,
                    )
                    _spinner_start(f"  Running {name}…")

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

                elif etype == "text":
                    token = event.get("token", "")
                    if not text_started:
                        _spinner_stop()
                        text_started = True
                    full_response += token
                    total_tokens  += max(1, len(token) // 4)

                elif etype == "interrupted":
                    _spinner_stop()
                    print(_C("\n  (interrupted)", "grey"))
                    break

                elif etype == "tool_denied":
                    _spinner_stop()
                    print(_C(f"\n  ✗  {event.get('name','')} denied\n", "red"))

                elif etype == "permission_required":
                    _handle_permission(event.get("name", ""), event.get("args", {}))

                elif etype == "error":
                    _spinner_stop()
                    print(_C(f"\n  ✗  {event.get('message','Unknown error')}\n", "red"))
                    break

        except KeyboardInterrupt:
            _spinner_stop()
            print(_C("\n  (interrupted)", "grey"))
            _send({"type": "disconnect"})
            break

        _spinner_stop()
        if text_started and full_response.strip():
            elapsed = time.time() - t_start
            tw = shutil.get_terminal_size((100, 24)).columns
            rendered_lines = _render_md(full_response).splitlines()
            print()
            print(_C("  ╭─ Koza ", "yellow", "bold") + _C("─" * (tw - 10), "gold"))
            for rline in rendered_lines:
                plain_len = len(_re.sub(r"\x1b\[[^m]*m", "", rline))
                if plain_len == 0 and not rline.strip():
                    print(_C("  │", "yellow"))
                else:
                    print(_C("  │ ", "yellow") + rline)
            print(_C("  ╰─", "yellow") + _C(f"  {elapsed:.1f}s", "grey"))
            print()
            _status_bar()
        print()
