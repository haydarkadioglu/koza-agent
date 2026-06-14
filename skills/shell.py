"""Shell skill — run commands on Windows (PowerShell/cmd) and Linux (bash)."""
import os
import platform
import subprocess
import threading
import shlex
import time
from pathlib import Path

# Tracks the current working directory across tool calls on a per-thread basis.
from config import load_config
_thread_local = threading.local()


def get_cwd() -> str:
    if not hasattr(_thread_local, "cwd"):
        _thread_local.cwd = os.getcwd()
    return _thread_local.cwd


def set_cwd(path: str) -> None:
    _thread_local.cwd = os.path.abspath(path)


def resolve_path(path: str) -> str:
    base = get_cwd()
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
                "Use 'cd <path>' as the command to change the working directory for future commands. "
                "If a command requires Administrator privileges on Windows, you must use: "
                "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -Command \"<your command>\"'"
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


def _read_stream(stream, lines_list):
    try:
        for line in iter(stream.readline, ''):
            lines_list.append(line)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def run_command(command: str, cwd: str = None, timeout: int = 30) -> str:
    # Handle bare 'cd' commands — update our tracked CWD
    stripped = command.strip()
    if stripped.lower().startswith("cd ") or stripped.lower() == "cd":
        parts = stripped.split(None, 1)
        target = parts[1] if len(parts) > 1 else os.path.expanduser("~")
        current_cwd = get_cwd()
        new_dir = os.path.abspath(os.path.join(current_cwd, os.path.expanduser(target)))
        if os.path.isdir(new_dir):
            set_cwd(new_dir)
            return f"Changed directory to: {new_dir}"
        return f"ERROR: Directory not found: {new_dir}"

    current_cwd = get_cwd()
    effective_cwd = os.path.abspath(os.path.join(current_cwd, os.path.expanduser(cwd))) if cwd else current_cwd
    if not os.path.isdir(effective_cwd):
        return f"ERROR: Working directory does not exist: {effective_cwd}"

    clone_target = _detect_git_clone_target(command.strip(), effective_cwd)

    cfg = load_config()
    backend = cfg.get("terminal", {}).get("backend", "local")

    if backend == "docker":
        from skills.environments import DockerEnvironment
        ws_path = cfg.get("workspace_path", str(Path(os.path.expanduser("~")) / ".Koza" / "workspace"))
        env = DockerEnvironment(ws_path)
    else:
        from skills.environments import LocalEnvironment
        env = LocalEnvironment()

    ret, stdout, stderr = env.execute(command, cwd=effective_cwd, timeout=timeout)

    output = [f"Working directory: {effective_cwd}"]
    if stdout.strip():
        output.append(stdout.strip())
    if stderr.strip():
        output.append(f"STDERR:\n{stderr.strip()}")

    if ret == -1 and not stdout and not stderr:
        output.append(f"⏳ Command timed out or execution failed after {timeout}s.")
    else:
        output.append(f"Exit code: {ret}")

    if ret == 0 and clone_target and Path(clone_target).is_dir():
        set_cwd(clone_target)
        output.append(f"Working directory updated to cloned repo: {clone_target}")
    return "\n".join(output)


HANDLERS = {"run_command": run_command}
