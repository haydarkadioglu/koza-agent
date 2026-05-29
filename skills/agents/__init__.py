"""
Agents package — spawn and manage autonomous sub-agents.
Exports TOOL_DEFINITIONS and HANDLERS for core.py.
"""
import threading
import time
import uuid

from ._registry import _subagents
from .runner import _run_subagent_thread
from .background import BackgroundTaskManager, _background_tasks


def spawn_subagent(goal: str, provider: str = "", model: str = "",
                   tools: str = "", capabilities: str = "",
                   wait: bool = True,
                   profile: str = "") -> str:
    """Spawn a sub-agent with a specific goal. Runs in-process in a thread.
    
    If 'profile' is given, the named agent profile's system prompt and tools are used.
    """
    from tools.capabilities import resolve_capabilities

    system_prompt_override = ""

    # Load named profile if requested
    if profile:
        from skills.shared_memory import memory_recall
        key = f"agent_profile.{profile.lower().strip().replace(' ', '_')}"
        stored = memory_recall(key)
        if "No memory" not in stored:
            import json as _json
            try:
                data = _json.loads(stored)
                system_prompt_override = data.get("role", "")
                # Merge profile tools with explicit tools
                if data.get("tools") and not tools:
                    tools = data["tools"]
            except Exception:
                system_prompt_override = stored  # treat raw value as system prompt

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
        "profile": profile,
    }

    t = threading.Thread(
        target=_run_subagent_thread,
        args=(agent_id, goal, provider, model, tools_filter, system_prompt_override),
        daemon=True,
    )
    t.start()

    profile_note = f" [profile: {profile}]" if profile else ""
    if wait:
        t.join(timeout=180)
        ag     = _subagents[agent_id]
        status = ag["status"]
        result = ag.get("result", "")
        return f"[Sub-agent {agent_id}{profile_note}] {status}\n{result}"
    return f"Sub-agent {agent_id}{profile_note} launched (background). Use get_subagent_status('{agent_id}') to check."


def agent_profile_save(name: str, role: str, tools: str = "", description: str = "") -> str:
    """Save a named agent profile to memory. The profile defines a specialist role
    (system prompt) and optional tool set. Use spawn_subagent(profile='name') to use it."""
    import json as _json
    from skills.shared_memory import memory_store
    key = f"agent_profile.{name.lower().strip().replace(' ', '_')}"
    data = {"name": name, "role": role, "tools": tools, "description": description}
    memory_store(key, _json.dumps(data), tags="agent_profile", source="user")
    return f"✅ Agent profile '{name}' saved. Use: spawn_subagent(goal='...', profile='{name}')"


def agent_profile_list() -> str:
    """List all saved agent profiles."""
    from skills.shared_memory import memory_list
    result = memory_list(tags="agent_profile", limit=30)
    return result


def agent_profile_delete(name: str) -> str:
    """Delete a named agent profile."""
    from skills.shared_memory import memory_delete
    key = f"agent_profile.{name.lower().strip().replace(' ', '_')}"
    return memory_delete(key)


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


def subagent_get_result(agent_id: str) -> str:
    """Get the full result/output of a completed sub-agent."""
    ag = _subagents.get(agent_id)
    if not ag:
        return f"No sub-agent found with id '{agent_id}'."
    if ag["status"] not in ("done", "error"):
        return f"Sub-agent {agent_id} is still running (status: {ag['status']})."
    result = ag.get("result", "") or "(no output)"
    return f"[Sub-agent {agent_id} — {ag['status']}]\n{result}"


def subagent_delete(agent_id: str) -> str:
    """Remove a sub-agent from the registry. The thread continues running if not done."""
    if agent_id not in _subagents:
        return f"No sub-agent found with id '{agent_id}'."
    ag = _subagents.pop(agent_id)
    from .notifier import SubAgentNotifier
    SubAgentNotifier._notified.discard(agent_id)
    return f"Sub-agent {agent_id} removed from registry (was: {ag['status']})."


def subagent_update(agent_id: str, new_goal: str, provider: str = "",
                    model: str = "", tools: str = "", capabilities: str = "") -> str:
    """Cancel the current sub-agent and spawn a new one with an updated goal."""
    if agent_id in _subagents:
        old = _subagents.pop(agent_id)
        from .notifier import SubAgentNotifier
        SubAgentNotifier._notified.discard(agent_id)
        old_goal = old.get("goal", "")
    else:
        old_goal = ""
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


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "spawn_subagent",
        "description": (
            "Spawn an autonomous background sub-agent to handle a user-requested task. "
            "ONLY use for tasks explicitly requested by the user that benefit from parallelism or isolation. "
            "DO NOT use for: Telegram (use start_telegram_daemon), Cron (use create_cron), Sync (use sync_now). "
            "Use 'capabilities' for named skill bundles (e.g. 'browser,files') instead of listing individual tools. "
            "If the user has a saved agent profile for this type of task, use 'profile' to load it automatically."
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
                "profile":      {"type": "string",  "default": "", "description": "Named agent profile to use (see agent_profile_list). Loads the profile's role (system prompt) and default tools."},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "agent_profile_save",
        "description": (
            "Save a named specialist agent profile with a custom system prompt (role) and optional tool set. "
            "After saving, use spawn_subagent(goal='...', profile='name') to reuse this specialist in future tasks. "
            "Example: save a 'code_reviewer' profile with a strict code review role."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "Profile name (e.g. 'code_reviewer', 'data_analyst')"},
                "role":        {"type": "string", "description": "System prompt / role description for this specialist agent"},
                "tools":       {"type": "string", "default": "", "description": "Comma-separated tool names this agent should have (empty = all)"},
                "description": {"type": "string", "default": "", "description": "Human-readable description of what this profile does"},
            },
            "required": ["name", "role"],
        },
    },
    {
        "name": "agent_profile_list",
        "description": "List all saved named agent profiles. Check this before spawning a sub-agent to see if a matching specialist profile exists.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_profile_delete",
        "description": "Delete a saved agent profile by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Profile name to delete"},
            },
            "required": ["name"],
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
]

HANDLERS: dict = {
    "spawn_subagent":      lambda goal, provider="", model="", tools="", capabilities="", wait=True, profile="":
                               spawn_subagent(goal, provider, model, tools, capabilities, wait, profile),
    "get_subagent_status": lambda agent_id: get_subagent_status(agent_id),
    "list_subagents":      lambda **_: list_subagents(),
    "list_capabilities":   lambda **_: list_capabilities(),
    "subagent_get_result": lambda agent_id: subagent_get_result(agent_id),
    "subagent_delete":     lambda agent_id: subagent_delete(agent_id),
    "subagent_update":     lambda agent_id, new_goal, provider="", model="", tools="", capabilities="":
                               subagent_update(agent_id, new_goal, provider, model, tools, capabilities),
    "create_project":      lambda name, description="": create_project(name, description),
    "list_projects":       lambda **_: list_projects(),
    "clean_workspace":     lambda scope="all": clean_workspace(scope),
    "extract_project":     lambda source, dest="", include_koza_core=True:
                               extract_project(source, dest, include_koza_core),
    "agent_profile_save":  lambda name, role, tools="", description="":
                               agent_profile_save(name, role, tools, description),
    "agent_profile_list":  lambda **_: agent_profile_list(),
    "agent_profile_delete": lambda name: agent_profile_delete(name),
}
