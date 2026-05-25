# Koza Agent &nbsp;[![Version](https://img.shields.io/badge/version-v1.4.4-cyan)](https://github.com/haydarkadioglu/koza-agent/releases)

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
powershell -c "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; irm https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/install.ps1 | iex"
```

### Linux / macOS — one-liner

```bash
curl -fsSL https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/install.sh | bash
```

Her iki script de:
- Repo'yu `~/.koza-agent/` altına indirir (git varsa clone, yoksa ZIP)
- Otomatik virtualenv oluşturur
- Tüm bağımlılıkları kurar
- `koza` komutunu PATH'e ekler
- Tekrar çalıştırılırsa mevcut kurulumu günceller

> **Gereksinimler:** Python 3.11+ (git opsiyonel — yoksa ZIP ile indirir)  
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
"deepseek api keyim sk-abc123"
"openai modelini gpt-4o-mini yap"
"telegram tokenım 1234567:ABC..."
"hangi provider kullanılıyor"
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

Tüm system prompt'lar Python kaynak kodundan ayrılmış olup `prompts/` dizininde `.md` dosyaları olarak tutulur. Bu sayede prompt'ları kod değiştirmeden düzenleyebilir, versiyonlayabilir ve bağımsız olarak test edebilirsiniz.

### Dizin Yapısı

```
prompts/
├── core/
│   └── system.md           # Ana system prompt (CORE_PROMPT)
├── sections/
│   ├── workspace.md        # Dinamik olarak eklenen bölümler
│   ├── code.md
│   ├── web.md
│   ├── shell.md
│   ├── memory.md
│   ├── agent.md
│   ├── security.md
│   ├── devops.md
│   └── background.md
├── personas/
│   ├── team_lead.md        # Coding Mode persona prompt'ları
│   ├── backend_dev.md
│   ├── frontend_dev.md
│   └── test_engineer.md
├── channels/
│   ├── telegram.md         # Kanal-spesifik prompt ekleri
│   ├── discord.md
│   ├── whatsapp.md
│   └── cli.md
└── routing/
    └── classifier.md       # Intent Router system prompt'u
```

### Prompt Düzenleme

Prompt dosyalarını doğrudan düzenleyebilirsiniz — değişiklikler otomatik olarak algılanır. `PromptLoader` modülü mtime-based cache invalidation kullanır; dosya değiştiğinde bir sonraki erişimde güncel içerik yüklenir. Restart gerekmez.

### Yeni Section Ekleme

`prompts/sections/` dizinine yeni bir `.md` dosyası oluşturmanız yeterlidir. Dosya adı section adı olarak kullanılır ve sistem tarafından otomatik algılanır.

### Yeni Channel Ekleme

`prompts/channels/` dizinine kanal adıyla bir `.md` dosyası oluşturun (örn. `slack.md`). `build_system_prompt(channel="slack")` çağrıldığında ilgili dosya otomatik yüklenir. Dosya yoksa hata fırlatılmaz, sadece channel prompt'u eklenmez.

### Teknik Detaylar

- **Cache**: `PromptLoader` singleton pattern ile çalışır, thread-safe in-memory cache kullanır
- **Validation**: UTF-8 encoding zorunlu, boş dosyalar `ValueError` fırlatır
- **Geriye uyumluluk**: `from prompt import SYSTEM_PROMPT, build_system_prompt` çalışmaya devam eder

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

