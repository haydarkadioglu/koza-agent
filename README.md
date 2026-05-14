# 🪽 Hermes Agent

Konsolda her şeyi yapabilen, birden fazla LLM destekleyen, Windows/Linux üzerinde çalışan AI agent.

## Özellikler

- **Çoklu LLM Desteği**: OpenAI, Anthropic, DeepSeek, Gemini (API key + OAuth), Ollama (local)
- **Textual TUI**: Ok tuşlarıyla gezilen setup sihirbazı, chat arayüzü ve Kanban tahtası
- **Skills (Yetenekler)**:
  - 📁 Dosya sistemi (okuma/yazma/listeleme/silme)
  - 🖥️ Kabuk komutları (Windows PowerShell + Linux bash)
  - 🌐 Web arama (DuckDuckGo) + URL getirme
  - 🐍 Kod çalıştırma (Python, Node.js, script)
  - ℹ️ Sistem bilgisi (OS, env, process)
  - 📋 Kanban görev yönetimi
  - ⏰ Cron zamanlaması (agent kendi kendine schedule oluşturur, Linux crontab + Windows Task Scheduler senkronizasyonu)

## Kurulum

```bash
pip install -r requirements.txt
```

## Kullanım

```bash
# İlk açılış: setup sihirbazı açılır
python main.py

# Belirli provider ile başlatma
python main.py --provider openai --model gpt-4o

# Setup sihirbazını tekrar çalıştır
python main.py --setup

# Kanban tahtasını aç
python main.py --kanban

# TUI olmadan (düz CLI)
python main.py --no-tui
```

## Konfigürasyon

Config dosyası: `~/.hermes/config.yaml`  
Veritabanı: `~/.hermes/hermes.db` (Kanban + Cron görevleri)

API key'leri `.env` dosyasına da koyabilirsiniz (bkz. `.env.example`).

## Proje Yapısı

```
agent/
├── config.py              # Konfigürasyon yönetimi
├── core.py                # Tool-calling agent döngüsü
├── providers/
│   ├── base.py            # Soyut sağlayıcı arayüzü
│   ├── factory.py         # Provider seçici
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   ├── deepseek_provider.py
│   ├── gemini_provider.py
│   └── ollama_provider.py
├── skills/
│   ├── filesystem.py
│   ├── shell.py
│   ├── web.py
│   ├── code_runner.py
│   ├── system_info.py
│   ├── kanban.py
│   └── cron.py
└── tui/
    ├── setup_wizard.py    # İlk kurulum TUI
    ├── chat_app.py        # Ana chat arayüzü
    └── kanban_app.py      # Kanban tahtası
```

## Cron Örneği

Hermes'e şunu söyleyebilirsiniz:
> "Her gün saat 09:00'da haber ara ve özetle"

Hermes bunu otomatik olarak:
1. `create_cron` aracıyla SQLite'a kaydeder
2. Linux'ta `crontab`'a ekler / Windows'ta `schtasks` ile Task Scheduler'a ekler
3. APScheduler ile aynı process içinde de çalıştırır
