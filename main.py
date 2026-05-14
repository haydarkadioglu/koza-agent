#!/usr/bin/env python3
"""Hermes Agent — Entry point."""
import argparse
import sys

from agent.config import load_config, config_exists, save_config


def main():
    parser = argparse.ArgumentParser(prog="hermes", description="Hermes AI Agent")
    parser.add_argument("--provider", help="Override LLM provider (openai/anthropic/deepseek/gemini/ollama)")
    parser.add_argument("--model", help="Override model name")
    parser.add_argument("--setup", action="store_true", help="Re-run setup wizard")
    parser.add_argument("--kanban", action="store_true", help="Open Kanban board")
    parser.add_argument("--no-tui", action="store_true", help="Run in plain CLI mode (no TUI)")
    args = parser.parse_args()

    # Setup wizard if first run or --setup flag
    if not config_exists() or args.setup:
        from agent.tui.setup_wizard import SetupWizard
        wizard = SetupWizard()
        result = wizard.run()
        if result is None:
            print("Setup cancelled.")
            sys.exit(0)
        cfg = result
    else:
        cfg = load_config()

    # Apply CLI overrides
    if args.provider:
        cfg["provider"] = args.provider
    if args.model:
        cfg["model"] = args.model

    # Build provider and agent
    from agent.providers.factory import get_provider
    from agent.core import Agent

    provider = get_provider(cfg)
    agent = Agent(provider, db_path=cfg["db_path"])

    # Standalone Kanban view
    if args.kanban:
        from agent.skills.kanban import init_db
        from agent.skills.cron import init_db as cron_init_db
        init_db(cfg["db_path"])
        cron_init_db(cfg["db_path"])
        from agent.tui.kanban_app import KanbanApp
        KanbanApp().run()
        return

    # Plain CLI mode
    if args.no_tui:
        print(f"Hermes Agent [{cfg['provider']} / {cfg.get('model','default')}]")
        print("Type 'exit' to quit, '/reset' to clear history, '/kanban' to show tasks.\n")
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                break
            if user_input == "/reset":
                agent.reset()
                print("Chat reset.\n")
                continue
            if user_input == "/kanban":
                from agent.skills.kanban import list_tasks
                from agent.skills.cron import list_crons
                print(list_tasks())
                print("\n--- CRON JOBS ---")
                print(list_crons())
                continue
            print("Hermes: ", end="", flush=True)
            for token in agent.stream_chat(user_input):
                print(token, end="", flush=True)
            print("\n")
        return

    # Default: full TUI
    from agent.tui.chat_app import ChatApp
    ChatApp(agent).run()


if __name__ == "__main__":
    main()
