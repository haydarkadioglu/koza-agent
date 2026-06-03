# Installation

## Requirements

- Python **3.11+**
- pip

## Basic Install

```bash
# Clone the repo
git clone https://github.com/yourname/koza-agent.git
cd koza-agent

# (Recommended) Create a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## First Run

```bash
python main.py
```

On first launch, the **setup wizard** opens in the terminal. Use arrow keys to navigate, Enter to confirm. You can configure:

- LLM provider (OpenAI, Anthropic, DeepSeek, Gemini, Ollama)
- API keys
- Default model
- Notes vault path

Config is saved to `~/.koza/config.yaml`.

## Optional Dependencies

These are not in `requirements.txt` because they are only needed for specific skills:

| Package | Skill | Install |
|---|---|---|
| `twilio` | WhatsApp messaging | `pip install twilio` |
| `phue` | Philips Hue smart home | `pip install phue` |
| `paho-mqtt` | MQTT smart home | already included |
| `spotipy` | Spotify | already included |
| `yt-dlp` | YouTube download | `pip install yt-dlp` |

## Windows Notes

- Shell skill automatically uses **PowerShell 7** (`pwsh`) when available, falls back to `cmd`.
- Cron jobs sync to **Windows Task Scheduler** (`schtasks`).
- Install PowerShell 7: `winget install Microsoft.PowerShell`

## Linux / macOS Notes

- Shell skill uses `bash`.
- Cron jobs sync to the user's **crontab**.

## Updating

```bash
git pull
pip install -r requirements.txt --upgrade
```

## Uninstall

```bash
python main.py uninstall   # removes ~/.koza (config + database)
pip uninstall -r requirements.txt -y
```
