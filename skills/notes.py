"""Note-taking skill — Obsidian vault and local Markdown notes."""
from pathlib import Path
import os
import re

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "note_create",
            "description": "Create a new Markdown note in the vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "tags": {"type": "string", "default": "", "description": "Comma-separated tags"},
                    "folder": {"type": "string", "default": "", "description": "Subfolder within vault"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_search",
            "description": "Search notes in the vault by title or content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "search_content": {"type": "boolean", "default": True},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_read",
            "description": "Read a note by filename or title.",
            "parameters": {
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_list",
            "description": "List all notes in the vault.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "default": ""},
                    "tag": {"type": "string", "default": ""},
                },
                "required": [],
            },
        },
    },
]

_vault_path: str = ""


def init_notes(vault_path: str):
    global _vault_path
    _vault_path = vault_path or str(Path.home() / "Notes")
    Path(_vault_path).mkdir(parents=True, exist_ok=True)


def _vault() -> Path:
    return Path(_vault_path or str(Path.home() / "Notes"))


def note_create(title: str, content: str, tags: str = "", folder: str = "") -> str:
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        frontmatter = "---\n"
        frontmatter += f"title: {title}\n"
        if tag_list:
            frontmatter += f"tags: [{', '.join(tag_list)}]\n"
        frontmatter += f"created: {__import__('datetime').datetime.now().isoformat()[:19]}\n"
        frontmatter += "---\n\n"
        full_content = frontmatter + content
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", title)
        target_dir = _vault() / folder if folder else _vault()
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{safe_title}.md"
        path.write_text(full_content, encoding="utf-8")
        return f"Note created: {path}"
    except Exception as e:
        return f"ERROR: {e}"


def note_search(query: str, search_content: bool = True) -> str:
    try:
        vault = _vault()
        q = query.lower()
        results = []
        for md in vault.rglob("*.md"):
            if q in md.stem.lower():
                results.append(("title", md))
            elif search_content:
                try:
                    if q in md.read_text(encoding="utf-8").lower():
                        results.append(("content", md))
                except Exception:
                    pass
        if not results:
            return "No notes found."
        lines = []
        for match_type, path in results[:20]:
            rel = path.relative_to(vault)
            lines.append(f"[{match_type}] {rel}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


def note_read(filename: str) -> str:
    try:
        vault = _vault()
        if not filename.endswith(".md"):
            filename += ".md"
        for md in vault.rglob(filename):
            return md.read_text(encoding="utf-8")
        return f"Note not found: {filename}"
    except Exception as e:
        return f"ERROR: {e}"


def note_list(folder: str = "", tag: str = "") -> str:
    try:
        vault = _vault()
        base = vault / folder if folder else vault
        notes = sorted(base.rglob("*.md"))
        if not notes:
            return "No notes found."
        lines = []
        for md in notes[:50]:
            rel = md.relative_to(vault)
            if tag:
                content = md.read_text(encoding="utf-8")
                if tag.lower() not in content.lower():
                    continue
            lines.append(f"📝 {rel}")
        return "\n".join(lines) if lines else "No matching notes."
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {"note_create": note_create, "note_search": note_search, "note_read": note_read, "note_list": note_list}
