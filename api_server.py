from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json
import uuid
import os

from core import Agent
from providers.anthropic_provider import AnthropicProvider

app = FastAPI(title="Koza API Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import sqlite3
from providers.factory import get_provider

def load_keys_from_koza_db():
    db_path = os.path.join(os.path.expanduser("~"), ".local", "share", "koza", "koza.db")
    if not os.path.exists(db_path):
        return {}
    
    keys = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute("SELECT integration_id, value FROM credential WHERE active = 1")
        for integration_id, val_str in cursor.fetchall():
            try:
                val = json.loads(val_str)
                if val.get("type") == "key" and "key" in val:
                    keys[integration_id] = val["key"]
            except Exception:
                pass
        conn.close()
    except Exception as e:
        print("Error reading keys from koza.db:", e)
    return keys

from config import load_config

def get_agent():
    try:
        local_cfg = load_config()
    except Exception:
        local_cfg = {"db_path": os.path.join(os.path.expanduser("~"), ".Koza", "koza.db")}
        
    db_keys = load_keys_from_koza_db()
    
    if "providers" not in local_cfg:
        local_cfg["providers"] = {}
        
    mappings = {
        "anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
        "openai": ("openai", "OPENAI_API_KEY"),
        "google": ("gemini", "GEMINI_API_KEY"),
        "deepseek": ("deepseek", "DEEPSEEK_API_KEY")
    }
    
    for koza_id, (koza_id, env_var) in mappings.items():
        if koza_id in db_keys:
            key = db_keys[koza_id]
            os.environ[env_var] = key
            if koza_id not in local_cfg["providers"]:
                local_cfg["providers"][koza_id] = {}
            local_cfg["providers"][koza_id]["api_key"] = key
            
    # Auto-detect best provider from UI settings
    if db_keys.get("anthropic"):
        local_cfg["provider"] = "anthropic"
        local_cfg["model"] = "claude-3-5-sonnet-20241022"
    elif db_keys.get("openai"):
        local_cfg["provider"] = "openai"
        local_cfg["model"] = "gpt-4o"
    elif db_keys.get("google"):
        local_cfg["provider"] = "gemini"
        local_cfg["model"] = "gemini-1.5-pro"
        
    prov = get_provider(local_cfg)
    agent = Agent(provider=prov, db_path=local_cfg.get("db_path", os.path.join(os.path.expanduser("~"), ".Koza", "koza.db")), cfg=local_cfg)

    # Sync workspace path / cwd with active directory or home directory
    active_dir = get_active_session_directory()
    if active_dir and active_dir != "/":
        from skills import shell as _shell
        _shell.set_cwd(active_dir)
        print("Synced shell CWD with active session workspace:", active_dir)
    else:
        from skills import shell as _shell
        import pathlib
        home_dir = str(pathlib.Path.home())
        _shell.set_cwd(home_dir)
        print("No specific workspace active. Synced shell CWD with home:", home_dir)

    return agent

def get_active_session_directory():
    db_path = os.path.join(os.path.expanduser("~"), ".local", "share", "koza", "koza.db")
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute("SELECT directory FROM session ORDER BY time_updated DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception as e:
        print("Error reading active session directory:", e)
    return None

@app.get("/")
async def root():
    return {"status": "ok", "message": "Koza API Server is running. Use /v1/chat/completions for API access."}

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{
            "id": "koza-engine",
            "object": "model",
            "created": 1686935002,
            "owned_by": "koza"
        }]
    }

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    
    user_input = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_input = msg.get("content", "")
            break
            
    agent = get_agent()
    agent.messages = [m for m in messages if m.get("role") != "user" or m != messages[-1]]

    async def event_generator():
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        
        for event in agent.stream_chat(user_input):
            if event["type"] == "text":
                chunk = {
                    "id": f"chatcmpl-{uuid.uuid4()}",
                    "object": "chat.completion.chunk",
                    "model": "koza-engine",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": event["token"]},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                
            elif event["type"] == "tool_start":
                # Convert tool start into a UI-friendly markdown message instead of a native tool call, 
                # so Koza UI just displays it rather than trying to execute it (Koza executes it).
                msg = f"\n\n> 🛠️ **Koza Tool:** `{event['name']}`\n> ```json\n> {json.dumps(event['args'], indent=2)}\n> ```\n\n"
                chunk = {
                    "id": f"chatcmpl-{uuid.uuid4()}",
                    "object": "chat.completion.chunk",
                    "model": "koza-engine",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": msg},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                
            elif event["type"] == "tool_done":
                # Show completion in UI
                msg = f"\n> ✅ *Finished in {event.get('elapsed', 0):.2f}s*\n\n"
                chunk = {
                    "id": f"chatcmpl-{uuid.uuid4()}",
                    "object": "chat.completion.chunk",
                    "model": "koza-engine",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": msg},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                
            elif event["type"] == "tool_denied":
                msg = f"\n> 🚫 **Tool Denied:** `{event.get('name')}`\n\n"
                chunk = {
                    "id": f"chatcmpl-{uuid.uuid4()}",
                    "object": "chat.completion.chunk",
                    "model": "koza-engine",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": msg},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"

            elif event["type"] == "error":
                msg = f"\n> ❌ **Error:** {event.get('message')}\n\n"
                chunk = {
                    "id": f"chatcmpl-{uuid.uuid4()}",
                    "object": "chat.completion.chunk",
                    "model": "koza-engine",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": msg},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                
        final_chunk = {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion.chunk",
            "model": "koza-engine",
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


from pydantic import BaseModel
from config import load_config, save_config

class ConfigUpdateRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    fallback_provider: str | None = None
    fallback_model: str | None = None
    media_provider: str | None = None
    providers: dict | None = None
    messaging: dict | None = None
    email: dict | None = None
    voice: dict | None = None
    multi_host: dict | None = None
    tool_approval: bool | None = None
    allowed_tools: list[str] | None = None

class CronCreateRequest(BaseModel):
    name: str
    command: str
    cron_expr: str

class MCPCreateRequest(BaseModel):
    name: str
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict | None = None
    env: dict | None = None

@app.get("/api/config")
async def get_config_endpoint():
    cfg = load_config()
    return cfg

@app.post("/api/config")
async def update_config_endpoint(req: ConfigUpdateRequest):
    cfg = load_config()
    if req.provider is not None:
        cfg["provider"] = req.provider
    if req.model is not None:
        cfg["model"] = req.model
    if req.fallback_provider is not None:
        cfg["fallback_provider"] = req.fallback_provider
    if req.fallback_model is not None:
        cfg["fallback_model"] = req.fallback_model
    if req.media_provider is not None:
        cfg["media_provider"] = req.media_provider
    if req.providers is not None:
        provs = cfg.setdefault("providers", {})
        for k, v in req.providers.items():
            if isinstance(v, dict):
                provs.setdefault(k, {}).update(v)
            else:
                provs[k] = v
    if req.messaging is not None:
        msg_cfg = cfg.setdefault("messaging", {})
        for k, v in req.messaging.items():
            if isinstance(v, dict):
                msg_cfg.setdefault(k, {}).update(v)
            else:
                msg_cfg[k] = v
    if req.email is not None:
        cfg.setdefault("email", {}).update(req.email)
    if req.voice is not None:
        cfg.setdefault("voice", {}).update(req.voice)
    if req.multi_host is not None:
        cfg.setdefault("multi_host", {}).update(req.multi_host)
    if req.tool_approval is not None:
        cfg["tool_approval"] = req.tool_approval
    if req.allowed_tools is not None:
        cfg["allowed_tools"] = req.allowed_tools
    save_config(cfg)
    return {"status": "ok"}


import urllib.request
import zipfile
from pathlib import Path
import threading

git_install_progress = {"status": "idle", "percent": 0, "error": None}

def run_git_installer():
    global git_install_progress
    git_install_progress = {"status": "downloading", "percent": 0, "error": None}
    try:
        target_dir = Path.home() / ".Koza" / "git"
        zip_path = Path.home() / ".Koza" / "mingit.zip"
        url = "https://github.com/git-for-windows/git/releases/download/v2.44.0.windows.1/MinGit-2.44.0-64-bit.zip"
        
        def progress_hook(count, block_size, total_size):
            if total_size > 0:
                percent = int(count * block_size * 100 / total_size)
                git_install_progress["percent"] = min(100, percent)
                
        urllib.request.urlretrieve(url, str(zip_path), reporthook=progress_hook)
        git_install_progress["status"] = "extracting"
        
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(target_dir)
            
        if zip_path.exists():
            zip_path.unlink()
            
        git_install_progress["status"] = "completed"
    except Exception as e:
        git_install_progress["status"] = "failed"
        git_install_progress["error"] = str(e)

@app.get("/api/git/status")
async def get_git_status():
    bash_exe = Path.home() / ".Koza" / "git" / "bin" / "bash.exe"
    return {
        "installed": bash_exe.exists(),
        "path": str(bash_exe) if bash_exe.exists() else None,
        "progress": git_install_progress
    }

@app.post("/api/git/install")
async def install_git_endpoint():
    global git_install_progress
    if git_install_progress["status"] in ["downloading", "extracting"]:
        return {"status": "already_running"}
    t = threading.Thread(target=run_git_installer)
    t.start()
    return {"status": "started"}

@app.get("/api/cron")
async def get_cron_endpoint():
    from skills.cron_db import get_conn
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT id, name, command, cron_expr FROM cron_jobs").fetchall()
        jobs = []
        for r in rows:
            jobs.append({
                "id": r[0],
                "name": r[1],
                "command": r[2],
                "cron_expr": r[3]
            })
        return jobs
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/cron")
async def create_cron_endpoint(req: CronCreateRequest):
    from skills.cron_db import get_conn
    from skills.cron_scheduler import schedule_job
    try:
        import datetime
        created_at = datetime.datetime.now().isoformat()
        with get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO cron_jobs (name, command, cron_expr, sync_system, created_at) VALUES (?, ?, ?, 1, ?)",
                (req.name, req.command, req.cron_expr, created_at)
            )
            job_id = cursor.lastrowid
        schedule_job(req.command, req.name, req.cron_expr, job_id)
        return {"status": "ok", "id": job_id}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/api/cron/{job_id}")
async def delete_cron_endpoint(job_id: int):
    from skills.cron_db import get_conn
    from skills.cron_scheduler import get_scheduler
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        try:
            scheduler = get_scheduler()
            scheduler.remove_job(str(job_id))
        except Exception:
            pass
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/cron/trigger/{job_id}")
async def trigger_cron_endpoint(job_id: int):
    from skills.cron_db import get_conn
    from skills.cron_scheduler import run_job
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT name, command FROM cron_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return {"error": "Job not found"}
        name, command = row
        import threading
        t = threading.Thread(target=run_job, args=(command, name, job_id))
        t.start()
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/mcp")
async def get_mcp_endpoint():
    cfg = load_config()
    return cfg.get("mcp_servers", {})

@app.post("/api/mcp")
async def create_mcp_endpoint(req: MCPCreateRequest):
    cfg = load_config()
    mcp_servers = cfg.setdefault("mcp_servers", {})
    server_cfg = {}
    if req.url:
        server_cfg["url"] = req.url
        if req.headers:
            server_cfg["headers"] = req.headers
    elif req.command:
        server_cfg["command"] = req.command
        if req.args:
            server_cfg["args"] = req.args
        if req.env:
            server_cfg["env"] = req.env
    else:
        return {"error": "Must specify url or command"}
        
    mcp_servers[req.name] = server_cfg
    save_config(cfg)
    
    try:
        from skills.mcp_skill import load_dynamic_mcp_tools
        load_dynamic_mcp_tools()
    except Exception:
        pass
        
    return {"status": "ok"}

@app.delete("/api/mcp/{name}")
async def delete_mcp_endpoint(name: str):
    cfg = load_config()
    mcp_servers = cfg.setdefault("mcp_servers", {})
    if name in mcp_servers:
        del mcp_servers[name]
        save_config(cfg)
        
        try:
            from skills.mcp_skill import _ACTIVE_CLIENTS
            if name in _ACTIVE_CLIENTS:
                _ACTIVE_CLIENTS[name].close()
                del _ACTIVE_CLIENTS[name]
        except Exception:
            pass
            
        return {"status": "ok"}
    return {"error": "MCP server not found"}

@app.get("/api/logs")
async def get_logs_endpoint(limit: int = 100):
    from koza_daemon import LOG_FILE
    if not LOG_FILE.exists():
        return {"logs": ["No log file found."]}
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"logs": lines[-limit:]}
    except Exception as e:
        return {"logs": [f"Error reading logs: {e}"]}

@app.post("/api/clean")
async def clean_endpoint():
    from config import save_config, default_config
    save_config(default_config())
    
    from skills.cron_db import get_conn as get_cron_conn
    try:
        with get_cron_conn() as conn:
            conn.execute("DROP TABLE IF EXISTS cron_jobs")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT UNIQUE NOT NULL,
                    command     TEXT NOT NULL,
                    cron_expr   TEXT NOT NULL,
                    sync_system INTEGER NOT NULL DEFAULT 0,
                    created_at  REAL NOT NULL
                )
            """)
    except Exception:
        pass

    from skills.session_memory import _conn as get_session_conn
    try:
        with get_session_conn() as conn:
            conn.execute("DROP TABLE IF EXISTS sessions")
            conn.execute("DROP TABLE IF EXISTS sessions_fts")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    title     TEXT NOT NULL DEFAULT 'Untitled',
                    started   REAL NOT NULL,
                    ended     REAL,
                    messages  TEXT NOT NULL DEFAULT '[]',
                    summary   TEXT NOT NULL DEFAULT '',
                    project   TEXT NOT NULL DEFAULT 'agent'
                )
            """)
    except Exception:
        pass
        
    from koza_daemon import LOG_FILE
    if LOG_FILE.exists():
        try:
            LOG_FILE.write_text("")
        except Exception:
            pass
            
    return {"status": "ok"}

@app.get("/api/version")
async def version_endpoint():
    try:
        from cli.update_cmd import _check_latest_version
        latest, current = _check_latest_version()
        return {
            "current": current,
            "latest": latest,
            "update_available": bool(latest and latest != current)
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/version/update")
async def update_engine_endpoint():
    try:
        from cli.update_cmd import cmd_update
        import threading
        t = threading.Thread(target=cmd_update, args=([],))
        t.start()
        return {"status": "started"}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
