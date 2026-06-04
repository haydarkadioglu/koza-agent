"""
Code Tools — patch, search, format, lint, and test utilities for coding workflows.

Extends Koza's basic code execution with professional-grade code manipulation:
- patch_file: find-and-replace specific text in existing files
- search_files: regex/grep search across project files
- format_code: auto-format Python (black) and JS/TS (prettier)
- lint_code: syntax and style checks
- run_tests: run test suites with output capture
- read_file_range: read specific line ranges from files
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resolve(path: str) -> Path:
    """Resolve path relative to shell CWD."""
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        try:
            from skills.shell import get_cwd
            p = Path(get_cwd()) / p
        except Exception:
            pass
    return p.resolve()


def _run(cmd: list, cwd: str | None = None, timeout: int = 60) -> tuple[str, int]:
    """Run a command and return (output, exit_code)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        out = (result.stdout + result.stderr).strip()
        return out, result.returncode
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s", -1
    except FileNotFoundError:
        return f"Command not found: {cmd[0]}", -1
    except Exception as e:
        return f"ERROR: {e}", -1


def _find_files(pattern: str, root: str, file_glob: str = "") -> list[Path]:
    """Find files matching a pattern using rg/grep or Python fallback."""
    root_path = _resolve(root)
    if not root_path.exists():
        return []

    # Try ripgrep first (much faster)
    rg_cmd = ["rg", "-l", "--no-heading", pattern, str(root_path)]
    if file_glob:
        rg_cmd.extend(["-g", file_glob])
    try:
        result = subprocess.run(rg_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode in (0, 1):  # 1 = no matches
            return [Path(p) for p in result.stdout.strip().split("\n") if p.strip()]
    except FileNotFoundError:
        pass

    # Fallback: Python os.walk
    matches = []
    for root_dir, dirs, files in os.walk(root_path):
        # Skip hidden dirs
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if file_glob and not Path(f).match(file_glob):
                continue
            fp = Path(root_dir) / f
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                if re.search(pattern, content):
                    matches.append(fp)
            except Exception:
                continue
    return matches


# ─── Tool: patch_file ─────────────────────────────────────────────────────────

def patch_file(path: str, old_string: str, new_string: str, count: int = 1) -> str:
    """Find and replace text in a file. Use for targeted edits without rewriting the whole file.
    
    Args:
        path: File path.
        old_string: Text to find (must be unique unless count > 1).
        new_string: Replacement text.
        count: Number of occurrences to replace (default 1, use 0 for all).
    
    Returns:
        Summary of changes made.
    """
    try:
        p = _resolve(path)
        if not p.exists():
            return f"❌ File not found: {p}"

        content = p.read_text(encoding="utf-8")
        if old_string not in content:
            return f"❌ Pattern not found in {p.name}"

        if count == 0:
            # Replace all
            new_content = content.replace(old_string, new_string)
            replace_count = content.count(old_string)
        else:
            # Replace first N
            new_content = content.replace(old_string, new_string, count)
            replace_count = min(count, content.count(old_string))

        p.write_text(new_content, encoding="utf-8")

        # Show context around changes
        lines = content.split("\n")
        new_lines = new_content.split("\n")
        changed_lines = []
        for i, (old_l, new_l) in enumerate(zip(lines, new_lines)):
            if old_l != new_l:
                changed_lines.append(f"  L{i+1}: -{old_l}")
                changed_lines.append(f"       +{new_l}")

        preview = "\n".join(changed_lines[:10])
        if len(changed_lines) > 10:
            preview += f"\n  ... and {len(changed_lines) - 10} more changes"

        return (
            f"✅ Patched {p.name}: {replace_count} replacement(s)\n"
            f"   Path: {p}\n"
            f"{preview}"
        )
    except Exception as e:
        return f"❌ Error: {e}"


# ─── Tool: search_files ───────────────────────────────────────────────────────

def search_files(pattern: str, path: str = ".", file_glob: str = "", 
                 context: int = 0, output_mode: str = "content") -> str:
    """Search for a regex pattern across files. Like grep but for codebases.
    
    Args:
        pattern: Regex pattern to search for.
        path: Root directory to search (default: current dir).
        file_glob: Optional file filter (e.g. '*.py', '*.js').
        context: Lines of context before/after each match (default 0).
        output_mode: 'content' (default), 'files_only', or 'count'.
    
    Returns:
        Matching results with file paths and line numbers.
    """
    root = _resolve(path)
    if not root.exists():
        return f"❌ Path not found: {root}"

    # Try ripgrep for best results
    try:
        cmd = ["rg", "--no-heading", "--line-number"]
        if context > 0:
            cmd.extend(["-C", str(context)])
        if file_glob:
            cmd.extend(["-g", file_glob])
        if output_mode == "files_only":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")
        cmd.extend([pattern, str(root)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            output = result.stdout.strip()
            line_count = len(output.split("\n")) if output else 0
            return f"🔍 Found {line_count} match(es) for '{pattern}':\n\n{output}"
        elif result.returncode == 1:
            return f"🔍 No matches found for '{pattern}'."
        else:
            # rg had an error, fall through to Python
            pass
    except FileNotFoundError:
        pass

    # Fallback: Python rg-like search
    matches = []
    try:
        import fnmatch
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for f in files:
                if file_glob and not fnmatch.fnmatch(f, file_glob):
                    continue
                fp = Path(root_dir) / f
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                    for i, line in enumerate(content.split("\n"), 1):
                        if re.search(pattern, line):
                            rel = fp.relative_to(root) if root != fp else fp.name
                            prefix = f"{rel}:{i}:"
                            if output_mode == "files_only":
                                matches.append(str(rel))
                                break
                            elif output_mode == "count":
                                matches.append(str(rel))
                                break  # count per file
                            else:
                                matches.append(f"{prefix}{line.strip()}")
                                if context > 0:
                                    ctx_lines = content.split("\n")
                                    start = max(0, i - 1 - context)
                                    end = min(len(ctx_lines), i + context)
                                    for ci in range(start, end):
                                        if ci != i - 1:
                                            marker = ">" if ci == i - 1 else " "
                                            matches.append(f"  {marker}{ctx_lines[ci].strip()}")
                except Exception:
                    continue
    except Exception as e:
        return f"❌ Search error: {e}"

    if not matches:
        return f"🔍 No matches found for '{pattern}'."

    if output_mode == "count":
        from collections import Counter
        counts = Counter(matches)
        lines = [f"  {k}: {v}" for k, v in counts.most_common()]
        return f"🔍 {sum(counts.values())} match(es) in {len(counts)} file(s):\n" + "\n".join(lines)

    return f"🔍 Found {len(matches)} match(es) for '{pattern}':\n\n" + "\n".join(matches[:100])


# ─── Tool: format_code ────────────────────────────────────────────────────────

def format_code(path: str, check_only: bool = False) -> str:
    """Auto-format a code file. Supports Python (black), JS/TS/JSON/CSS (prettier).
    
    Args:
        path: File or directory to format.
        check_only: If True, only check if formatting is needed (don't modify).
    """
    p = _resolve(path)
    if not p.exists():
        return f"❌ Path not found: {p}"

    suffix = p.suffix.lower() if p.is_file() else ""

    # Python: use black
    if suffix == ".py" or (p.is_dir() and any(p.rglob("*.py"))):
        cmd = ["black", "--quiet"]
        if check_only:
            cmd.append("--check")
        cmd.append(str(p))
        out, code = _run(cmd, timeout=60)
        if code == 0:
            return "✅ Already formatted (black)" if check_only else f"✅ Formatted with black: {p.name}"
        elif code == 1 and not check_only:
            return f"✅ Formatted with black: {p.name}"
        else:
            return f"ℹ️  black: {out[:300]}"

    # JS/TS/JSON/CSS/MD: use prettier
    if suffix in (".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".scss", ".md", ".html"):
        cmd = ["npx", "prettier", "--write"]
        if check_only:
            cmd = ["npx", "prettier", "--check"]
        cmd.append(str(p))
        out, code = _run(cmd, timeout=60)
        if code == 0:
            return f"✅ Formatted with prettier: {p.name}"
        return f"ℹ️  prettier: {out[:300]}"

    return f"ℹ️  No formatter available for {suffix or 'directory'}. Supported: .py (black), .js/.ts/.json/.css (prettier)"


# ─── Tool: lint_code ──────────────────────────────────────────────────────────

def lint_code(path: str) -> str:
    """Run linting on a code file. Python: flake8/pylint. JS: eslint."""
    p = _resolve(path)
    if not p.exists():
        return f"❌ Path not found: {p}"

    suffix = p.suffix.lower() if p.is_file() else ""

    if suffix == ".py":
        # Try flake8 first, then pylint
        out, code = _run(["flake8", str(p)], timeout=30)
        if code == 0:
            return f"✅ No lint errors (flake8): {p.name}"
        elif code != -1:  # flake8 exists but found issues
            return f"🔍 flake8 ({p.name}):\n{out[:1000]}"
        # Fallback to pylint
        out2, code2 = _run(["pylint", "--score=n", str(p)], timeout=30)
        if code2 == 0:
            return f"✅ No lint errors (pylint): {p.name}"
        return f"🔍 pylint ({p.name}):\n{out2[:1000]}"

    if suffix in (".js", ".jsx", ".ts", ".tsx"):
        out, code = _run(["npx", "eslint", str(p)], timeout=30)
        if code == 0:
            return f"✅ No lint errors (eslint): {p.name}"
        return f"🔍 eslint ({p.name}):\n{out[:1000]}"

    return f"ℹ️  No linter available for {suffix}. Supported: .py (flake8/pylint), .js/.ts (eslint)"


# ─── Tool: run_tests ──────────────────────────────────────────────────────────

def run_tests(path: str = "", command: str = "", timeout: int = 180) -> str:
    """Run tests in a project directory. Auto-detects test framework if no command given.
    
    Args:
        path: Project directory (default: current dir).
        command: Optional explicit test command.
        timeout: Command timeout in seconds (default 180).
    """
    target = _resolve(path) if path else Path.cwd()
    if not target.exists():
        return f"❌ Directory not found: {target}"

    # Auto-detect test command
    if not command:
        if (target / "pyproject.toml").exists():
            command = "python -m pytest -x -q"
        elif (target / "setup.py").exists() or list(target.glob("*test*.py")) or list(target.glob("tests/")):
            command = "python -m pytest -x -q"
        elif (target / "package.json").exists():
            pkg = json.loads((target / "package.json").read_text())
            scripts = pkg.get("scripts", {})
            command = scripts.get("test", "npm test")
        elif list(target.glob("*test*.js")) or list(target.glob("*spec*.js")):
            command = "npx jest --no-coverage"
        else:
            return "ℹ️  No test framework detected. Specify a command, e.g. run_tests(command='python -m pytest')"

    out, code = _run(["bash", "-c", command], str(target), timeout)

    # Truncate very long output
    if len(out) > 3000:
        out = out[:1500] + "\n... (truncated) ...\n" + out[-1500:]

    status = "✅ Passed" if code == 0 else f"❌ Failed (exit: {code})"
    return f"🧪 Tests: {status}\n   Command: {command}\n   Dir: {target}\n\n{out}"


# ─── Tool: read_file_range ────────────────────────────────────────────────────

def read_file_range(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """Read a specific range of lines from a file. Useful for reading code sections.

    Args:
        path: File path.
        start_line: First line to read (1-indexed).
        end_line: Last line to read (0 = read to end).
    """
    try:
        p = _resolve(path)
        if not p.exists():
            return f"❌ File not found: {p}"

        lines = p.read_text(encoding="utf-8").split("\n")
        total = len(lines)

        if end_line <= 0 or end_line > total:
            end_line = total
        if start_line < 1:
            start_line = 1
        if start_line > total:
            return f"❌ Start line {start_line} exceeds file length ({total} lines)"

        selected = lines[start_line - 1:end_line]
        result = "\n".join(
            f"{i + start_line:>4}|{line}" for i, line in enumerate(selected)
        )
        return f"📄 {p.name} (lines {start_line}-{end_line} of {total}):\n\n{result}"
    except Exception as e:
        return f"❌ Error: {e}"


# ─── Registry ─────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "patch_file",
        "description": "Find and replace text in a file. Use for targeted code edits without rewriting the whole file. Shows a diff of changes made.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit"},
                "old_string": {"type": "string", "description": "Text to find. Must be unique in file unless count > 1."},
                "new_string": {"type": "string", "description": "Replacement text"},
                "count": {"type": "integer", "default": 1, "description": "Replace count: 1=first, 0=all"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for a regex pattern across files. Like grep but searches entire codebase. Use to find function definitions, imports, or any text pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "default": ".", "description": "Root directory (default: current)"},
                "file_glob": {"type": "string", "default": "", "description": "File filter (e.g. '*.py', '*.js')"},
                "context": {"type": "integer", "default": 0, "description": "Lines of context before/after each match"},
                "output_mode": {"type": "string", "default": "content", "enum": ["content", "files_only", "count"]},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "format_code",
        "description": "Auto-format code files. Python files use black, JS/TS/JSON/CSS use prettier. Supports check-only mode.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to format"},
                "check_only": {"type": "boolean", "default": False, "description": "If True, only check if formatting is needed"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "lint_code",
        "description": "Run linting on a code file. Python: flake8/pylint. JavaScript/TypeScript: eslint.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to lint"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_tests",
        "description": "Run tests in a project directory. Auto-detects framework (pytest, jest) or accepts explicit command.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "", "description": "Project directory (default: current dir)"},
                "command": {"type": "string", "default": "", "description": "Explicit test command (auto-detected if empty)"},
                "timeout": {"type": "integer", "default": 180, "description": "Timeout in seconds"},
            },
        },
    },
    {
        "name": "read_file_range",
        "description": "Read a specific range of lines from a file with line numbers. Use to inspect code sections without reading the entire file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "start_line": {"type": "integer", "default": 1, "description": "First line to read (1-indexed)"},
                "end_line": {"type": "integer", "default": 0, "description": "Last line to read (0 = read to end)"},
            },
            "required": ["path"],
        },
    },
]

HANDLERS: dict = {
    "patch_file":      lambda path, old_string, new_string, count=1: patch_file(path, old_string, new_string, int(count)),
    "search_files":    lambda pattern, path=".", file_glob="", context=0, output_mode="content": search_files(pattern, path, file_glob, int(context), output_mode),
    "format_code":     lambda path, check_only=False: format_code(path, check_only),
    "lint_code":       lambda path: lint_code(path),
    "run_tests":       lambda path="", command="", timeout=180: run_tests(path, command, int(timeout)),
    "read_file_range": lambda path, start_line=1, end_line=0: read_file_range(path, int(start_line), int(end_line)),
}
