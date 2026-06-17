"""MCP (Model Context Protocol) skill — dynamic bridge to external MCP servers."""
import json
import logging
import urllib.request
import subprocess
import sys
import os
import shutil
import re
import atexit
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Cache active client connections to reuse them across turns
_ACTIVE_CLIENTS: dict[str, Any] = {}

class StdioMCPClient:
    def __init__(self, name: str, command: str, args: list = None, env: dict = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env
        self.process = None
        self.request_id = 1
        self.stderr_file = None

    def connect(self) -> bool:
        sub_env = dict(os.environ)
        if self.env:
            sub_env.update(self.env)
        
        # Redirect stderr to prevent blocking/hanging the subprocess
        try:
            log_dir = Path.home() / ".Koza" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "mcp-stderr.log"
            self.stderr_file = open(log_file, "a", encoding="utf-8", errors="ignore")
        except Exception:
            self.stderr_file = subprocess.DEVNULL

        try:
            # Resolve executable path to prevent cmd resolution issues
            cmd_path = shutil.which(self.command) or self.command
            self.process = subprocess.Popen(
                [cmd_path] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr_file,
                text=True,
                env=sub_env,
                bufsize=1,
                shell=(sys.platform == "win32")
            )
            return True
        except Exception as e:
            logger.error(f"Failed to start MCP stdio server '{self.name}': {e}")
            return False

    def send_request(self, method: str, params: dict = None) -> dict:
        if not self.process or self.process.poll() is not None:
            if not self.connect():
                return {"error": f"Failed to connect to stdio server {self.name}"}
        
        req_id = self.request_id
        self.request_id += 1
        
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }
        
        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
            
            # Read line-by-line filtering out notifications
            while True:
                line = self.process.stdout.readline()
                if not line:
                    return {"error": "EOF from MCP server stdout"}
                try:
                    resp = json.loads(line)
                    if resp.get("id") == req_id:
                        return resp
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            return {"error": f"Stdio communication error: {e}"}

    def send_notification(self, method: str, params: dict = None):
        if not self.process or self.process.poll() is not None:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
        except Exception:
            pass

    def close(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        if self.stderr_file and self.stderr_file != subprocess.DEVNULL:
            try:
                self.stderr_file.close()
            except Exception:
                pass


class HttpMCPClient:
    def __init__(self, name: str, url: str, headers: dict = None):
        self.name = name
        self.url = url
        self.headers = headers or {}
        self.request_id = 1

    def send_request(self, method: str, params: dict = None) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {}
        }
        self.request_id += 1
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "KozaAgent/1.0",
            **self.headers
        }
        
        try:
            req = urllib.request.Request(
                self.url.rstrip("/") + "/",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": f"HTTP request failed: {e}"}

    def send_notification(self, method: str, params: dict = None):
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "KozaAgent/1.0",
            **self.headers
        }
        try:
            req = urllib.request.Request(
                self.url.rstrip("/") + "/",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception:
            pass

    def close(self):
        pass

def _mcp_initialize_handshake(client: Any) -> bool:
    """Perform the mandatory MCP protocol initialize handshake."""
    resp = client.send_request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
            "name": "KozaAgent",
            "version": "1.0"
        }
    })
    if "error" in resp:
        return False
    # Send initialized notification
    client.send_notification("notifications/initialized")
    return True

def mcp_to_openai_tool(server_name: str, mcp_tool: dict) -> dict:
    # Namespace tool name to prevent collision
    raw_name = f"mcp_{server_name}_{mcp_tool['name']}"
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name)
    return {
        "type": "function",
        "function": {
            "name": safe_name,
            "description": f"[{server_name}] {mcp_tool.get('description', '')}",
            "parameters": mcp_tool.get("inputSchema", {
                "type": "object",
                "properties": {}
            })
        }
    }


def make_mcp_handler(client: Any, original_tool_name: str) -> Callable:
    def handler(**kwargs) -> str:
        resp = client.send_request("tools/call", {
            "name": original_tool_name,
            "arguments": kwargs
        })
        if "error" in resp:
            return f"Error: {resp['error']}"
        result = resp.get("result", {})
        content = result.get("content", [])
        if isinstance(content, list):
            parts = []
            for item in content:
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(result)
    return handler


def load_dynamic_mcp_tools() -> tuple[list[dict], dict[str, Callable]]:
    """Load and register configured MCP servers from config."""
    from config import load_config
    try:
        cfg = load_config()
    except Exception:
        return [], {}
        
    mcp_servers = cfg.get("mcp_servers", {})
    if not mcp_servers:
        return [], {}

    tools = []
    handlers = {}

    for name, server_cfg in mcp_servers.items():
        client = None
        if "url" in server_cfg:
            client = HttpMCPClient(name, server_cfg["url"], server_cfg.get("headers"))
        elif "command" in server_cfg:
            client = StdioMCPClient(
                name, 
                server_cfg["command"], 
                server_cfg.get("args"), 
                server_cfg.get("env")
            )

        if not client:
            continue

        # Close existing cached connection if we are reloading
        if name in _ACTIVE_CLIENTS:
            try:
                _ACTIVE_CLIENTS[name].close()
            except Exception:
                pass

        # Cache connection
        _ACTIVE_CLIENTS[name] = client

        # Pre-connect checks for stdio
        if isinstance(client, StdioMCPClient):
            if not client.connect():
                continue

        # Perform the mandatory MCP handshake
        if not _mcp_initialize_handshake(client):
            logger.warning(f"MCP server '{name}' failed initialization handshake.")
            continue

        # Discover tools
        resp = client.send_request("tools/list")
        if "error" in resp:
            logger.warning(f"Could not discover tools from MCP server '{name}': {resp['error']}")
            continue

        result = resp.get("result", {})
        mcp_tools = result.get("tools", [])

        for t in mcp_tools:
            openai_tool = mcp_to_openai_tool(name, t)
            tools.append(openai_tool)
            tool_name = openai_tool["function"]["name"]
            handlers[tool_name] = make_mcp_handler(client, t["name"])

    return tools, handlers


# ─── Backward compatibility wrappers ─────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "mcp_list_tools",
            "description": "List available tools from an MCP server URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_url": {"type": "string", "description": "MCP server URL, e.g. http://localhost:3000"},
                },
                "required": ["server_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_call_tool",
            "description": "Call a tool on an MCP server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_url": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "arguments": {"type": "object", "default": {}},
                },
                "required": ["server_url", "tool_name"],
            },
        },
    },
]


def _mcp_post(server_url: str, method: str, params: dict = None) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        server_url.rstrip("/") + "/",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "KozaAgent/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def mcp_list_tools(server_url: str) -> str:
    try:
        resp = _mcp_post(server_url, "tools/list")
        tools = resp.get("result", {}).get("tools", [])
        if not tools:
            return "No tools found on MCP server."
        lines = [f"MCP Server: {server_url}\nAvailable tools ({len(tools)}):"]
        for t in tools:
            lines.append(f"  • {t['name']}: {t.get('description','')[:80]}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR connecting to MCP server: {e}"


def mcp_call_tool(server_url: str, tool_name: str, arguments: dict = None) -> str:
    try:
        resp = _mcp_post(server_url, "tools/call", {"name": tool_name, "arguments": arguments or {}})
        result = resp.get("result", {})
        content = result.get("content", [])
        if isinstance(content, list):
            return "\n".join(c.get("text", str(c)) for c in content)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR calling MCP tool: {e}"


HANDLERS = {"mcp_list_tools": mcp_list_tools, "mcp_call_tool": mcp_call_tool}


# ─── Cleanup on exit ─────────────────────────────────────────────────────────

def cleanup_clients():
    for name, client in list(_ACTIVE_CLIENTS.items()):
        try:
            client.close()
        except Exception:
            pass
    _ACTIVE_CLIENTS.clear()

atexit.register(cleanup_clients)
