"""
Tool permission system for the CLI chat interface.

Extracted from cli/chat.py to keep it maintainable as a standalone module.
Usage:
    from cli.permissions import make_permission_callback
    agent.permission_callback = make_permission_callback(cfg)
"""
"""
Tool permission system for the CLI chat interface.

Extracted from cli/chat.py to keep it maintainable as a standalone module.
Usage:
    from cli.permissions import make_permission_callback
    agent.permission_callback = make_permission_callback(cfg)
"""
from __future__ import annotations

# ── Tools that are always auto-approved (no prompt needed) ────────────────────
SAFE_TOOLS: frozenset[str] = frozenset({
    # Web & search
    "web_search", "fetch_url",
    # Filesystem (excluding modification tools)
    "list_dir", "read_file", "create_dir",
    "search_files", "get_cwd", "list_projects",
    # Shell / code (none are auto-approved)
    # Memory
    "wm_add", "wm_get", "wm_list", "wm_clear", "wm_get_context",
    "memory_recall", "memory_search", "memory_list", "memory_store",
    "recall_sessions", "list_sessions",
    # Kanban & Cron
    "list_tasks", "add_task", "update_task", "delete_task", "move_task",
    "list_crons", "create_cron", "add_cron", "delete_cron", "run_cron",
    # Multi-host sync
    "sync_status", "sync_now", "list_hosts",
    # Sub-agents
    "list_subagents", "get_subagent_status", "subagent_get_result",
    "subagent_delete", "subagent_update", "spawn_subagent",
    "start_background_task", "get_background_status",
    "list_background_tasks", "cancel_background_task",
    "list_capabilities",
    # Config
    "get_config",
    # Messaging
    "send_message", "get_messages",
    "telegram_send", "telegram_get_updates", "telegram_send_photo",
    "telegram_send_video", "telegram_set_webhook",
    "telegram_status", "start_telegram_daemon",
    "discord_send", "discord_get_messages",
    "whatsapp_send",
    # GitHub
    "github_search_code", "github_list_prs", "github_repo_info",
    # Data science
    "pandas_query", "matplotlib_plot",
    # Utilities
    "get_weather", "get_time", "calculator",
    "get_env_var", "set_env_var", "list_env_vars",
    # Image gen
    "generate_image",
})


def _show_permission_ui(name: str, args: dict, select_fn) -> str:
    """Render the interactive permission prompt in the terminal.

    Returns the choice string.
    ``select_fn`` is injected so this function doesn't depend on cli.ui directly.
    """
    from cli.ui import _C

    arg_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in list(args.items())[:3])
    print()
    print(_C("  ┌─ Permission Required ", "yellow", "bold") + _C("─" * 40, "gold"))
    print(_C("  │  Tool  : ", "grey") + _C(name, "cyan", "bold"))
    if arg_preview:
        print(_C("  │  Args  : ", "grey") + _C(arg_preview, "white"))
    print(_C("  └" + "─" * 53, "yellow"))
    try:
        choice = select_fn(
            "Allow this tool?",
            ["Allow (this session)", "Allow all tools (this session)",
             "Allow permanently", "Allow (once)", "Edit arguments", "Deny"],
            default_idx=0,
        )
    except (KeyboardInterrupt, EOFError):
        return "Deny"
    return choice


def make_permission_callback(cfg: dict):
    """
    Build and return a permission callback function for an Agent.

    The returned callable has signature ``(tool_name: str, tool_args: dict) -> bool``
    and manages its own session/permanent allow sets.
    """
    from cli.ui import _C, _select_menu, _spinner_stop

    _session_allowed:   set[str] = set()
    _permanent_allowed: set[str] = set(cfg.get("allowed_tools", []))
    _session_allow_all            = [False]
    _approval_enabled = bool(cfg.get("tool_approval", False))

    # Check prompt_toolkit availability once
    try:
        from prompt_toolkit.application import get_app_or_none
        _HAS_PT = True
    except ImportError:
        get_app_or_none = lambda: None  # noqa: E731
        _HAS_PT = False

    def _ui(name: str, args: dict) -> bool:
        """Run the interactive permission UI, handling approve/deny + persisting permanently."""
        choice = _show_permission_ui(name, args, _select_menu)
        if choice == "Allow (this session)":
            _session_allowed.add(name)
            return True
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
                existing.add(name)
                c["allowed_tools"] = sorted(existing)
                save_config(c)
            except Exception:
                pass
            return True
        if choice == "Allow (once)":
            return True
        if choice == "Edit arguments":
            import json
            print(_C("\n  📝 Current Arguments (JSON):", "yellow"))
            print(json.dumps(args, indent=2))
            print(_C("  Enter new JSON arguments (leave empty to cancel edit):", "yellow"))
            try:
                new_json = input("  JSON: ").strip()
                if new_json:
                    edited_args = json.loads(new_json)
                    args.clear()
                    args.update(edited_args)
                    print(_C("  ✓  Arguments updated.", "green"))
            except Exception as e:
                print(_C(f"  ❌ Invalid JSON: {e}", "red"))
            # Re-ask permission with updated (or unchanged) arguments
            return _ui(name, args)
        print(_C(f"  ✗  {name} denied.\n", "red"))
        return False

    def _ask_permission(name: str, args: dict) -> bool:
        if not _approval_enabled:
            return True
        if _session_allow_all[0]:
            return True
        if name in SAFE_TOOLS or name in _session_allowed or name in _permanent_allowed:
            return True

        _spinner_stop()

        # If a prompt_toolkit Application is running, suspend TUI, run in terminal
        pt_app = get_app_or_none() if _HAS_PT else None
        if (pt_app is not None and pt_app.is_running
                and pt_app.loop is not None and pt_app.loop.is_running()):
            import asyncio
            from prompt_toolkit.application import run_in_terminal

            result = [False]

            def _permission_in_terminal():
                result[0] = _ui(name, args)

            try:
                coro = run_in_terminal(_permission_in_terminal, render_cli_done=False)
                try:
                    future = asyncio.run_coroutine_threadsafe(coro, pt_app.loop)
                except Exception:
                    coro.close()
                    return _ui(name, args)
                future.result(timeout=300)
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                return _ui(name, args)
            except TimeoutError:
                return _ui(name, args)
            except Exception:
                return _ui(name, args)
            return result[0]

        return _ui(name, args)

    return _ask_permission
