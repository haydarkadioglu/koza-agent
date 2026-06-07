"""
Agents package — spawn and manage autonomous sub-agents.
Exports TOOL_DEFINITIONS and HANDLERS for core.py.
"""
import threading
import time
import uuid

from ._registry import _subagents, _registry_lock
from .runner import _run_subagent_thread
from .background import BackgroundTaskManager, _background_tasks
from .swarm import run_swarm


def init_db(db_path: str) -> None:
    """Initialize SQLite tables for sub-agents and background tasks."""
    _subagents.init_db(db_path)
    from .background import init_db as init_bg_db
    init_bg_db(db_path)



def spawn_subagent(goal: str, provider: str = "", model: str = "",
                   tools: str = "", capabilities: str = "",
                   wait: bool = True) -> str:
    """Spawn a sub-agent with a specific goal. Runs in-process in a thread."""
    from tools.capabilities import resolve_capabilities

    cap_names    = [c.strip() for c in capabilities.split(",") if c.strip()] if capabilities else []
    cap_tools    = resolve_capabilities(cap_names)

    explicit     = [t.strip() for t in tools.split(",") if t.strip()] if tools else []
    seen: set    = set()
    tools_filter = []
    for t in cap_tools + explicit:
        if t not in seen:
            seen.add(t)
            tools_filter.append(t)

    agent_id     = str(uuid.uuid4())[:8]
    cancel_event = threading.Event()
    with _registry_lock:
        _subagents[agent_id] = {
            "id": agent_id, "goal": goal[:80], "status": "pending",
            "result": "", "messages": [], "started": time.time(),
            "capabilities": cap_names,
            "_cancel": cancel_event,
        }

    t = threading.Thread(
        target=_run_subagent_thread,
        args=(agent_id, goal, provider, model, tools_filter, "", cancel_event),
        daemon=True,
    )
    t.start()

    if wait:
        t.join(timeout=900)  # 15 minutes max for long-running tasks
        with _registry_lock:
            ag     = _subagents[agent_id]
            status = ag["status"]
            result = ag.get("result", "")
        return f"[Sub-agent {agent_id}] {status}\n{result}"
    return f"Sub-agent {agent_id} launched (background). Use get_subagent_status('{agent_id}') to check."


def start_tracked_coding_task(goal: str, checklist: str = "", followup_minutes: int = 10,
                              capabilities: str = "files,code,github,devops") -> str:
    """Start a coding sub-agent with Kanban tracking and a one-shot follow-up check."""
    import re
    from skills.kanban import create_task, create_task_plan, move_task, update_task
    from skills.cron import create_once_cron

    title = goal.strip()[:80] or "Coding task"
    if checklist.strip():
        task_result = create_task_plan(title, checklist, column="todo")
        task_id_match = re.search(r"id=(\d+)", task_result)
        if task_id_match:
            move_task(int(task_id_match.group(1)), "in_progress")
    else:
        task_result = create_task(title, "Tracked coding task. Background agent will update progress.", "in_progress")
        task_id_match = re.search(r"id=(\d+)", task_result)
    task_id = int(task_id_match.group(1)) if task_id_match else 0

    agent_goal = (
        f"{goal}\n\n"
        "Work autonomously. Keep changes scoped, verify with tests or checks when possible, "
        "and report the exact files changed plus remaining blockers. "
        f"If you use Kanban, update task id {task_id}."
    )
    launched = spawn_subagent(agent_goal, capabilities=capabilities, wait=False)
    agent_match = re.search(r"Sub-agent\s+([a-f0-9]{8})", launched)
    agent_id = agent_match.group(1) if agent_match else ""

    if task_id and agent_id:
        update_task(
            task_id,
            description=(
                "Tracked coding task.\n"
                f"Sub-agent: {agent_id}\n"
                f"Goal: {goal}\n"
                f"Follow-up after: {followup_minutes} minutes"
            ),
        )

    followup = ""
    if agent_id:
        followup_instruction = (
            f"Check sub-agent {agent_id} for coding task '{title}'. "
            f"If it is done, summarize result and move kanban task {task_id} to done if that task exists. "
            f"If it is still running, report current status and schedule another one-shot follow-up in "
            f"{max(5, int(followup_minutes))} minutes using create_once_cron."
        )
        followup = create_once_cron(
            name=f"coding follow-up {agent_id}",
            command=f"@agent: {followup_instruction}",
            delay_minutes=max(1, int(followup_minutes)),
        )

    return (
        "Tracked coding task started.\n"
        f"Kanban:\n{task_result}\n\n"
        f"Sub-agent: {agent_id or launched}\n"
        f"Follow-up:\n{followup or 'No follow-up scheduled.'}"
    )


def cancel_subagent(agent_id: str) -> str:
    """Cancel a running sub-agent by sending it a cancellation signal."""
    with _registry_lock:
        ag = _subagents.get(agent_id)
    if not ag:
        return f"No sub-agent found with id '{agent_id}'."
    ev = ag.get("_cancel")
    if ev:
        ev.set()
        return f"Cancellation signal sent to sub-agent {agent_id}."
    return f"Sub-agent {agent_id} does not support cancellation."



def get_subagent_status(agent_id: str) -> str:
    """Check the status and result of a running or completed sub-agent."""
    with _registry_lock:
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
    with _registry_lock:
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


def subagent_get_result(agent_id: str) -> str:
    """Get the full result/output of a completed sub-agent."""
    with _registry_lock:
        ag = _subagents.get(agent_id)
    if not ag:
        return f"No sub-agent found with id '{agent_id}'."
    if ag["status"] not in ("done", "error"):
        return f"Sub-agent {agent_id} is still running (status: {ag['status']})."
    result = ag.get("result", "") or "(no output)"
    return f"[Sub-agent {agent_id} — {ag['status']}]\n{result}"


def subagent_delete(agent_id: str) -> str:
    """Remove a sub-agent from the registry. The thread continues running if not done."""
    with _registry_lock:
        if agent_id not in _subagents:
            return f"No sub-agent found with id '{agent_id}'."
        ag = _subagents.pop(agent_id)
    from .notifier import SubAgentNotifier
    SubAgentNotifier._notified.discard(agent_id)
    return f"Sub-agent {agent_id} removed from registry (was: {ag['status']})."


def subagent_update(agent_id: str, new_goal: str, provider: str = "",
                    model: str = "", tools: str = "", capabilities: str = "") -> str:
    """Cancel the current sub-agent and spawn a new one with an updated goal."""
    with _registry_lock:
        if agent_id in _subagents:
            old = _subagents.pop(agent_id)
            ev = old.get("_cancel")
            if ev:
                ev.set()
            old_goal = old.get("goal", "")
        else:
            old_goal = ""
    from .notifier import SubAgentNotifier
    SubAgentNotifier._notified.discard(agent_id)
    new_id_info = spawn_subagent(new_goal, provider, model, tools, capabilities, wait=False)
    return f"Old agent {agent_id} ('{old_goal}') replaced.\n{new_id_info}"


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


def extract_project(source: str, dest: str = "", include_koza_core: bool = True) -> str:
    """
    Extract a sub-agent or project folder into a fully standalone, independent project.

    Scans all Python files in the source folder, detects which Koza skills and
    providers are imported, and copies them alongside the project code so the
    result can run without the parent Koza installation.

    Args:
        source: Project/sub-agent name (looked up in workspace/projects/ then
                workspace/subagents/) or an absolute path.
        dest:   Destination path. Defaults to workspace/projects/<source>_standalone/
        include_koza_core: If True (default), copy core Koza framework files
                           (core.py, config.py, prompt.py, providers/, tools/).
    """
    import re
    import shutil
    from pathlib import Path
    from config import load_config

    cfg = load_config()
    koza_root = Path(__file__).resolve().parent.parent.parent  # repo root
    ws = Path(cfg.get("workspace_path", str(Path.home() / ".Koza" / "workspace")))

    # ── Resolve source path ───────────────────────────────────────────────────
    src_path: Path | None = None
    if Path(source).is_absolute() and Path(source).exists():
        src_path = Path(source)
    else:
        for candidate in [
            ws / "projects" / source,
            ws / "subagents" / source,
        ]:
            if candidate.exists():
                src_path = candidate
                break
    if src_path is None:
        return (
            f"❌ Source not found: '{source}'\n"
            f"   Checked: workspace/projects/{source}, workspace/subagents/{source}"
        )

    # ── Resolve destination path ──────────────────────────────────────────────
    safe_name = re.sub(r"[^\w\-]", "_", src_path.name).strip("_") or "extracted"
    dest_path = Path(dest) if dest else ws / "projects" / f"{safe_name}_standalone"
    dest_path.mkdir(parents=True, exist_ok=True)

    # ── Copy project source files ─────────────────────────────────────────────
    proj_dest = dest_path / "app"
    if proj_dest.exists():
        shutil.rmtree(proj_dest)
    shutil.copytree(src_path, proj_dest, dirs_exist_ok=False)

    # ── Scan imports in all project .py files ─────────────────────────────────
    py_files = list(proj_dest.rglob("*.py"))
    all_text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in py_files)

    used_skills: set[str] = set()
    used_providers: set[str] = set()

    # Detect `from skills.X` or `from skills import X` patterns
    for m in re.finditer(r"from\s+skills[.\s]+(\w+)", all_text):
        used_skills.add(m.group(1))
    for m in re.finditer(r"import\s+skills\.(\w+)", all_text):
        used_skills.add(m.group(1))
    # Detect provider patterns
    for m in re.finditer(r"from\s+providers[.\s]+(\w+)", all_text):
        used_providers.add(m.group(1))
    for m in re.finditer(r"import\s+providers\.(\w+)", all_text):
        used_providers.add(m.group(1))

    copied_files: list[str] = []

    if include_koza_core:
        # ── Copy core framework files ─────────────────────────────────────────
        core_files = [
            "core.py", "config.py", "prompt.py", "prompt_loader.py", "router.py",
        ]
        for cf in core_files:
            src_f = koza_root / cf
            if src_f.exists():
                shutil.copy2(src_f, dest_path / cf)
                copied_files.append(cf)

        # ── Copy tools/ directory ─────────────────────────────────────────────
        tools_src = koza_root / "tools"
        if tools_src.exists():
            shutil.copytree(tools_src, dest_path / "tools", dirs_exist_ok=True)
            copied_files.append("tools/")

        # ── Copy providers/ ───────────────────────────────────────────────────
        prov_dest = dest_path / "providers"
        prov_dest.mkdir(exist_ok=True)
        always_prov = ["__init__.py", "base.py", "factory.py", "fallback_provider.py"]
        for pf in always_prov:
            src_f = koza_root / "providers" / pf
            if src_f.exists():
                shutil.copy2(src_f, prov_dest / pf)
        # Copy detected providers
        for pname in used_providers:
            src_f = koza_root / "providers" / f"{pname}.py"
            if src_f.exists():
                shutil.copy2(src_f, prov_dest / f"{pname}.py")
                copied_files.append(f"providers/{pname}.py")
        # Always include all providers if none detected explicitly
        if not used_providers:
            for pf in (koza_root / "providers").glob("*.py"):
                shutil.copy2(pf, prov_dest / pf.name)
            copied_files.append("providers/ (all)")

        # ── Copy skills/ ──────────────────────────────────────────────────────
        skills_dest = dest_path / "skills"
        skills_dest.mkdir(exist_ok=True)
        shutil.copy2(koza_root / "skills" / "__init__.py", skills_dest / "__init__.py")

        # Always copy these core skill files
        always_skills = [
            "shared_memory.py", "working_memory.py", "session_memory.py",
            "shell.py", "filesystem.py",
        ]
        for sf in always_skills:
            src_f = koza_root / "skills" / sf
            if src_f.exists():
                shutil.copy2(src_f, skills_dest / sf)

        # Copy detected skills
        skills_src_dir = koza_root / "skills"
        for sname in used_skills:
            # Could be a file or a package (sub-directory)
            src_f = skills_src_dir / f"{sname}.py"
            src_d = skills_src_dir / sname
            if src_f.exists():
                shutil.copy2(src_f, skills_dest / f"{sname}.py")
                copied_files.append(f"skills/{sname}.py")
            elif src_d.is_dir():
                shutil.copytree(src_d, skills_dest / sname, dirs_exist_ok=True)
                copied_files.append(f"skills/{sname}/")

        # ── Copy prompts/ directory ───────────────────────────────────────────
        prompts_src = koza_root / "prompts"
        if prompts_src.exists():
            shutil.copytree(prompts_src, dest_path / "prompts", dirs_exist_ok=True)
            copied_files.append("prompts/")

    # ── Build requirements.txt ────────────────────────────────────────────────
    # Map skill/module names → pip packages required
    _SKILL_REQS: dict[str, list[str]] = {
        "web":          ["requests", "playwright"],
        "research":     ["requests"],
        "datascience":  ["pandas", "matplotlib", "openpyxl"],
        "media":        ["yt-dlp", "spotipy"],
        "email_skill":  ["requests"],
        "github_skill": ["requests"],
        "security":     ["python-whois"],
        "smarthome":    ["paho-mqtt"],
        "voice":        ["requests"],
        "image_gen":    ["requests", "Pillow"],
        "notes":        ["requests"],
        "social":       ["requests"],
        "finance":      ["requests"],
        "gaming":       ["requests"],
        "devops":       ["docker"],
    }
    _PROVIDER_REQS: dict[str, list[str]] = {
        "openai_provider":    ["openai>=1.30.0"],
        "anthropic_provider": ["anthropic>=0.28.0"],
        "gemini_provider":    ["google-genai>=0.7.0", "google-auth>=2.29.0", "gemini-webapi>=1.0.0"],
        "groq_provider":      ["openai>=1.30.0"],
        "ollama_provider":    ["openai>=1.30.0"],
        "deepseek_provider":  ["openai>=1.30.0"],
        "openrouter_provider":["openai>=1.30.0"],
    }

    base_reqs = ["pyyaml>=6.0.1", "python-dotenv>=1.0.1", "requests>=2.31.0", "psutil>=5.9.8"]
    extra_reqs: set[str] = set()
    for sname in used_skills:
        for req in _SKILL_REQS.get(sname, []):
            extra_reqs.add(req)
    for pname in used_providers:
        key = f"{pname}_provider" if not pname.endswith("_provider") else pname
        for req in _PROVIDER_REQS.get(key, _PROVIDER_REQS.get(pname, [])):
            extra_reqs.add(req)
    if not used_providers:
        # Include all provider deps
        for reqs in _PROVIDER_REQS.values():
            extra_reqs.update(reqs)

    all_reqs = sorted(set(base_reqs) | extra_reqs)
    (dest_path / "requirements.txt").write_text("\n".join(all_reqs) + "\n", encoding="utf-8")

    # ── Write standalone main.py entry point ──────────────────────────────────
    main_py = '''\
"""
Standalone entry point — generated by Koza extract_project.
Run: python main.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from config import load_config
from providers.factory import get_provider
from core import Agent


def main():
    cfg = load_config()
    provider = get_provider(cfg)
    agent = Agent(provider, cfg["db_path"], cfg=cfg)

    print("Agent ready. Type your message (Ctrl+C to quit).")
    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            response = ""
            for event in agent.stream_chat(user_input):
                if event.get("type") == "text":
                    tok = event["token"]
                    print(tok, end="", flush=True)
                    response += tok
            print()
        except KeyboardInterrupt:
            print("\\nBye!")
            break


if __name__ == "__main__":
    main()
'''
    (dest_path / "main.py").write_text(main_py, encoding="utf-8")

    # ── Summary ───────────────────────────────────────────────────────────────
    lines = [
        f"✅ Project extracted to: {dest_path}",
        f"",
        f"  📁 app/              — your project code ({len(py_files)} Python files)",
        f"  📄 main.py           — standalone entry point",
        f"  📄 requirements.txt  — pip dependencies",
    ]
    if include_koza_core:
        lines += [
            f"  📦 skills/           — Koza skills used: {sorted(used_skills) or ['(core only)']}",
            f"  📦 providers/        — providers: {sorted(used_providers) or ['(all)']  }",
            f"  📦 core.py + config.py + prompt.py + tools/",
        ]
    lines += [
        f"",
        f"To run:",
        f"  cd {dest_path}",
        f"  pip install -r requirements.txt",
        f"  python main.py",
    ]
    return "\n".join(lines)


def start_coding_session(goal: str, max_retries: int = 3) -> str:
    """
    Run a multi-persona coding session synchronously and return the final summary.
    Streams persona events to stdout as they happen.
    """
    try:
        from config import load_config
        from skills.agents.coding_mode import CodingSession
    except ImportError as e:
        return f"Coding Mode unavailable: {e}"

    cfg      = load_config()
    db_path  = cfg.get("db_path", str(__import__("pathlib").Path.home() / ".Koza" / "koza.db"))
    session  = CodingSession(cfg, db_path, max_retries=max_retries)
    summary  = ""
    events   = []

    for event in session.run(goal):
        etype = event.get("type", "")
        if etype == "status":
            print(f"\n[{event.get('persona', '?')}] {event.get('message', '')}", flush=True)
        elif etype == "persona_token":
            print(event.get("token", ""), end="", flush=True)
        elif etype == "plan":
            plan = event.get("plan", {})
            tasks = plan.get("tasks", [])
            print(f"\n📋 Plan: {plan.get('title', '')} — {len(tasks)} task(s)", flush=True)
        elif etype == "error_recorded":
            err = event.get("error", {})
            print(f"\n⚠ Error recorded: {err.get('description', '')}", flush=True)
        elif etype == "done":
            summary = event.get("summary", "")
        elif etype == "interrupted":
            return "Coding session was interrupted."
        events.append(event)

    return summary or "Coding session completed."


# ── Tool definitions ──────────────────────────────────────────────────────────


TOOL_DEFINITIONS = [
    {
        "name": "spawn_subagent",
        "description": (
            "Spawn an autonomous background sub-agent to handle a user-requested task. "
            "ONLY use for tasks explicitly requested by the user that benefit from parallelism or isolation. "
            "DO NOT use for: Telegram (use start_telegram_daemon), Cron (use create_cron), Sync (use sync_now). "
            "Use 'capabilities' for named skill bundles (e.g. 'browser,files') instead of listing individual tools."
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
            "ONLY use when the user EXPLICITLY asks to create a new project, app, or codebase. "
            "DO NOT call this spontaneously, for telegram setup, or for any built-in service configuration."
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
        "name": "subagent_get_result",
        "description": "Retrieve the full output of a completed sub-agent.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Sub-agent ID"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "subagent_delete",
        "description": "Remove a finished or failed sub-agent from the registry.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Sub-agent ID"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "subagent_update",
        "description": "Cancel a sub-agent and re-spawn it with a new goal (effectively an update).",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id":     {"type": "string", "description": "Existing sub-agent ID to replace"},
                "new_goal":     {"type": "string", "description": "New goal for the replacement agent"},
                "provider":     {"type": "string", "default": ""},
                "model":        {"type": "string", "default": ""},
                "tools":        {"type": "string", "default": ""},
                "capabilities": {"type": "string", "default": ""},
            },
            "required": ["agent_id", "new_goal"],
        },
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
    {
        "name": "extract_project",
        "description": (
            "Extract a sub-agent or project into a fully standalone, independent project that can run without Koza. "
            "Scans the project's Python files to detect which Koza skills and providers are used, "
            "copies them alongside the project code, generates a filtered requirements.txt, "
            "and writes a main.py entry point. Use after a sub-agent finishes building something "
            "so the user can take it and run it independently."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Project or sub-agent name (looks in workspace/projects/ then workspace/subagents/) or absolute path",
                },
                "dest": {
                    "type": "string",
                    "default": "",
                    "description": "Output path (default: workspace/projects/<name>_standalone/)",
                },
                "include_koza_core": {
                    "type": "boolean",
                    "default": True,
                    "description": "Copy Koza framework files (core.py, providers/, skills/, tools/). Set False to extract only app code.",
                },
            },
            "required": ["source"],
        },
    },
    {
        "name": "cancel_subagent",
        "description": "Send a cancellation signal to a running sub-agent. The agent will stop at the next iteration.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Sub-agent ID to cancel"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "start_coding_session",
        "description": (
            "Start a multi-persona coding session: Team Lead plans, Backend Dev writes code, "
            "Frontend Dev handles UI, Test Engineer runs tests and reports. "
            "Use for complex coding tasks that benefit from structured planning + testing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal":        {"type": "string", "description": "What to build (describe the full requirement)"},
                "max_retries": {"type": "integer", "default": 3,
                                "description": "How many times to retry failed code before giving up"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "start_tracked_coding_task",
        "description": (
            "Start a coding task in the background, create Kanban tracking, and schedule "
            "a one-time follow-up check so long tasks do not appear frozen."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The coding task to complete"},
                "checklist": {"type": "string", "default": "", "description": "Optional newline-separated checklist to create Kanban tasks"},
                "followup_minutes": {"type": "integer", "default": 10, "description": "Minutes until the first automatic status check"},
                "capabilities": {"type": "string", "default": "files,code,github,devops", "description": "Capability groups for the background sub-agent"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "run_swarm",
        "description": (
            "Run a parallel agent swarm to solve a complex task. "
            "Decomposes the task into independent subtasks, runs them concurrently in separate background agents, "
            "and synthesizes the final results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal":         {"type": "string", "description": "The complex task/goal to solve"},
                "capabilities": {"type": "string", "default": "", "description": "Comma-separated default capability groups (e.g. 'files,code')"},
            },
            "required": ["goal"],
        },
    },
]


HANDLERS: dict = {
    "spawn_subagent":       lambda goal, provider="", model="", tools="", capabilities="", wait=True:
                                spawn_subagent(goal, provider, model, tools, capabilities, wait),
    "get_subagent_status":  lambda agent_id: get_subagent_status(agent_id),
    "list_subagents":       lambda **_: list_subagents(),
    "list_capabilities":    lambda **_: list_capabilities(),
    "subagent_get_result":  lambda agent_id: subagent_get_result(agent_id),
    "subagent_delete":      lambda agent_id: subagent_delete(agent_id),
    "subagent_update":      lambda agent_id, new_goal, provider="", model="", tools="", capabilities="":
                                subagent_update(agent_id, new_goal, provider, model, tools, capabilities),
    "cancel_subagent":      lambda agent_id: cancel_subagent(agent_id),
    "start_coding_session": lambda goal, max_retries=3: start_coding_session(goal, int(max_retries)),
    "start_tracked_coding_task": lambda goal, checklist="", followup_minutes=10, capabilities="files,code,github,devops":
                                start_tracked_coding_task(goal, checklist, int(followup_minutes), capabilities),
    "create_project":       lambda name, description="": create_project(name, description),
    "list_projects":        lambda **_: list_projects(),
    "clean_workspace":      lambda scope="all": clean_workspace(scope),
    "extract_project":      lambda source, dest="", include_koza_core=True:
                                extract_project(source, dest, include_koza_core),
    "run_swarm":            lambda goal, capabilities="": run_swarm(goal, capabilities),
}
