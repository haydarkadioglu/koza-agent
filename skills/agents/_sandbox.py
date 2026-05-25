"""Sub-agent sandbox — restricts write operations to the agent's working directory.

Only SANDBOXED_TOOLS are wrapped; read operations and shell commands are unrestricted.
The agent's own source repo is always protected regardless of agent_dir.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Callable

# Root of the koza source repo — always protected from writes
_AGENT_REPO: Path = Path(__file__).resolve().parent.parent.parent

SANDBOXED_TOOLS: tuple[str, ...] = ("write_file", "delete_file", "create_dir")


def _resolve_path(path: str, cwd: str) -> Path:
    """Return an absolute, canonical Path, resolving ~ and relative segments."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(cwd) / p
    return p.resolve()


def _is_within(target: Path, boundary: Path) -> bool:
    """Return True if target is inside boundary (or is boundary itself)."""
    try:
        target.relative_to(boundary)
        return True
    except ValueError:
        return False


def validate_path(path: str, agent_dir: str, cwd: str) -> str | None:
    """
    Check whether a path is safe for a sandboxed write operation.

    Returns:
        None   — path is allowed
        str    — error message explaining why the path is blocked
    """
    if not path:
        return "error: empty path is not allowed"

    resolved = _resolve_path(path, cwd)
    boundary = Path(agent_dir).resolve()

    # Repo protection takes precedence
    if _is_within(resolved, _AGENT_REPO):
        return (
            f"error: write blocked — path {resolved} is inside the koza source repo "
            f"({_AGENT_REPO}). Sub-agents may not modify the agent's own code."
        )

    # Must be inside the agent's working directory
    if not _is_within(resolved, boundary):
        return (
            f"error: write blocked — path {resolved} is outside the agent sandbox "
            f"({boundary}). Use relative paths or paths within your working directory."
        )

    return None


def sandbox_wrap(handler: Callable, agent_dir: str, cwd: str) -> Callable:
    """
    Wrap a file-write handler so it validates the target path before executing.
    The first positional argument or the 'path' keyword argument is checked.
    """
    @functools.wraps(handler)
    def _wrapped(*args, **kwargs):
        # Determine which argument is the target path
        path_val = kwargs.get("path") or (args[0] if args else "")
        err = validate_path(str(path_val), agent_dir, cwd)
        if err:
            return err
        return handler(*args, **kwargs)

    return _wrapped


def apply_sandbox(handlers: dict[str, Callable], agent_dir: str, cwd: str) -> dict[str, Callable]:
    """
    Return a new handlers dict where SANDBOXED_TOOLS are wrapped with path validation.
    All other handlers are passed through unchanged.
    """
    result = {}
    for name, fn in handlers.items():
        if name in SANDBOXED_TOOLS:
            result[name] = sandbox_wrap(fn, agent_dir, cwd)
        else:
            result[name] = fn
    return result
