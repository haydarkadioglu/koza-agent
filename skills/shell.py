"""Shell skill — run commands on Windows (PowerShell/cmd) and Linux (bash)."""
import os
import platform
import subprocess
import threading
import shlex
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


def resolve_path(path: str) -> str:
    with _cwd_lock:
        base = _CWD
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)
    return os.path.abspath(os.path.join(base, expanded))


def _repo_dir_name(value: str) -> str:
    name = value.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repository"


def _detect_git_clone_target(command: str, base_dir: str) -> str | None:
    """Return the target directory for a simple `git clone ...` command."""
    try:
        parts = shlex.split(command, posix=(platform.system() != "Windows"))
    except ValueError:
        return None
    if len(parts) < 3 or parts[0] != "git" or parts[1] != "clone":
        return None

    args = parts[2:]
    positional: list[str] = []
    idx = 0
    options_with_values = {
        "-b", "--branch", "--config", "-c", "--depth", "--jobs",
        "--origin", "-o", "--reference", "--reference-if-able",
        "--separate-git-dir", "--shallow-since", "--shallow-exclude",
        "--template", "--upload-pack", "-u",
    }
    while idx < len(args):
        arg = args[idx]
        if arg == "--":
            positional.extend(args[idx + 1:])
            break
        if arg.startswith("-"):
            if arg in options_with_values and idx + 1 < len(args):
                idx += 2
            else:
                idx += 1
            continue
        positional.append(arg)
        idx += 1

    if not positional:
        return None
    repo = positional[0]
    dest = positional[1] if len(positional) > 1 else _repo_dir_name(repo)
    return os.path.abspath(os.path.join(base_dir, os.path.expanduser(dest)))


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
        with _cwd_lock:
            new_dir = os.path.abspath(os.path.join(_CWD, os.path.expanduser(target)))
            if os.path.isdir(new_dir):
                _CWD = new_dir
                return f"Changed directory to: {_CWD}"
        return f"ERROR: Directory not found: {new_dir}"

    with _cwd_lock:
        current_cwd = _CWD
    effective_cwd = os.path.abspath(os.path.join(current_cwd, os.path.expanduser(cwd))) if cwd else current_cwd
    if not os.path.isdir(effective_cwd):
        return f"ERROR: Working directory does not exist: {effective_cwd}"

    clone_target = _detect_git_clone_target(command.strip(), effective_cwd)

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
    output.append(f"Working directory: {effective_cwd}")
    if result.stdout.strip():
        output.append(result.stdout.strip())
    if result.stderr.strip():
        output.append(f"STDERR:\n{result.stderr.strip()}")
    output.append(f"Exit code: {result.returncode}")

    if result.returncode == 0 and clone_target and Path(clone_target).is_dir():
        set_cwd(clone_target)
        output.append(f"Working directory updated to cloned repo: {clone_target}")
    return "\n".join(output)


HANDLERS = {"run_command": run_command}
