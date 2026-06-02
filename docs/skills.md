# Skills & Tools Reference

Koza exposes **96 tools** across 25+ skill categories. The agent selects and calls tools automatically based on your request.

---

## Core Skills

### 📁 Filesystem (`skills/filesystem.py`)
| Tool | Description |
|---|---|
| `read_file` | Read a file's contents |
| `write_file` | Write or overwrite a file |
| `list_dir` | List directory contents |
| `create_dir` | Create a directory |
| `delete_file` | Delete a file or directory |

### 🖥️ Shell (`skills/shell.py`)
| Tool | Description |
|---|---|
| `run_command` | Execute a shell command (pwsh on Windows, bash on Linux) |

### 🌐 Web (`skills/web.py`)
| Tool | Description |
|---|---|
| `web_search` | Search the web via DuckDuckGo |
| `fetch_url` | Fetch the content of a URL |
| `browser_task` | Open a visible browser and perform an interactive website task |

### 🐍 Code Runner (`skills/code_runner.py`)
| Tool | Description |
|---|---|
| `run_python` | Execute Python code in a subprocess |
| `run_node` | Execute Node.js code |
| `run_script` | Run any script file |

### ℹ️ System Info (`skills/system_info.py`)
| Tool | Description |
|---|---|
| `get_os_info` | OS, CPU, RAM, disk info |
| `get_env_var` | Read an environment variable |
| `list_processes` | List running processes |

---

## Task Management

### 📋 Kanban (`skills/kanban.py`)
| Tool | Description |
|---|---|
| `create_task` | Create a Kanban task (todo/doing/done) |
| `list_tasks` | List all tasks with status |
| `move_task` | Move task to a different column |
| `update_task` | Update task title or notes |
| `delete_task` | Delete a task |

### ⏰ Cron (`skills/cron.py`)
| Tool | Description |
|---|---|
| `create_cron` | Schedule a recurring job (cron expression) |
| `list_crons` | List all scheduled jobs |
| `delete_cron` | Delete a scheduled job |

---

## Memory

### 🧠 Working Memory (`skills/working_memory.py`)
Short-term ring buffer — last 20 events always injected into the system prompt.

| Tool | Description |
|---|---|
| `wm_add` | Add an event to working memory |
| `wm_get` | Retrieve working memory entries |
| `wm_list` | Retrieve working memory entries (legacy alias) |
| `wm_clear` | Clear working memory |

### 💾 Shared Memory (`skills/shared_memory.py`)
Permanent cross-session SQLite memory — retrieved on demand.

| Tool | Description |
|---|---|
| `memory_store` | Store a fact permanently |
| `memory_recall` | Recall memories by keyword |
| `memory_search` | Semantic search across memories |
| `memory_list` | List all stored memories |
| `memory_delete` | Delete a memory entry |

### 📚 Session Memory (`skills/session_memory.py`)
Save and recall full conversation sessions.

| Tool | Description |
|---|---|
| `save_session` | Save current conversation |
| `recall_sessions` | Search past sessions |
| `list_sessions` | List all saved sessions |
| `delete_session` | Delete a saved session |

---

## Communications

### 💬 Messaging (`skills/messaging/`)
| Tool | Description |
|---|---|
| `send_message` | Send via telegram/discord/whatsapp |
| `get_messages` | Fetch recent messages |
| `telegram_send` | Send Telegram message directly |
| `telegram_get_updates` | Fetch Telegram updates |
| `telegram_set_webhook` | Set Telegram webhook URL |
| `discord_send` | Send to Discord channel/webhook |
| `discord_get_messages` | Fetch Discord messages |
| `whatsapp_send` | Send WhatsApp message via Twilio |

### 📧 Email (`skills/email_skill.py`)
| Tool | Description |
|---|---|
| `send_email` | Send email via SMTP |
| `read_emails` | Read emails via IMAP |

---

## Developer Tools

### 🤖 Sub-agents (`skills/agents/`)
| Tool | Description |
|---|---|
| `spawn_subagent` | Spawn an autonomous sub-agent in a background thread |
| `get_subagent_status` | Check status/result of a sub-agent |
| `list_subagents` | List all sub-agents this session |

### 🐙 GitHub (`skills/github_skill.py`)
| Tool | Description |
|---|---|
| `github_search_code` | Search code across GitHub |
| `github_create_issue` | Create a GitHub issue |
| `github_list_prs` | List pull requests |
| `github_repo_info` | Get repository metadata |
| `github_clone_repo` | Clone a repository locally |
| `github_prepare_repo` | Clone or update a repository in Koza's stable workspace and set the working directory |

### 🔧 DevOps (`skills/devops.py`)
| Tool | Description |
|---|---|
| `git_operation` | Run git commands |
| `docker_run` | Run a Docker container |
| `webhook_listen` | Listen for incoming webhooks |

### 🔌 MCP (`skills/mcp_skill.py`)
| Tool | Description |
|---|---|
| `mcp_list_tools` | List tools from an MCP server |
| `mcp_call_tool` | Call a tool on an MCP server |

---

## Data & Science

### 📊 Data Science (`skills/datascience.py`)
| Tool | Description |
|---|---|
| `run_jupyter_cell` | Execute a Jupyter notebook cell |
| `pandas_query` | Run a pandas query on a CSV/DataFrame |
| `matplotlib_plot` | Generate a matplotlib chart |

### 🤖 MLOps (`skills/mlops.py`)
| Tool | Description |
|---|---|
| `run_eval` | Run an LLM evaluation |
| `model_benchmark` | Benchmark model performance |
| `huggingface_model_info` | Get HuggingFace model info |

---

## Research & Information

### 🔬 Research (`skills/research.py`)
| Tool | Description |
|---|---|
| `arxiv_search` | Search arXiv papers |
| `wikipedia_search` | Search Wikipedia |
| `polymarket_search` | Search Polymarket prediction markets |

### 💰 Finance (`skills/finance.py`)
| Tool | Description |
|---|---|
| `crypto_price` | Get cryptocurrency price |
| `stock_price` | Get stock price |
| `crypto_top` | List top cryptocurrencies |

---

## Media & Creative

### 🎨 Creative (`skills/creative.py`)
| Tool | Description |
|---|---|
| `ascii_art` | Generate ASCII art from text |
| `architecture_diagram` | Generate architecture diagrams |
| `generate_image` | Generate images via API |

### 🎵 Media (`skills/media.py`)
| Tool | Description |
|---|---|
| `spotify_search` | Search Spotify tracks |
| `youtube_search` | Search YouTube videos |
| `gif_search` | Search for GIFs |
| `youtube_download` | Download YouTube video/audio |

---

## Productivity

### 📅 Productivity (`skills/productivity.py`)
| Tool | Description |
|---|---|
| `google_calendar_list` | List Google Calendar events |
| `google_calendar_create` | Create a calendar event |
| `google_sheets_read` | Read a Google Sheet |
| `airtable_query` | Query an Airtable base |

### 📓 Notes (`skills/notes.py`)
| Tool | Description |
|---|---|
| `note_create` | Create a markdown note |
| `note_search` | Search notes by keyword |
| `note_read` | Read a note's content |
| `note_list` | List all notes |

---

## Security

### 🔒 Security (`skills/security.py`)
| Tool | Description |
|---|---|
| `port_scan` | Scan open ports on a host |
| `http_headers_check` | Inspect HTTP response headers |
| `ssl_check` | Check SSL certificate details |
| `whois_lookup` | WHOIS domain lookup |
| `kali_tool_status` | Check installed Kali-style recon tools and show safe examples |
| `kali_run_recon` | Run allowlisted recon tools against an authorized target |

---

## Smart Home & Social

### 🏠 Smart Home (`skills/smarthome.py`)
| Tool | Description |
|---|---|
| `hue_list_lights` | List Philips Hue lights |
| `hue_set_light` | Control a Hue light |
| `mqtt_publish` | Publish an MQTT message |
| `home_assistant_call` | Call a Home Assistant service |

### 📱 Social (`skills/social.py`)
| Tool | Description |
|---|---|
| `twitter_search` | Search Twitter/X |
| `reddit_search` | Search Reddit |
| `mastodon_post` | Post to Mastodon |

### 🎮 Gaming (`skills/gaming.py`)
| Tool | Description |
|---|---|
| `minecraft_command` | Send a command to a Minecraft server |
| `pokemon_lookup` | Look up Pokémon data |
