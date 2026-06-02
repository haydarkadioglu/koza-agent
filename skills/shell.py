"""Shell skill — run commands on Windows (PowerShell/cmd) and Linux (bash)."""
import os
import platform
import subprocess
import threading
from pathlib import Path

# Tracks the current working directory across tool calls.
# Lock protects against concurrent sub-agent CWD changes.
_CWD = os.getcwd()
_cwd_lock = threading.Lock()


def get_cwd() -> str:
    with _cwd_lock:
        return _CWD


def set_cwd(path: str) -> None:
    global _CWD
    with _cwd_lock:
        _CWD = os.path.abspath(path)


def resolve_path(path: str = ".") -> str:
    """Resolve absolute and relative paths against Koza's tracked CWD."""
    expanded = Path(os.path.expanduser(path or "."))
    with _cwd_lock:
        current_cwd = _CWD
    if not expanded.is_absolute():
        expanded = Path(current_cwd) / expanded
    return str(expanded.resolve())


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command and return stdout+stderr. "
                "Supports Windows (PowerShell/cmd) and Linux/macOS (bash). "
                "Use 'cwd' to run in a specific directory, or omit to use the current working directory. "
                "Use 'cd <path>' as the command to change the working directory for future commands."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run"},
                    "cwd": {"type": "string", "description": "Working directory (absolute or relative). Defaults to current directory."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
                },
                "required": ["command"],
            },
        },
    },
]


def run_command(command: str, cwd: str = None, timeout: int = 30) -> str:
    global _CWD

    # Handle bare 'cd' commands — update our tracked CWD
    stripped = command.strip()
    if stripped.lower().startswith("cd ") or stripped.lower() == "cd":
        parts = stripped.split(None, 1)
        target = parts[1] if len(parts) > 1 else os.path.expanduser("~")
        new_dir = resolve_path(target)
        with _cwd_lock:
            if os.path.isdir(new_dir):
                _CWD = new_dir
                return f"Changed directory to: {_CWD}"
        return f"ERROR: Directory not found: {new_dir}"

    with _cwd_lock:
        current_cwd = _CWD
    effective_cwd = resolve_path(cwd) if cwd else current_cwd

    system = platform.system()
    try:
        if system == "Windows":
            try:
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-Command", command],
                    capture_output=True, text=True, timeout=timeout, cwd=effective_cwd
                )
            except FileNotFoundError:
                result = subprocess.run(
                    ["cmd", "/c", command],
                    capture_output=True, text=True, timeout=timeout, cwd=effective_cwd
                )
        else:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True, text=True, timeout=timeout, cwd=effective_cwd
            )
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"

    output = []
    if result.stdout.strip():
        output.append(result.stdout.strip())
    if result.stderr.strip():
        output.append(f"STDERR:\n{result.stderr.strip()}")
    output.append(f"Exit code: {result.returncode}")
    return "\n".join(output)


HANDLERS = {"run_command": run_command}
