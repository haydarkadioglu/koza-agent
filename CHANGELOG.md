# Changelog

All notable changes to Koza Agent are documented here.

---

## [v2.0.0] — 2026-05-21

### 🚀 Major Features

#### Coding Mode — Multi-Persona AI Team
- **`koza coding`** — new command that launches a full AI software team
- **4 AI personas** working together on coding tasks:
  - 🎯 **Team Lead (Koza)** — expands user prompts, creates JSON task plans, summarizes results
  - 🔧 **Backend Developer** — writes modular, file-per-function code; learns from past errors
  - 🎨 **Frontend Developer** — handles UI/UX, CSS, components
  - 🧪 **Test Engineer** — runs tests inline, reports FAIL/PASS, records error patterns
- **Error Memory** — SQLite-backed; failed patterns are stored and injected into retry prompts so the same mistake is never repeated
- **Retry loop** — up to `max_retries` (default 3) attempts per task before escalating
- `koza coding status` — inspect recorded error memory
- `koza coding clear` — clear error memory
- `/mode coding` toggle from within normal chat

#### Sticky-Bottom Prompt (prompt_toolkit)
- Input always stays at the bottom while agent output scrolls above
- Press **Enter** during processing to interrupt the agent
- Prompt text dynamically switches: `● You ›` ↔ `⏎ Enter to interrupt ›`
- Graceful fallback to plain `input()` if `prompt_toolkit` is not installed

#### Voice Mode — Always-On VAD
- No more Enter-to-record; automatic speech detection via energy VAD
- Pre-roll buffer preserves first syllable
- **pyttsx3** as zero-download TTS (primary); **Kokoro** optional
- Dynamic Hugging Face file discovery — no hardcoded model filenames
- Device selection UX: system default + named devices only (no 36-item list)

### ✨ Improvements

- `config.py` — added `coding_mode` section (`max_retries`, `auto_test`)
- `koza_run.py` — `coding` command dispatched
- `cli/chat.py` — `/mode coding` and `/mode off` inline toggles
- `requirements.txt` — `prompt_toolkit>=3.0.0` added

---

## [v1.2.0] — Cross-Platform Uninstall

### Added
- `koza uninstall` works on **Windows**, **Linux**, and **macOS**
- Platform detection: PowerShell on Windows, shell script on Unix
- Removes venv, PATH entries, and leftover config per platform

---

## [v1.1.0] — Self-Update & Version Check

### Added
- `koza update` — pulls latest from GitHub and reinstalls
- `koza version` — shows current version; highlights if a newer release is available on PyPI/GitHub
- README version badge updated automatically on release

---

## [v1.0.0] — Initial Release

### Features
- 99+ tools across 25+ skill categories
- Dual memory (working memory + long-term SQLite)
- Sub-agent spawning with capability groups
- Telegram bot integration
- Cross-platform scheduling (APScheduler)
- Multi-host sync protocol
- Kanban board (TUI)
- Multi-provider support: OpenAI, Anthropic, Gemini, DeepSeek, Ollama, GitHub Models, Kimi, MiniMax, ZAI
