"""
Agents package — spawn and manage autonomous sub-agents.
Exports TOOL_DEFINITIONS and HANDLERS for core.py.
"""
import threading
import time
import uuid

from ._registry import _subagents
from .runner import _run_subagent_thread


def spawn_subagent(goal: str, provider: str = "", model: str = "",
                   tools: str = "", capabilities: str = "",
                   wait: bool = True) -> str:
    """Spawn a sub-agent with a specific goal. Runs in-process in a thread."""
    from tools.capabilities import resolve_capabilities

    # Resolve named capability groups into individual tool names
    cap_names    = [c.strip() for c in capabilities.split(",") if c.strip()] if capabilities else []
    cap_tools    = resolve_capabilities(cap_names)

    # Merge individual tool names with capability-derived ones (deduplicated)
    explicit     = [t.strip() for t in tools.split(",") if t.strip()] if tools else []
    seen: set    = set()
    tools_filter = []
    for t in cap_tools + explicit:
        if t not in seen:
            seen.add(t)
            tools_filter.append(t)

    agent_id = str(uuid.uuid4())[:8]
    _subagents[agent_id] = {
        "id": agent_id, "goal": goal[:80], "status": "pending",
        "result": "", "messages": [], "started": time.time(),
        "capabilities": cap_names,
    }

    t = threading.Thread(
        target=_run_subagent_thread,
        args=(agent_id, goal, provider, model, tools_filter),
        daemon=True,
    )
    t.start()

    if wait:
        t.join(timeout=180)
        ag     = _subagents[agent_id]
        status = ag["status"]
        result = ag.get("result", "")
        return f"[Sub-agent {agent_id}] {status}\n{result}"
    return f"Sub-agent {agent_id} launched (background). Use get_subagent_status('{agent_id}') to check."


def get_subagent_status(agent_id: str) -> str:
    """Check the status and result of a running or completed sub-agent."""
    ag = _subagents.get(agent_id)
    if not ag:
        if not _subagents:
            return "No sub-agents have been spawned in this session."
        lines = [f"#{a['id']}: {a['status']} — {a['goal']}" for a in _subagents.values()]
        return "Active sub-agents:\n" + "\n".join(lines)
    elapsed = round(time.time() - ag["started"], 1)
    workdir = ag.get("workdir", "")
    workdir_line = f"\n  Workdir: {workdir}" if workdir else ""
    return (
        f"Sub-agent {agent_id}\n"
        f"  Status : {ag['status']}\n"
        f"  Goal   : {ag['goal']}\n"
        f"  Elapsed: {elapsed}s{workdir_line}\n"
        f"  Result : {ag.get('result', '')[:500]}"
    )


def list_subagents() -> str:
    """List all sub-agents spawned this session."""
    if not _subagents:
        return "No sub-agents spawned yet."
    lines = []
    for ag in _subagents.values():
        elapsed = round(time.time() - ag["started"], 1)
        lines.append(f"  #{ag['id']} [{ag['status']}] {elapsed}s — {ag['goal']}")
    return "Sub-agents this session:\n" + "\n".join(lines)


def list_capabilities() -> str:
    """List all available capability groups and the tools they include."""
    from tools.capabilities import CAPABILITY_GROUPS
    lines = ["Available capability groups:\n"]
    for name, tool_list in sorted(CAPABILITY_GROUPS.items()):
        lines.append(f"  {name:12s} → {', '.join(tool_list)}")
    return "\n".join(lines)


def create_project(name: str, description: str = "") -> str:
    """Create a named project folder under workspace/projects/ and switch into it."""
    import re
    from pathlib import Path
    from config import load_config
    from skills import shell as _shell

    cfg = load_config()
    ws = Path(cfg.get("workspace_path", str(Path.home() / ".Koza" / "workspace")))
    # Sanitize folder name
    safe_name = re.sub(r"[^\w\-]", "_", name.strip()).strip("_") or "project"
    project_dir = ws / "projects" / safe_name
    project_dir.mkdir(parents=True, exist_ok=True)
    if description:
        (project_dir / "README.md").write_text(f"# {name}\n\n{description}\n", encoding="utf-8")
    _shell.set_cwd(str(project_dir))
    return f"✅ Project '{safe_name}' ready at: {project_dir}\nWorking directory set to project folder."


def list_projects() -> str:
    """List all projects in the workspace projects folder."""
    from pathlib import Path
    from config import load_config

    cfg = load_config()
    ws = Path(cfg.get("workspace_path", str(Path.home() / ".Koza" / "workspace")))
    projects_dir = ws / "projects"
    if not projects_dir.exists():
        return "No projects yet."
    projects = [p for p in projects_dir.iterdir() if p.is_dir()]
    if not projects:
        return "No projects yet."
    lines = []
    for p in sorted(projects):
        readme = p / "README.md"
        desc = ""
        if readme.exists():
            first_line = readme.read_text(encoding="utf-8").splitlines()
            desc = next((l for l in first_line if l and not l.startswith("#")), "")
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        size_str = f"{size/1024:.1f}KB" if size < 1024*1024 else f"{size/1024/1024:.1f}MB"
        lines.append(f"  📁 {p.name}  ({size_str}){('  — ' + desc) if desc else ''}")
    return "Projects:\n" + "\n".join(lines)


def clean_workspace(scope: str = "all") -> str:
    """
    Remove empty files and empty folders from the workspace.
    scope: 'all' | 'tmp' | 'subagents' | 'projects' | 'downloads'
    """
    from pathlib import Path
    from config import load_config

    cfg = load_config()
    ws = Path(cfg.get("workspace_path", str(Path.home() / ".Koza" / "workspace")))
    if not ws.exists():
        return "Workspace does not exist yet."

    targets = {
        "all":       [ws],
        "tmp":       [ws / "tmp"],
        "subagents": [ws / "subagents"],
        "projects":  [ws / "projects"],
        "downloads": [ws / "downloads"],
    }
    dirs_to_clean = targets.get(scope, [ws])

    total_files = total_dirs = 0
    for d in dirs_to_clean:
        if not d.exists():
            continue
        # Empty files
        for f in list(d.rglob("*")):
            if f.is_file() and f.stat().st_size == 0:
                try:
                    f.unlink()
                    total_files += 1
                except Exception:
                    pass
        # Empty dirs bottom-up
        for sub in sorted(d.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if sub.is_dir() and not any(sub.iterdir()):
                try:
                    sub.rmdir()
                    total_dirs += 1
                except Exception:
                    pass

    return (
        f"✅ Workspace cleanup done.\n"
        f"   Removed {total_files} empty file(s) and {total_dirs} empty folder(s) "
        f"from '{scope}' scope."
    )


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "spawn_subagent",
        "description": (
            "Spawn an autonomous sub-agent with its own tool-calling loop to handle a sub-task. "
            "Runs in the background and returns its result. "
            "Use for parallel work, research tasks, or delegating complex sub-problems. "
            "Use 'capabilities' to give named skill bundles (e.g. 'browser,files') instead of listing individual tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal":         {"type": "string",  "description": "The task or goal for the sub-agent"},
                "provider":     {"type": "string",  "default": "", "description": "LLM provider override"},
                "model":        {"type": "string",  "default": "", "description": "Model override"},
                "tools":        {"type": "string",  "default": "", "description": "Comma-separated individual tool names (empty = all)"},
                "capabilities": {"type": "string",  "default": "", "description": "Comma-separated capability group names (e.g. 'browser,files,code'). Use list_capabilities() to see available groups."},
                "wait":         {"type": "boolean", "default": True, "description": "Wait for completion or launch in background"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "list_capabilities",
        "description": "List all available capability groups and the tools they include. Use this to discover what to pass in spawn_subagent's 'capabilities' parameter.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_subagent_status",
        "description": "Check the status and result of a previously spawned sub-agent by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "ID returned by spawn_subagent"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "list_subagents",
        "description": "List all sub-agents spawned this session with their status.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "create_project",
        "description": (
            "Create a new named project folder under workspace/projects/ and switch the working directory into it. "
            "Use this whenever the user asks you to build an app, start a new project, or create a new codebase. "
            "All subsequent files will be created inside this project folder."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "Project name (used as folder name)"},
                "description": {"type": "string", "default": "", "description": "Short description written to README.md"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_projects",
        "description": "List all existing projects in the workspace.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "clean_workspace",
        "description": (
            "Remove empty files and empty folders from the workspace. "
            "Use scope='all' for the whole workspace, or 'tmp'/'subagents'/'projects'/'downloads' for a specific area."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "default": "all",
                          "enum": ["all", "tmp", "subagents", "projects", "downloads"],
                          "description": "Which part of the workspace to clean"},
            },
            "required": [],
        },
    },
]

HANDLERS: dict = {
    "spawn_subagent":      lambda goal, provider="", model="", tools="", capabilities="", wait=True:
                               spawn_subagent(goal, provider, model, tools, capabilities, wait),
    "get_subagent_status": lambda agent_id: get_subagent_status(agent_id),
    "list_subagents":      lambda **_: list_subagents(),
    "list_capabilities":   lambda **_: list_capabilities(),
    "create_project":      lambda name, description="": create_project(name, description),
    "list_projects":       lambda **_: list_projects(),
    "clean_workspace":     lambda scope="all": clean_workspace(scope),
}
