# Configuration

## Config File

Location: `~/.koza/config.yaml`

All settings can be managed through the setup wizard (`python main.py setup`) or by editing the YAML file directly.

## Full Config Reference

```yaml
# Active LLM provider
provider: ollama          # openai | anthropic | deepseek | gemini | ollama

# Default model (leave empty to use provider default)
model: ""

# Per-provider settings
providers:
  openai:
    api_key: ""
    base_url: "https://api.openai.com/v1"   # override for compatible APIs
  anthropic:
    api_key: ""
  deepseek:
    api_key: ""
    base_url: "https://api.deepseek.com/v1"
  gemini:
    auth: "api_key"                           # api_key | adc | cookie | antigravity
    api_key: ""
    cookie_1psid: ""                          # only for auth: cookie
    cookie_1psidts: ""                        # optional
    antigravity_url: "http://localhost:5188"  # only for auth: antigravity
  ollama:
    base_url: "http://localhost:11434"       # local Ollama server
  github:
    token: ""                               # GitHub PAT for github_skill

# Messaging integrations
messaging:
  telegram:
    token: ""                               # Bot token from @BotFather
    chat_id: ""                             # Default target chat/channel ID
  discord:
    webhook_url: ""                         # Webhook URL (simplest setup)
    token: ""                               # Bot token (for reading messages)
    channel_id: ""
  whatsapp:
    account_sid: ""                         # Twilio Account SID
    auth_token: ""                          # Twilio Auth Token
    from_number: "whatsapp:+14155238886"    # Twilio sandbox or verified number
    to_number: ""                           # Default recipient

# Obsidian / markdown notes vault
vault_path: "~/notes"

# SQLite database path (kanban, cron, memory, sessions)
db_path: "~/.koza/koza.db"
```

## Environment Variables

All sensitive values can be set as environment variables or in a `.env` file in the project root. They take **priority over** the config file.

| Variable | Config path |
|---|---|
| `OPENAI_API_KEY` | `providers.openai.api_key` |
| `ANTHROPIC_API_KEY` | `providers.anthropic.api_key` |
| `DEEPSEEK_API_KEY` | `providers.deepseek.api_key` |
| `GEMINI_API_KEY` | `providers.gemini.api_key` |
| `GITHUB_TOKEN` | `providers.github.token` |
| `TELEGRAM_TOKEN` | `messaging.telegram.token` |
| `TELEGRAM_CHAT_ID` | `messaging.telegram.chat_id` |
| `DISCORD_WEBHOOK_URL` | `messaging.discord.webhook_url` |
| `DISCORD_TOKEN` | `messaging.discord.token` |
| `DISCORD_CHANNEL_ID` | `messaging.discord.channel_id` |
| `TWILIO_ACCOUNT_SID` | `messaging.whatsapp.account_sid` |
| `TWILIO_AUTH_TOKEN` | `messaging.whatsapp.auth_token` |
| `TWILIO_FROM_WA` | `messaging.whatsapp.from_number` |
| `TWILIO_TO_WA` | `messaging.whatsapp.to_number` |

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

## Provider Setup

### OpenAI
1. Get API key at https://platform.openai.com/api-keys
2. Set `OPENAI_API_KEY` or fill in `config.yaml`
3. Recommended models: `gpt-4o`, `gpt-4o-mini`, `o3-mini`

### Anthropic
1. Get API key at https://console.anthropic.com/
2. Recommended models: `claude-opus-4-5`, `claude-sonnet-4-5`

### DeepSeek
1. Get API key at https://platform.deepseek.com/
2. Models: `deepseek-chat`, `deepseek-reasoner`

### Gemini
1. Get API key at https://aistudio.google.com/
2. Models: `gemini-2.0-flash`, `gemini-2.5-pro`
3. Alternative auth modes:
   - `providers.gemini.auth: adc` → use local Google credentials (Gemini CLI / gcloud ADC)
   - `providers.gemini.auth: cookie` → use browser cookie session
   - `providers.gemini.auth: antigravity` → route through Antigravity Manager proxy (localhost:5188)

### Ollama (Local)
1. Install from https://ollama.com
2. Pull a model: `ollama pull llama3.2`
3. Koza auto-connects to `http://localhost:11434`

## View Current Config

```bash
python main.py config
```

This shows all settings with API keys masked (last 4 chars visible).
