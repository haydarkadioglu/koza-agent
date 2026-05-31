# Koza Agent &nbsp;[![Version](https://img.shields.io/badge/version-v1.4.*-cyan)](https://github.com/haydarkadioglu/koza-agent/releases)

```
   ██╗  ██╗ ██████╗ ███████╗ █████╗
   ██║ ██╔╝██╔═══██╗╚══███╔╝██╔══██╗
   █████╔╝ ██║   ██║  ███╔╝ ███████║
   ██╔═██╗ ██║   ██║ ███╔╝  ██╔══██║
   ██║  ██╗╚██████╔╝███████╗██║  ██║
   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
```

> A powerful, extensible AI agent that runs entirely in your terminal, 99+ tools across 25+ skill categories, dual memory, sub-agents, Telegram bot, and cross-platform scheduling.

---

## Quick Install

### Windows — one-liner (PowerShell)

```powershell
irm https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/install.ps1 | iex
```

> If you're using PowerShell 5.1 (Windows built-in) and get a TLS error:
> ```powershell
> [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; irm https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/install.ps1 | iex
> ```

### Linux / macOS — one-liner

```bash
curl -fsSL https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/install.sh | bash
```

Both scripts will:
- Clone the repo to `~/.koza-agent/` (via git if available, otherwise ZIP download)
- Automatically create a virtualenv
- Install all dependencies
- Add the `koza` command to PATH
- Re-running updates an existing installation

> **Requirements:** Python 3.11+ (git optional — falls back to ZIP download)  
> Windows: [python.org](https://python.org/downloads)  
> macOS: `brew install python@3.12` · Debian/Ubuntu: `sudo apt install python3.12`



## Features

| Category | What it does |
|---|---|
| **Multi-LLM** | OpenAI, Anthropic, DeepSeek, Gemini, Ollama (local), GitHub Models |
| **Rich TUI** | Textual-based chat UI, setup wizard, and Kanban board — navigate with arrow keys |
| **99+ Tools** | Files, shell, web, code runner, GitHub, research, crypto, smart home, media, and more |
| **Kanban + Cron** | Task management board + scheduled jobs (syncs to OS crontab / Windows Task Scheduler) |
| **Dual Memory** | Working memory (short-term ring buffer) + Permanent shared memory (cross-session SQLite) |
| **Sub-agents** | Spawn autonomous sub-agents with their own tool loops in background threads |
| **Messaging** | Telegram bot (auto-start, owner registration), Discord, WhatsApp (Twilio) |
| **Config via Chat** | Tell Koza your API keys directly — it saves them without you touching config files |
| **Session Recall** | Every conversation is saved and searchable across sessions |

---

## Commands

```bash
koza              # Launch (setup wizard on first start)
koza setup        # Re-run setup wizard
koza config       # Show current configuration (keys masked)
koza kanban       # Open Kanban board
koza telegram     # Configure & start Telegram bot
koza version      # Show version
koza help         # Show all commands
```

---

## Configuration

Config file: `~/.Koza/config.yaml`  
Database:    `~/.Koza/koza.db`

### Configure via chat (recommended)

Just tell Koza what you want to set:

```
"my deepseek api key is sk-abc123"
"set openai model to gpt-4o-mini"
"my telegram token is 1234567:ABC..."
"which provider is currently active"
```

### Environment variables / `.env` file

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=...
GEMINI_API_KEY=...
GITHUB_TOKEN=ghp-...
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
DISCORD_WEBHOOK_URL=...
```

### Supported providers

| Provider | Config key | Notes |
|---|---|---|
| `openai` | `providers.openai.api_key` | GPT-4o, o1, etc. |
| `anthropic` | `providers.anthropic.api_key` | Claude 3.5 Sonnet, etc. |
| `deepseek` | `providers.deepseek.api_key` | deepseek-chat, deepseek-reasoner |
| `gemini` | `providers.gemini.api_key` | Gemini 2.0 Flash, etc. |
| `ollama` | `providers.ollama.base_url` | Local models (default: localhost:11434) |
| `github` | `providers.github.token` | GitHub Models (free tier via GitHub token) |

---

## Project Structure

```
koza-agent/
├── koza_run.py                 # CLI entry point (koza command)
├── core.py                     # Agent loop (tool-calling orchestration)
├── config.py                   # Config load/save + ENV overrides
├── prompt.py                   # System prompt (unrestricted, cross-platform)
├── tg_bot.py                   # Telegram bot (auto-start on koza launch)
├── pyproject.toml              # Package config (installs `koza` command)
├── requirements.txt
│
├── providers/                  # LLM backends
│   ├── factory.py
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   ├── deepseek_provider.py
│   ├── gemini_provider.py
│   ├── ollama_provider.py
│   └── github_provider.py     # GitHub Models (OpenAI-compatible)
│
├── skills/                     # Tool skill modules (99+ tools)
│   ├── config_manager.py       # get_config / set_config / delete_config
│   ├── filesystem.py
│   ├── shell.py
│   ├── web.py
│   ├── code_runner.py
│   ├── system_info.py
│   ├── kanban.py
│   ├── cron.py
│   ├── session_memory.py
│   ├── shared_memory.py
│   ├── working_memory.py
│   ├── agents.py               # Sub-agents
│   ├── messaging.py            # Telegram, Discord, WhatsApp
│   ├── creative.py
│   ├── datascience.py
│   ├── devops.py
│   ├── email_skill.py
│   ├── finance.py
│   ├── gaming.py
│   ├── github_skill.py
│   ├── media.py
│   ├── mlops.py
│   ├── notes.py
│   ├── productivity.py
│   ├── research.py
│   ├── security.py
│   ├── smarthome.py
│   └── social.py
│
├── tools/
│   └── registry.py             # ALL_TOOLS + ALL_HANDLERS assembly
│
└── tui/
    ├── setup_wizard.py
    ├── chat_app.py
    └── kanban_app.py
```

---

## Prompt Externalization

All system prompts are separated from Python source code and stored as `.md` files in the `prompts/` directory. This allows you to edit, version, and test prompts independently without touching any code.

### Directory Structure

```
prompts/
├── core/
│   └── system.md           # Main system prompt (CORE_PROMPT)
├── sections/
│   ├── workspace.md        # Dynamically injected sections
│   ├── code.md
│   ├── web.md
│   ├── shell.md
│   ├── memory.md
│   ├── agent.md
│   ├── security.md
│   ├── devops.md
│   └── background.md
├── personas/
│   ├── team_lead.md        # Coding Mode persona prompts
│   ├── backend_dev.md
│   ├── frontend_dev.md
│   └── test_engineer.md
├── channels/
│   ├── telegram.md         # Channel-specific prompt additions
│   ├── discord.md
│   ├── whatsapp.md
│   └── cli.md
└── routing/
    └── classifier.md       # Intent Router system prompt
```

### Editing Prompts

Edit prompt files directly — changes are picked up automatically. The `PromptLoader` module uses mtime-based cache invalidation; the next access after a file change will load the updated content. No restart required.

### Adding a New Section

Create a new `.md` file in `prompts/sections/`. The filename becomes the section name and is auto-detected by the system.

### Adding a New Channel

Create a `.md` file in `prompts/channels/` named after the channel (e.g. `slack.md`). When `build_system_prompt(channel="slack")` is called, the file is loaded automatically. Missing files are silently ignored — no error is thrown.

### Technical Details

- **Cache**: `PromptLoader` uses a singleton pattern with a thread-safe in-memory cache
- **Validation**: UTF-8 encoding required; empty files raise `ValueError`
- **Backwards compatibility**: `from prompt import SYSTEM_PROMPT, build_system_prompt` continues to work

---

## Documentation

| Guide | Description |
|---|---|
| [Installation](docs/installation.md) | Full install, venv setup, optional deps |
| [Configuration](docs/configuration.md) | All config keys, ENV vars, provider setup |
| [Skills & Tools](docs/skills.md) | All tools listed by category |
| [Memory System](docs/memory.md) | Working memory + permanent memory architecture |
| [Sub-agents](docs/subagents.md) | How to spawn and use sub-agents |
| [Messaging](docs/messaging.md) | Telegram, Discord, WhatsApp setup |
| [Kanban & Cron](docs/kanban-cron.md) | Task management and scheduling |

---

## License

MIT

