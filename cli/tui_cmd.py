"""CLI command: koza tui — Textual cockpit."""
from __future__ import annotations

from cli.ui import _C, _print_error


def build_agent_from_config(cfg: dict, session_id: int | None = None):
    from providers.factory import get_provider
    from core import Agent

    agent = Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg)
    if session_id is not None:
        from skills.session_memory import load_session
        msgs = load_session(session_id)
        if not msgs:
            raise ValueError(f"Session #{session_id} not found or empty.")
        sys_msg = agent.messages[0] if agent.messages and agent.messages[0].get("role") == "system" else None
        agent.messages = ([sys_msg] if sys_msg else []) + msgs
        agent._active_session_id = session_id
    return agent


def init_tui_datastores(cfg: dict) -> None:
    from skills import kanban
    from skills.cron_db import init_db as cron_init
    from skills.session_memory import init_db as session_init
    from skills.shared_memory import init_db as shared_init
    from skills.working_memory import init_db as working_init

    db_path = cfg["db_path"]
    kanban.init_db(db_path)
    cron_init(db_path)
    session_init(db_path)
    shared_init(db_path)
    working_init(db_path)


def start_tui_background_services(cfg: dict) -> list[str]:
    services: list[str] = []
    try:
        from skills.cron_scheduler import get_scheduler
        get_scheduler()
        services.append("cron")
    except Exception:
        pass

    token = (
        cfg.get("telegram_token", "").strip()
        or cfg.get("messaging", {}).get("telegram", {}).get("token", "").strip()
    )
    if token:
        try:
            from koza_daemon import get_daemon_port
            if get_daemon_port() is not None:
                services.append("telegram daemon")
            else:
                from bots.telegram import start_bot_thread
                from providers.factory import get_provider

                def _agent_factory(channel: str = "telegram"):
                    from core import Agent
                    return Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg, channel=channel)

                if start_bot_thread(_agent_factory, cfg):
                    services.append("telegram")
        except Exception:
            pass
    return services


def cmd_tui(args: list) -> None:
    """Start the Textual Koza cockpit, falling back to plain CLI if needed."""
    from config import config_exists, load_config
    session_id: int | None = None

    if args and args[0] in ("--session", "session", "load"):
        if len(args) < 2:
            print(_C("  ✗  Usage: koza tui --session <id>", "red"))
            return
        try:
            session_id = int(args[1])
        except ValueError:
            print(_C(f"  ✗  Invalid session ID: {args[1]}", "red"))
            return

    if not config_exists():
        print(_C("  No config found. Running setup first...\n", "grey"))
        from cli.setup import cmd_setup
        cmd_setup([])

    cfg = load_config()
    try:
        import textual  # noqa: F401
        from tui.chat_app import ChatApp

        init_tui_datastores(cfg)
        services = start_tui_background_services(cfg)
        agent = build_agent_from_config(cfg, session_id=session_id)
        cfg.setdefault("_runtime", {})["services"] = services
        ChatApp(agent, cfg).run()
    except ImportError:
        print(_C("  Textual is not installed. Falling back to plain CLI.\n", "yellow"))
        print(_C("  Install with: pip install 'koza[tui]' or pip install textual\n", "grey"))
        from cli.chat import _plain_cli
        _plain_cli(build_agent_from_config(cfg, session_id=session_id), cfg)
    except Exception as exc:
        _print_error(exc, fatal=False)
        print(_C("  Falling back to plain CLI.\n", "yellow"))
        from cli.chat import _plain_cli
        _plain_cli(build_agent_from_config(cfg, session_id=session_id), cfg)
