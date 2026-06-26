"""DevOps skill — webhooks, Docker, Git operations."""
import subprocess
import threading
import platform
from pathlib import Path

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "git_operation",
            "description": "Run a Git operation: clone, pull, commit, push, status, log.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["clone", "pull", "commit", "push", "status", "log", "diff"],
                    },
                    "repo_path": {"type": "string", "default": ".", "description": "Local repo path"},
                    "remote_url": {"type": "string", "default": "", "description": "For clone operation"},
                    "message": {"type": "string", "default": "", "description": "Commit message"},
                    "branch": {"type": "string", "default": "", "description": "Branch name"},
                },
                "required": ["operation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_run",
            "description": "Run a Docker container and return output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image": {"type": "string"},
                    "command": {"type": "string", "default": ""},
                    "detach": {"type": "boolean", "default": False},
                    "remove": {"type": "boolean", "default": True},
                    "ports": {"type": "string", "default": "", "description": "e.g. '8080:80'"},
                },
                "required": ["image"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "webhook_listen",
            "description": "Start a temporary HTTP server to receive a webhook. Waits for one request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "port": {"type": "integer", "default": 9988},
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": [],
            },
        },
    },
]


def git_operation(operation: str, repo_path: str = ".", remote_url: str = "",
                  message: str = "", branch: str = "") -> str:
    if operation == "push":
        return "ERROR: git push is disabled in Koza Agent to prevent accidental remote pushes. Please review and push changes manually."
    try:
        cmds = {
            "clone": ["git", "clone", remote_url],
            "pull": ["git", "-C", repo_path, "pull"] + ([f"origin {branch}"] if branch else []),
            "status": ["git", "-C", repo_path, "status"],
            "log": ["git", "-C", repo_path, "log", "--oneline", "-10"],
            "diff": ["git", "-C", repo_path, "diff"],
            "commit": ["git", "-C", repo_path, "commit", "-am", message or "Auto commit"],
        }
        cmd = cmds.get(operation)
        if not cmd:
            return f"Unknown operation: {operation}"
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (result.stdout + result.stderr).strip() or "Done"
    except Exception as e:
        return f"ERROR: {e}"


def docker_run(image: str, command: str = "", detach: bool = False,
               remove: bool = True, ports: str = "") -> str:
    try:
        cmd = ["docker", "run"]
        if detach:
            cmd.append("-d")
        if remove:
            cmd.append("--rm")
        if ports:
            cmd += ["-p", ports]
        cmd.append(image)
        if command:
            cmd += command.split()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return (result.stdout + result.stderr).strip() or "Container started"
    except FileNotFoundError:
        return "Docker not found. Install Docker first."
    except Exception as e:
        return f"ERROR: {e}"


def webhook_listen(port: int = 9988, timeout: int = 30) -> str:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import json as _json

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            received.append({"method": "POST", "path": self.path, "body": body})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def do_GET(self):
            received.append({"method": "GET", "path": self.path})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            pass

    server = HTTPServer(("", port), Handler)
    server.timeout = timeout
    server.handle_request()
    server.server_close()
    if received:
        return f"Webhook received:\n{_json.dumps(received[0], indent=2)}"
    return "No webhook received within timeout."


HANDLERS = {"git_operation": git_operation, "docker_run": docker_run, "webhook_listen": webhook_listen}
