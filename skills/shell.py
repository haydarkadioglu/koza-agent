"""Shell skill — run commands on Windows (PowerShell/cmd) and Linux (bash)."""
import os
import platform
import subprocess
import threading
import shlex
import time
from pathlib import Path

# Tracks the current working directory across tool calls on a per-thread basis.
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

    system = platform.system()
    # Use Popen for timeout-resilient execution
    shell_cmd = ["bash", "-c", command] if system != "Windows" else ["pwsh", "-NoProfile", "-Command", command]
    try:
        proc = subprocess.Popen(
            shell_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=effective_cwd,
        )
    except FileNotFoundError:
        if system == "Windows":
            proc = subprocess.Popen(
                ["cmd", "/c", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=effective_cwd,
            )
        else:
            return f"ERROR: Shell not found"
    except Exception as e:
        return f"ERROR: {e}"

    # Poll until timeout, then check if still running
    deadline = time.time() + timeout
    poll_interval = 2
    partial = []
    while time.time() < deadline:
        ret = proc.poll()
        if ret is not None:
            # Process finished
            break
        remaining = max(0, int(deadline - time.time()))
        time.sleep(min(poll_interval, remaining))
    else:
        # Timeout reached — check if still alive
        ret = proc.poll()
        if ret is None:
            # Still running — don't kill, return partial output with status
            # Try to read whatever stdout is available so far
            try:
                proc.stdout.flush()
                partial_out = proc.stdout.read(4096) if proc.stdout else ""
                partial_err = proc.stderr.read(2048) if proc.stderr else ""
            except Exception:
                partial_out = ""
                partial_err = ""
            output = [f"Working directory: {effective_cwd}"]
            if partial_out:
                output.append(partial_out.strip())
            if partial_err:
                output.append(f"STDERR:\n{partial_err.strip()}")
            output.append(f"⏳ Command still running after {timeout}s. Still in progress — do not retry, wait for next poll.")
            return "\n".join(output)

    # Process finished — read remaining output
    try:
        stdout, stderr = proc.communicate(timeout=5)
    except Exception:
        try:
            stdout = proc.stdout.read() if proc.stdout else ""
            stderr = proc.stderr.read() if proc.stderr else ""
        except Exception:
            stdout = ""
            stderr = ""

    output = [f"Working directory: {effective_cwd}"]
    if stdout.strip():
        output.append(stdout.strip())
    if stderr.strip():
        output.append(f"STDERR:\n{stderr.strip()}")
    output.append(f"Exit code: {ret}")

    if ret == 0 and clone_target and Path(clone_target).is_dir():
        set_cwd(clone_target)
        output.append(f"Working directory updated to cloned repo: {clone_target}")
    return "\n".join(output)


HANDLERS = {"run_command": run_command}
