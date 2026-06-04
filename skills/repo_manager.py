"""
Repo & Project Manager — clone, list, manage, and run external repos/agents.

Extends Koza's basic github_clone_repo / create_project with:
- repo_list: cloned repos tarama
- repo_prepare_multi: toplu repo clone
- repo_status: repo durumu (branch, commit, dirty)
- repo_run: cloned repo icinde komut calistir
- project_init: template ile proje olustur (gitignore, readme, lisans)
- project_run: projedeki araclari calistir (ornek: pip install && python main.py)
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

# Stable repo storage
_REPOS_DIR = Path.home() / ".Koza" / "workspace" / "repos"
_PROJECTS_DIR = Path.home() / ".Koza" / "workspace" / "projects"

# Common project templates
_TEMPLATES = {
    "python": {
        "gitignore": (
            "__pycache__/\n*.py[cod]\n*.egg-info/\n.venv/\nvenv/\n"
            "dist/\nbuild/\n*.egg\n.env\n*.log\n.DS_Store\n"
        ),
        "readme": "# {name}\n\n## Description\n\n{description}\n\n## Setup\n\n```bash\npython -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt\n```\n",
    },
    "node": {
        "gitignore": (
            "node_modules/\n.env\n.DS_Store\n*.log\ndist/\nbuild/\n"
        ),
        "readme": "# {name}\n\n## Description\n\n{description}\n\n## Setup\n\n```bash\nnpm install\nnpm run dev\n```\n",
    },
    "react": {
        "gitignore": (
            "node_modules/\n.env\n.DS_Store\n*.log\nbuild/\ndist/\n"
        ),
        "readme": "# {name}\n\n## Description\n\n{description}\n\n## Quick Start\n\n```bash\nnpm install\nnpm run dev\n```\n",
    },
    "script": {
        "gitignore": (
            "__pycache__/\n*.pyc\n.env\n.DS_Store\n*.log\n"
        ),
        "readme": "# {name}\n\n## Description\n\n{description}\n\n## Usage\n\n```bash\npython {name}.py\n```\n",
    },
}

_PROJECT_TYPES = list(_TEMPLATES.keys())


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _repo_name_from_url(url: str) -> str:
    """Extract owner_repo from a GitHub URL."""
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parts = url.split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}_{parts[-1]}"
    return parts[-1] if parts else "unknown"


def _run_cmd(cmd: list, cwd: str, timeout: int = 120) -> tuple[str, int]:
    """Run a command and return (output, exit_code)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        out = (result.stdout + result.stderr).strip()
        return out, result.returncode
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s", -1
    except Exception as e:
        return f"ERROR: {e}", -1


# ─── Tool: repo_prepare ───────────────────────────────────────────────────────

def repo_prepare(repo: str, branch: str = "", dest: str = "", update: bool = True) -> str:
    """Clone or update a GitHub repo into stable repo storage."""
    url = repo if repo.startswith("http") else f"https://github.com/{repo}.git"
    if dest:
        target_dir = Path(dest).expanduser().resolve()
    else:
        target_dir = _REPOS_DIR / "github" / _repo_name_from_url(repo)

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    actions = []

    try:
        if (target_dir / ".git").exists():
            actions.append(f"📂 Repo already exists: {target_dir}")
            if update:
                out, code = _run_cmd(["git", "-C", str(target_dir), "pull", "--ff-only"], str(target_dir))
                if code != 0:
                    return f"ERROR: git pull failed\n{out}"
                actions.append(out or "✅ Already up to date.")
        else:
            cmd = ["git", "clone"]
            if branch:
                cmd.extend(["--branch", branch])
            cmd.extend([url, str(target_dir)])
            out, code = _run_cmd(cmd, str(target_dir.parent))
            if code != 0:
                return f"ERROR: git clone failed\n{out}"
            actions.append(out or "✅ Clone complete.")

        # Update shell CWD
        try:
            from skills import shell as _shell
            _shell.set_cwd(str(target_dir))
        except Exception:
            pass

        # Get repo info
        info_out, _ = _run_cmd(["git", "-C", str(target_dir), "log", "--oneline", "-1"], str(target_dir))
        branch_out, _ = _run_cmd(["git", "-C", str(target_dir), "branch", "--show-current"], str(target_dir))

        lines = [
            "📦 Repository Ready",
            f"   Path: {target_dir}",
            f"   Branch: {branch_out.strip() or 'detached'}",
            f"   Latest: {info_out.strip() or 'N/A'}",
            "",
        ]
        lines.extend(actions)
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


# ─── Tool: repo_list ──────────────────────────────────────────────────────────

def repo_list() -> str:
    """List all cloned repositories."""
    repos_dir = _REPOS_DIR / "github"
    if not repos_dir.exists():
        return "📭 No repositories cloned yet."

    repos = sorted(repos_dir.iterdir()) if repos_dir.exists() else []
    if not repos:
        return "📭 No repositories cloned yet."

    lines = [f"📦 Cloned Repositories ({len(repos)}):\n"]
    for repo_dir in repos:
        if not repo_dir.is_dir():
            continue
        # Get basic info
        git_dir = repo_dir / ".git"
        if not git_dir.exists():
            continue

        branch_out, _ = _run_cmd(["git", "-C", str(repo_dir), "branch", "--show-current"], str(repo_dir))
        log_out, _ = _run_cmd(["git", "-C", str(repo_dir), "log", "--oneline", "-1"], str(repo_dir))
        status_out, _ = _run_cmd(["git", "-C", str(repo_dir), "status", "--porcelain"], str(repo_dir))
        dirty = " ⚠ dirty" if status_out.strip() else ""
        last_commit = log_out.strip()[:60] if log_out.strip() else ""

        lines.append(
            f"  📁 {repo_dir.name}{dirty}\n"
            f"     Branch: {branch_out.strip() or 'detached'}\n"
            f"     {last_commit}\n"
            f"     Path: {repo_dir}\n"
        )

    return "\n".join(lines)


# ─── Tool: repo_status ────────────────────────────────────────────────────────

def repo_status(path: str = "") -> str:
    """Show git status of a cloned repo or project."""
    target = Path(path).expanduser().resolve() if path else Path.cwd()
    if not (target / ".git").exists():
        return f"❌ Not a git repository: {target}"

    out, code = _run_cmd(["git", "-C", str(target), "status"], str(target))
    if code != 0:
        return f"❌ Error: {out}"
    return out


# ─── Tool: repo_run ───────────────────────────────────────────────────────────

def repo_run(repo_or_path: str, command: str, timeout: int = 300) -> str:
    """Run a shell command inside the repo directory and return output.

    Auto-resolves 'repo_or_path' — if it matches a cloned repo name,
    runs inside that repo's directory. Otherwise treats as a path.
    """
    # Resolve target directory
    repo_dir = _resolve_repo_dir(repo_or_path)
    if repo_dir is None:
        return f"❌ Repo not found: {repo_or_path}. Use repo_list() to see cloned repos."

    out, code = _run_cmd(["bash", "-c", command], str(repo_dir), timeout)
    header = f"📂 {repo_dir.name} $ {command}\n"
    footer = f"\nExit code: {code}"
    return header + out + footer


def _resolve_repo_dir(name_or_path: str) -> Path | None:
    """Resolve a repo name or path to a directory. Checks repo storage first."""
    # Direct path
    p = Path(name_or_path).expanduser()
    if p.exists() and p.is_dir():
        return p.resolve()

    # Repo storage
    repo_dir = _REPOS_DIR / "github" / name_or_path
    if repo_dir.exists():
        return repo_dir

    # Fuzzy match
    if _REPOS_DIR.exists():
        for d in _REPOS_DIR.rglob(name_or_path):
            if d.is_dir() and (d / ".git").exists():
                return d

    # Projects
    proj_dir = _PROJECTS_DIR / name_or_path
    if proj_dir.exists():
        return proj_dir

    return None


# ─── Tool: project_init ──────────────────────────────────────────────────────

def project_init(name: str, project_type: str = "python", description: str = "") -> str:
    """Create a new project with template files (gitignore, readme, etc.)."""
    safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in name).strip("_") or "project"
    project_dir = _PROJECTS_DIR / safe_name
    project_dir.mkdir(parents=True, exist_ok=True)

    # Get template
    template = _TEMPLATES.get(project_type, _TEMPLATES["python"])

    # Create files
    created = []
    files_to_create = {
        ".gitignore": template["gitignore"],
        "README.md": template["readme"].format(name=safe_name, description=description or "No description"),
    }
    if project_type == "python":
        files_to_create["requirements.txt"] = "# Dependencies\n"

    for filename, content in files_to_create.items():
        filepath = project_dir / filename
        if not filepath.exists():
            filepath.write_text(content, encoding="utf-8")
            created.append(filename)

    # Update CWD
    try:
        from skills import shell as _shell
        _shell.set_cwd(str(project_dir))
    except Exception:
        pass

    lines = [
        f"✅ Project '{safe_name}' created",
        f"   Type: {project_type}",
        f"   Path: {project_dir}",
        f"   Files: {', '.join(created) if created else '(all exist)'}",
        "",
        "   Next steps:",
    ]
    if project_type == "python":
        lines.append("   • python -m venv .venv && source .venv/bin/activate")
        lines.append("   • pip install -r requirements.txt")
    elif project_type in ("node", "react"):
        lines.append("   • npm install")
    lines.append(f"   • cd {project_dir}")

    return "\n".join(lines)


# ─── Tool: project_install_deps ───────────────────────────────────────────────

def project_install_deps(path: str = "") -> str:
    """Auto-detect and install dependencies for a project/repo."""
    target = Path(path).expanduser().resolve() if path else Path.cwd()
    if not target.exists():
        return f"❌ Directory not found: {target}"

    results = []

    # Python: requirements.txt or setup.py
    req_file = target / "requirements.txt"
    setup_file = target / "setup.py"
    pyproject = target / "pyproject.toml"
    if req_file.exists():
        out, code = _run_cmd(["pip", "install", "-r", str(req_file)], str(target), 300)
        results.append(f"pip install -r requirements.txt → {'✅' if code == 0 else '❌'}")
        if code != 0:
            results.append(f"   {out[:200]}")
    elif setup_file.exists() or pyproject.exists():
        out, code = _run_cmd(["pip", "install", "-e", "."], str(target), 300)
        results.append(f"pip install -e . → {'✅' if code == 0 else '❌'}")

    # Node: package.json
    pkg_file = target / "package.json"
    if pkg_file.exists():
        if (target / "node_modules").exists():
            results.append("node_modules already exists (skipping npm install)")
        else:
            out, code = _run_cmd(["npm", "install"], str(target), 300)
            results.append(f"npm install → {'✅' if code == 0 else '❌'}")

    if not results:
        return f"ℹ️  No dependency files found in {target.name}."

    return "📦 Dependency Installation:\n" + "\n".join(results)


# ─── Registry ─────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "repo_prepare",
        "description": "Clone or update a GitHub repo into Koza's stable repo storage (~/.Koza/workspace/repos/github/). Use this for any GitHub repo you want to work with.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/repo or full GitHub URL"},
                "branch": {"type": "string", "default": "", "description": "Optional branch/tag"},
                "dest": {"type": "string", "default": "", "description": "Optional custom destination path"},
                "update": {"type": "boolean", "default": True, "description": "Pull if already cloned"},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "repo_list",
        "description": "List all cloned repositories with branch and last commit info.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "repo_status",
        "description": "Show git status of a cloned repo or project directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "", "description": "Repo path or name (optional, defaults to current dir)"},
            },
        },
    },
    {
        "name": "repo_run",
        "description": "Run a shell command inside a cloned repo or project directory. Auto-resolves repo name. Use this to build, test, or run tools from cloned repos.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_or_path": {"type": "string", "description": "Repo name, owner_repo, or path"},
                "command": {"type": "string", "description": "Shell command to run inside the repo"},
                "timeout": {"type": "integer", "default": 300, "description": "Command timeout in seconds"},
            },
            "required": ["repo_or_path", "command"],
        },
    },
    {
        "name": "project_init",
        "description": "Create a new project folder with template files (gitignore, readme, requirements). Supported types: python, node, react, script.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "project_type": {"type": "string", "default": "python", "enum": _PROJECT_TYPES, "description": "Project template type"},
                "description": {"type": "string", "default": "", "description": "Short project description"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "project_install_deps",
        "description": "Auto-detect and install dependencies for a project or repo. Detects requirements.txt, setup.py, pyproject.toml, and package.json.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "", "description": "Project path (optional, defaults to current dir)"},
            },
        },
    },
]

HANDLERS: dict = {
    "repo_prepare":          lambda repo, branch="", dest="", update=True: repo_prepare(repo, branch, dest, update),
    "repo_list":             lambda: repo_list(),
    "repo_status":           lambda path="": repo_status(path),
    "repo_run":              lambda repo_or_path, command, timeout=300: repo_run(repo_or_path, command, int(timeout)),
    "project_init":          lambda name, project_type="python", description="": project_init(name, project_type, description),
    "project_install_deps":  lambda path="": project_install_deps(path),
}
