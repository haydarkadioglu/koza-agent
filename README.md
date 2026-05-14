# 🪽 Koza Agent

> A powerful, extensible AI agent that runs entirely in your terminal — with a rich TUI, 96 tools across 25+ skill categories, dual memory, sub-agents, and cross-platform scheduling.

---

## Features

| Category | What it does |
|---|---|
| **Multi-LLM** | OpenAI, Anthropic, DeepSeek, Gemini, Ollama (local) |
| **Rich TUI** | Textual-based chat UI, setup wizard, and Kanban board — navigate with arrow keys |
| **96 Tools** | Files, shell, web, code runner, GitHub, research, crypto, smart home, media, and more |
| **Kanban + Cron** | Task management board + scheduled jobs (syncs to OS crontab / Windows Task Scheduler) |
| **Dual Memory** | Working memory (short-term ring buffer) + Permanent shared memory (cross-session SQLite) |
| **Sub-agents** | Spawn autonomous sub-agents with their own tool loops in background threads |
| **Messaging** | Send/receive via Telegram, Discord, WhatsApp (Twilio) |
| **Session Recall** | Every conversation is saved and searchable across sessions |

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run — setup wizard launches on first start
python main.py
```

---

## Commands

```bash
python main.py              # Launch TUI (runs setup wizard on first start)
python main.py setup        # Re-run setup wizard (providers, API keys)
python main.py config       # Show current configuration (keys masked)
python main.py kanban       # Open Kanban board
python main.py start --plain  # Plain terminal mode (no TUI)
python main.py uninstall    # Remove ~/.koza config and database
python main.py help         # Show all commands
```

---

## Configuration

Config file: `~/.koza/config.yaml`  
Database:    `~/.koza/koza.db`

You can also set API keys via environment variables or a `.env` file (see `.env.example`):

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=...
GEMINI_API_KEY=...
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
DISCORD_WEBHOOK_URL=...
GITHUB_TOKEN=...
```

---

## Project Structure

```
koza-agent/
├── main.py                     # Entry point + CLI command dispatch
├── core.py                     # Agent loop (tool-calling orchestration)
├── config.py                   # Config load/save + ENV overrides
├── requirements.txt
│
├── providers/                  # LLM backends
│   ├── base.py
│   ├── factory.py
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   ├── deepseek_provider.py
│   ├── gemini_provider.py
│   └── ollama_provider.py
│
├── skills/                     # Tool skill modules (96 tools total)
│   ├── filesystem.py           # read/write/list/delete files
│   ├── shell.py                # run shell commands (pwsh/bash)
│   ├── web.py                  # web search + URL fetch
│   ├── code_runner.py          # run Python / Node / scripts
│   ├── system_info.py          # OS info, env vars, processes
│   ├── kanban.py               # Kanban task management
│   ├── cron.py                 # Cron job orchestrator (thin)
│   ├── cron_db.py              # Cron SQLite layer
│   ├── cron_scheduler.py       # APScheduler + OS sync
│   ├── session_memory.py       # Per-session conversation recall
│   ├── shared_memory.py        # Permanent cross-session memory
│   ├── working_memory.py       # Short-term ring buffer (last 20 events)
│   ├── agents/                 # Sub-agent engine (package)
│   │   ├── __init__.py         # spawn/status/list tools
│   │   ├── runner.py           # background thread runner
│   │   └── _registry.py       # in-memory agent registry
│   ├── messaging/              # Messaging integrations (package)
│   │   ├── __init__.py         # unified router + tools
│   │   ├── telegram.py
│   │   ├── discord.py
│   │   └── whatsapp.py
│   ├── creative.py             # ASCII art, diagrams, image gen
│   ├── datascience.py          # Jupyter, pandas, matplotlib
│   ├── devops.py               # Git, Docker, webhooks
│   ├── email_skill.py          # Send/read email (SMTP/IMAP)
│   ├── finance.py              # Crypto + stock prices
│   ├── gaming.py               # Minecraft, Pokémon
│   ├── github_skill.py         # GitHub API (search, issues, PRs)
│   ├── mcp_skill.py            # MCP tool bridge
│   ├── media.py                # Spotify, YouTube, GIFs
│   ├── mlops.py                # HuggingFace, evals, benchmarks
│   ├── notes.py                # Obsidian / markdown vault
│   ├── productivity.py         # Google Calendar, Sheets, Airtable
│   ├── research.py             # arXiv, Wikipedia, Polymarket
│   ├── security.py             # Port scan, SSL, WHOIS, headers
│   ├── smarthome.py            # Philips Hue, MQTT, Home Assistant
│   └── social.py               # Twitter/X, Reddit, Mastodon
│
├── tools/
│   └── registry.py             # ALL_TOOLS + ALL_HANDLERS assembly
│
└── tui/
    ├── setup_wizard.py         # First-run setup (Textual)
    ├── chat_app.py             # Main chat interface
    └── kanban_app.py           # Kanban board
```

---

## Documentation

Detailed guides live in the [`docs/`](docs/) folder:

| Guide | Description |
|---|---|
| [Installation](docs/installation.md) | Full install, venv setup, optional deps |
| [Configuration](docs/configuration.md) | All config keys, ENV vars, provider setup |
| [Skills & Tools](docs/skills.md) | All 96 tools listed by category |
| [Memory System](docs/memory.md) | Working memory + permanent memory architecture |
| [Sub-agents](docs/subagents.md) | How to spawn and use sub-agents |
| [Messaging](docs/messaging.md) | Telegram, Discord, WhatsApp setup |
| [Kanban & Cron](docs/kanban-cron.md) | Task management and scheduling |

---

## License

MIT

