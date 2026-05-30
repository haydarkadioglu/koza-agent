"""Filesystem skill — read, write, list, create dir, delete."""
import os
import shutil
from pathlib import Path
from skills.shell import get_cwd


def _resolve(path: str) -> Path:
    """Resolve path: expand ~, then resolve relative to shell's tracked CWD."""
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = Path(get_cwd()) / p
    return p.resolve()


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file. "
                "Use absolute paths (e.g. /home/user/file.txt or C:/Users/user/file.txt). "
                "Use '~' to refer to the user's home directory (e.g. ~/file.txt). "
                "Relative paths resolve from the current working directory (NOT home)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute or relative file path. Use ~ for home directory."}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file (creates or overwrites).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "append": {"type": "boolean", "description": "Append instead of overwrite", "default": False},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": (
                "List contents of a directory. "
                "Use '.' or omit for current directory, '~' for home directory, "
                "or provide an absolute path like 'C:/Users/foo' or '/home/foo'. "
                "Relative paths are resolved from the current working directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Directory path. Use '~' for home, '.' for current.", "default": "."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_dir",
            "description": "Create a directory (including parents).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file or directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean", "default": False},
                },
                "required": ["path"],
            },
        },
    },
]


def read_file(path: str) -> str:
    try:
        return _resolve(path).read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: {e}"


def write_file(path: str, content: str, append: bool = False) -> str:
    try:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        if append:
            p.open("a", encoding="utf-8").write(content)
        else:
            p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {p}"
    except Exception as e:
        return f"ERROR: {e}"


def list_dir(path: str = ".") -> str:
    try:
        entries = []
        for entry in sorted(_resolve(path).iterdir()):
            kind = "DIR " if entry.is_dir() else "FILE"
            entries.append(f"{kind}  {entry.name}")
        return "\n".join(entries) if entries else "(empty)"
    except Exception as e:
        return f"ERROR: {e}"


def create_dir(path: str) -> str:
    try:
        _resolve(path).mkdir(parents=True, exist_ok=True)
        return f"Directory created: {_resolve(path)}"
    except Exception as e:
        return f"ERROR: {e}"


def delete_file(path: str, recursive: bool = False) -> str:
    try:
        p = _resolve(path)
        if p.is_dir():
            if recursive:
                shutil.rmtree(p)
            else:
                p.rmdir()
        else:
            p.unlink()
        return f"Deleted: {p}"
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_dir": list_dir,
    "create_dir": create_dir,
    "delete_file": delete_file,
}
