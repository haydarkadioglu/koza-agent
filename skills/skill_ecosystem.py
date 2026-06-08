"""Skill Ecosystem — reusable task templates that Koza can save, load, and execute.

Skills are structured task templates saved as JSON files in ~/.Koza/skills/.
Each skill has: name, description, steps (ordered list of actions), tags, and context notes.
Koza can create skills from successful work, list available skills, load them into context,
and use them as templates for similar future tasks.

This is distinct from the tools/skills/ modules — those are Python handler modules.
This is about learnable, reusable task procedures that persist across sessions.
"""
import json
import os
import time
from pathlib import Path
from typing import Any

_SKILLS_DIR: Path = Path.home() / ".Koza" / "skill_templates"


def _ensure_dir() -> None:
    _SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def _skill_path(name: str) -> Path:
    safe = name.lower().replace(" ", "-").replace("_", "-")
    safe = "".join(c for c in safe if c.isalnum() or c in "-.")
    return _SKILLS_DIR / f"{safe}.json"


def skill_save(name: str, description: str, steps: list, tags: str = "",
               context: str = "") -> str:
    """Save a reusable skill template. Steps is a list of action descriptions."""
    _ensure_dir()
    skill = {
        "name": name,
        "description": description,
        "steps": steps,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "context": context,
        "created": time.time(),
        "updated": time.time(),
        "use_count": 0,
    }
    path = _skill_path(name)
    path.write_text(json.dumps(skill, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"✅ Skill saved: '{name}' ({len(steps)} steps, tags: {tags or 'none'})"


def skill_load(name: str) -> str:
    """Load a skill template content into a readable format for the agent."""
    _ensure_dir()
    path = _skill_path(name)
    if not path.exists():
        # Try fuzzy match
        matches = list(_SKILLS_DIR.glob("*.json"))
        for m in matches:
            if name.lower() in m.stem.lower():
                path = m
                break
        else:
            return f"❌ Skill '{name}' not found. Use skill_list() to see available skills."
    try:
        skill = json.loads(path.read_text(encoding="utf-8"))
        # Increment use count
        skill["use_count"] = skill.get("use_count", 0) + 1
        skill["updated"] = time.time()
        path.write_text(json.dumps(skill, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return f"❌ Error loading skill '{name}'."
    return _format_skill(skill)


def _format_skill(skill: dict) -> str:
    """Format a skill for display/context injection."""
    lines = [
        f"📋 Skill: {skill['name']}",
        f"   {skill['description']}",
    ]
    tags = skill.get("tags", [])
    if tags:
        lines.append(f"   Tags: {', '.join(tags)}")
    lines.append("")
    steps = skill.get("steps", [])
    for i, step in enumerate(steps, 1):
        lines.append(f"  {i}. {step}")
    ctx = skill.get("context", "")
    if ctx:
        lines.append(f"\n  Context: {ctx}")
    return "\n".join(lines)


def skill_list(tag: str = "") -> str:
    """List available skills, optionally filtered by tag."""
    _ensure_dir()
    skills = []
    for path in sorted(_SKILLS_DIR.glob("*.json")):
        try:
            skill = json.loads(path.read_text(encoding="utf-8"))
            if tag:
                if tag.lower() not in [t.lower() for t in skill.get("tags", [])]:
                    continue
            skills.append(skill)
        except Exception:
            continue
    if not skills:
        return "No skills saved yet. Use skill_save() to create one."
    lines = [f"📚 Skill Library ({len(skills)} skills):\n"]
    for s in skills:
        tags = f" [{', '.join(s.get('tags', []))}]" if s.get("tags") else ""
        uses = s.get("use_count", 0)
        lines.append(f"  📌 {s['name']}{tags} — {s['description'][:80]} ({uses}x)")
    return "\n".join(lines)


def skill_delete(name: str) -> str:
    """Delete a saved skill template."""
    _ensure_dir()
    path = _skill_path(name)
    if path.exists():
        path.unlink()
        return f"✅ Skill '{name}' deleted."
    # Fuzzy match
    for m in _SKILLS_DIR.glob("*.json"):
        if name.lower() in m.stem.lower():
            m.unlink()
            return f"✅ Skill '{m.stem}' deleted."
    return f"❌ Skill '{name}' not found."


def skill_get_context(names: list[str]) -> str:
    """Load multiple skills and return a compact context string for prompt injection."""
    parts = []
    for name in names:
        path = _skill_path(name)
        if not path.exists():
            for m in _SKILLS_DIR.glob("*.json"):
                if name.lower() in m.stem.lower():
                    path = m
                    break
        if path.exists():
            try:
                skill = json.loads(path.read_text(encoding="utf-8"))
                parts.append(f"## Skill: {skill['name']}\n{skill['description']}")
                steps = skill.get("steps", [])
                for i, step in enumerate(steps, 1):
                    parts.append(f"{i}. {step}")
            except Exception:
                continue
    return "\n".join(parts) if parts else ""


def enable_core_skill(skill_id: str) -> str:
    """Dynamically enable a core built-in skill/toolset (e.g. 'browser_control', 'finance', 'github_skill', etc.) so its tools become available in the next turns."""
    from config import load_config, save_config
    from tools.registry import rebuild_registry, STATIC_SKILL_MODULES
    
    if skill_id not in STATIC_SKILL_MODULES:
        return f"❌ Skill '{skill_id}' is not a valid built-in skill. Valid choices: {list(STATIC_SKILL_MODULES.keys())}"
        
    cfg = load_config()
    disabled = cfg.get("disabled_skills", [])
    if skill_id in disabled:
        disabled.remove(skill_id)
        cfg["disabled_skills"] = disabled
        save_config(cfg)
        rebuild_registry()
        return f"✅ Skill '{skill_id}' has been successfully enabled. Its tools are now available for your next calls."
    else:
        return f"ℹ️ Skill '{skill_id}' was already enabled."


def disable_core_skill(skill_id: str) -> str:
    """Disable a core built-in skill/toolset so its tools are removed from your next turns."""
    from config import load_config, save_config
    from tools.registry import rebuild_registry, STATIC_SKILL_MODULES
    
    if skill_id not in STATIC_SKILL_MODULES:
        return f"❌ Skill '{skill_id}' is not a valid built-in skill. Valid choices: {list(STATIC_SKILL_MODULES.keys())}"
        
    cfg = load_config()
    disabled = cfg.get("disabled_skills", [])
    if skill_id not in disabled:
        disabled.append(skill_id)
        cfg["disabled_skills"] = disabled
        save_config(cfg)
        rebuild_registry()
        return f"⏹️ Skill '{skill_id}' has been disabled."
    else:
        return f"ℹ️ Skill '{skill_id}' was already disabled."


def list_core_skills() -> str:
    """List all available core built-in skills, indicating which ones are currently enabled or disabled."""
    from config import load_config
    from tools.registry import STATIC_SKILL_MODULES
    
    cfg = load_config()
    disabled = cfg.get("disabled_skills", [])
    
    lines = ["Core Built-in Skills Status:"]
    for s_id in sorted(STATIC_SKILL_MODULES.keys()):
        status = "DISABLED" if s_id in disabled else "ENABLED"
        lines.append(f"  - {s_id}: {status}")
    return "\n".join(lines)


# ─── Tool definitions ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "skill_save",
        "description": (
            "Save a reusable skill template from completed work. "
            "Call this after successfully completing a multi-step task so Koza "
            "can reuse the approach in future sessions. Include clear steps, "
            "tags for categorization, and context notes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "Short descriptive name (e.g. 'react-website', 'port-scan', 'kanban-setup')"},
                "description": {"type": "string", "description": "What this skill does"},
                "steps":       {"type": "array", "items": {"type": "string"}, "description": "Ordered list of action steps"},
                "tags":        {"type": "string", "description": "Comma-separated tags (e.g. 'web,react,frontend')", "default": ""},
                "context":     {"type": "string", "description": "Optional context or prerequisites", "default": ""},
            },
            "required": ["name", "description", "steps"],
        },
    },
    {
        "name": "skill_load",
        "description": "Load a saved skill template. Returns the full skill content including all steps.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name to load"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "skill_list",
        "description": "List all available skill templates, optionally filtered by tag.",
        "parameters": {
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "Optional tag to filter by", "default": ""},
            },
        },
    },
    {
        "name": "skill_delete",
        "description": "Delete a saved skill template.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name to delete"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "enable_core_skill",
        "description": "Dynamically enable a core built-in skill/toolset (e.g. 'browser_control', 'finance', 'github_skill', etc.) so its tools become available in the next turns.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "The ID of the built-in skill (e.g. 'browser_control', 'finance', 'github_skill', 'cron', 'creative', 'datascience', 'devops', 'email_skill', 'gaming', 'mcp_skill', 'media', 'mlops', 'productivity', 'research', 'security', 'smarthome', 'social', 'messaging', 'sync', 'vision')"},
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "disable_core_skill",
        "description": "Disable a core built-in skill/toolset so its tools are removed from your next turns.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "The ID of the built-in skill to disable"},
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "list_core_skills",
        "description": "List all available core built-in skills, indicating which ones are currently enabled or disabled.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]

HANDLERS: dict = {
    "skill_save":   lambda name, description, steps, tags="", context="": skill_save(name, description, steps, tags, context),
    "skill_load":   lambda name: skill_load(name),
    "skill_list":   lambda tag="": skill_list(tag),
    "skill_delete": lambda name: skill_delete(name),
    "enable_core_skill":  lambda skill_id: enable_core_skill(skill_id),
    "disable_core_skill": lambda skill_id: disable_core_skill(skill_id),
    "list_core_skills":   lambda: list_core_skills(),
}
