"""Code runner skill — execute Python, Node.js, or arbitrary scripts."""
import os
import sys
import subprocess
import tempfile
from pathlib import Path

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Execute Python code and return the output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_node",
            "description": "Execute JavaScript/Node.js code and return the output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_script",
            "description": "Run a script file that already exists on disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the script"},
                    "args": {"type": "string", "description": "Optional arguments", "default": ""},
                    "timeout": {"type": "integer", "default": 60},
                },
                "required": ["path"],
            },
        },
    },
]


def _run_temp(interpreter: list[str], code: str, suffix: str, timeout: int) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp = f.name
    try:
        result = subprocess.run(
            interpreter + [tmp],
            capture_output=True, text=True, timeout=timeout
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"STDERR:\n{err}")
        parts.append(f"Exit code: {result.returncode}")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return "ERROR: Timeout"
    finally:
        os.unlink(tmp)


def run_python(code: str, timeout: int = 30) -> str:
    return _run_temp([sys.executable], code, ".py", timeout)


def run_node(code: str, timeout: int = 30) -> str:
    return _run_temp(["node"], code, ".js", timeout)


def run_script(path: str, args: str = "", timeout: int = 60) -> str:
    try:
        cmd = [path] + (args.split() if args else [])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(f"STDERR:\n{result.stderr.strip()}")
        parts.append(f"Exit code: {result.returncode}")
        return "\n".join(parts)
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {"run_python": run_python, "run_node": run_node, "run_script": run_script}
