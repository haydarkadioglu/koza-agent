# Messaging

Koza supports sending and receiving messages on **Telegram**, **Discord**, and **WhatsApp** (via Twilio).

---

## Quick Setup

The easiest way to configure messaging is via environment variables in your `.env` file:

```env
# Telegram
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# WhatsApp (Twilio)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_WA=whatsapp:+14155238886
TWILIO_TO_WA=whatsapp:+1234567890
```

Or set them in `~/.koza/config.yaml` under the `messaging:` key.

---

## Telegram

### Setup
1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts — you'll get a **bot token**
3. Start a chat with your bot or add it to a group
4. Get your **chat ID**: send a message to your bot, then open  
   `https://api.telegram.org/bot<TOKEN>/getUpdates`  
   Look for `"chat": {"id": ...}`

### Tools
| Tool | Description |
|---|---|
| `telegram_send` | Send a message to the configured chat |
| `telegram_get_updates` | Fetch recent messages sent to the bot |
| `telegram_set_webhook` | Set a webhook URL for receiving updates |
| `send_message(platform="telegram", ...)` | Unified router |
| `get_messages(platform="telegram", ...)` | Unified fetch |

### Example
```
You: Send a Telegram message saying "Build finished successfully"
Koza: [calls telegram_send] ✅ Telegram sent to 123456789
```

---

## Discord

### Option A — Webhook (Simplest, send-only)
1. Open your Discord server settings → **Integrations** → **Webhooks**
2. Click **New Webhook**, copy the URL
3. Set `DISCORD_WEBHOOK_URL`

### Option B — Bot Token (Send + Read)
1. Go to https://discord.com/developers/applications → New Application
2. Add a **Bot** → copy the token
3. Invite the bot to your server with `Send Messages` permission
4. Set `DISCORD_TOKEN` + `DISCORD_CHANNEL_ID`

### Tools
| Tool | Description |
|---|---|
| `discord_send` | Send a message (uses webhook if available, falls back to bot) |
| `discord_get_messages` | Fetch recent messages (requires bot token) |
| `send_message(platform="discord", ...)` | Unified router |
| `get_messages(platform="discord", ...)` | Unified fetch |

### Example
```
You: Post "Deployment complete 🚀" to Discord
Koza: [calls discord_send] ✅ Discord sent via webhook
```

---

## WhatsApp (Twilio)

### Setup
1. Create a Twilio account at https://www.twilio.com
2. Activate the **WhatsApp Sandbox** (for testing) or purchase a Twilio number
3. Copy **Account SID** and **Auth Token** from your Twilio dashboard
4. Set all `TWILIO_*` environment variables

> **Note:** requires `pip install twilio`

### Tools
| Tool | Description |
|---|---|
| `whatsapp_send` | Send a WhatsApp message via Twilio |
| `send_message(platform="whatsapp", ...)` | Unified router |

### Example
```
You: Send a WhatsApp message to +905551234567 saying "Meeting in 10 minutes"
Koza: [calls whatsapp_send] ✅ WhatsApp sent (SID: SM...)
```

---

## Unified Router

All three platforms share a common interface:

```
send_message(platform, text, recipient="")
  platform  → "telegram" | "discord" | "whatsapp"
  text      → message content
  recipient → override chat_id / channel_id / phone (optional)

get_messages(platform, limit=10)
  platform  → "telegram" | "discord"
  limit     → number of messages to return
```
