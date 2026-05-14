"""Shell skill — run commands on Windows (PowerShell/cmd) and Linux (bash)."""
import os
import platform
import subprocess

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return stdout+stderr. Supports Windows (PowerShell/cmd) and Linux/macOS (bash).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run"},
                    "cwd": {"type": "string", "description": "Working directory", "default": "."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
                },
                "required": ["command"],
            },
        },
    },
]


def run_command(command: str, cwd: str = ".", timeout: int = 30) -> str:
    system = platform.system()
    if system == "Windows":
        # Try pwsh first, fall back to cmd
        try:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
        except FileNotFoundError:
            result = subprocess.run(
                ["cmd", "/c", command],
                capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
    else:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True, text=True, timeout=timeout, cwd=cwd
        )

    output = []
    if result.stdout.strip():
        output.append(result.stdout.strip())
    if result.stderr.strip():
        output.append(f"STDERR:\n{result.stderr.strip()}")
    output.append(f"Exit code: {result.returncode}")
    return "\n".join(output)


HANDLERS = {"run_command": run_command}
