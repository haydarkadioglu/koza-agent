"""Single source of truth for slash commands on every surface (CLI, TUI, bot)."""
from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass

SURFACES = ("cli", "tui", "bot")

_USAGE_WIDTH = 26
_MAX_ECHO = 40


@dataclass(frozen=True)
class SlashCommand:
    name: str
    usage: str
    description: str
    aliases: tuple[str, ...] = ()
    surfaces: tuple[str, ...] = ("cli",)


COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("help", "/help", "Show this help", aliases=("?",), surfaces=("cli", "tui", "bot")),
    SlashCommand("sessions", "/sessions", "Browse / load / delete saved sessions", surfaces=("cli", "tui")),
    SlashCommand("save", "/save [title]", "Save current session", surfaces=("cli", "tui")),
    SlashCommand("title", "/title [name]", "Rename current session"),
    SlashCommand("clear", "/clear", "Refresh screen from recent history"),
    SlashCommand("retry", "/retry", "Resend last message"),
    SlashCommand("undo", "/undo", "Remove last exchange"),
    SlashCommand("history", "/history", "Show recent conversation"),
    SlashCommand("provider", "/provider", "Switch LLM provider", surfaces=("cli", "tui")),
    SlashCommand("model", "/model [name]", "Show or change model"),
    SlashCommand("kanban", "/kanban", "Show Kanban board & cron jobs"),
    SlashCommand("memory", "/memory", "Show working memory", surfaces=("cli", "tui")),
    SlashCommand("tools", "/tools", "List available tool groups"),
    SlashCommand("plugins", "/plugins", "List installed plugins"),
    SlashCommand("plugin", "/plugin create <name> [desc]", "Create a new plugin template"),
    SlashCommand("skills", "/skills", "List saved skills"),
    SlashCommand("compress", "/compress", "Compress conversation context"),
    SlashCommand("reset", "/reset", "Clear conversation history", surfaces=("cli", "tui")),
    SlashCommand("mode", "/mode [coding|off]", "Activate or leave coding mode"),
    SlashCommand("swarm", "/swarm <goal>", "Run a multi-agent swarm on a goal"),
    SlashCommand("self-improve", "/self-improve", "Review recent context and save learnings"),
    SlashCommand("google-login", "/google-login", "Sign in with Google"),
    SlashCommand("anthropic-login", "/anthropic-login", "Sign in with Anthropic", aliases=("claude-login",)),
    SlashCommand("codex-login", "/codex-login", "Sign in with Codex"),
    SlashCommand("email-setup", "/email-setup", "Configure email access"),
    SlashCommand("email-log", "/email-log", "Show recent email activity"),
    SlashCommand("load", "/load <id>", "Load a saved session", surfaces=("tui",)),
    SlashCommand("tasks", "/tasks", "Switch to the Tasks tab", surfaces=("tui",)),
    SlashCommand("agents", "/agents", "Switch to the Agents tab", surfaces=("tui",)),
    SlashCommand("tracked", "/tracked <goal>", "Start a tracked coding task", surfaces=("tui",)),
    SlashCommand("once", "/once <minutes> <instruction>", "Schedule one one-shot @agent follow-up", surfaces=("tui",)),
    SlashCommand("status", "/status", "Refresh dashboard panels", surfaces=("tui",)),
    SlashCommand("exit", "/exit", "Quit Koza", aliases=("quit",)),
)


def _on_surface(cmd: SlashCommand, surface: str | None) -> bool:
    return surface is None or surface in cmd.surfaces


def _token(text) -> str:
    """Return the lower-cased command word of ``text`` without its leading slash."""
    if not isinstance(text, str):
        return ""
    parts = text.strip().split(None, 1)
    if not parts:
        return ""
    return parts[0][1:].lower() if parts[0].startswith("/") else parts[0].lower()


def looks_like_slash_command(text) -> bool:
    """True when ``text`` is plausibly a slash command rather than prose or a path.

    A pasted path (``/etc/hosts is broken``) must keep going to the model, so the
    command word is restricted to one short token of letters, digits, ``_`` and ``-``
    and may not contain a second slash.
    """
    if not isinstance(text, str):
        return False
    first = text.strip().split(None, 1)[0] if text.strip() else ""
    if not first.startswith("/") or len(first) < 2 or len(first) > 33:
        return False
    return all(ch.isalnum() or ch in "_-?" for ch in first[1:])


def find_command(text: str, surface: str | None = None) -> SlashCommand | None:
    token = _token(text)
    if not token:
        return None
    for cmd in COMMANDS:
        if (token == cmd.name or token in cmd.aliases) and _on_surface(cmd, surface):
            return cmd
    return None


def is_known_command(text: str, surface: str | None = None) -> bool:
    return find_command(text, surface) is not None


def command_names(surface: str | None = None, include_aliases: bool = False) -> list[str]:
    names: set[str] = set()
    for cmd in COMMANDS:
        if _on_surface(cmd, surface):
            names.add(cmd.name)
            if include_aliases:
                names.update(cmd.aliases)
    return sorted(names)


def completion_candidates(prefix: str, surface: str | None = None) -> list[str]:
    if not isinstance(prefix, str):
        return []
    p = prefix.strip().lower()
    bare = p.removeprefix("/")
    return sorted(
        cmd.usage for cmd in COMMANDS
        if _on_surface(cmd, surface)
        and (cmd.usage.lower().startswith(p) or cmd.name.startswith(bare))
    )


def suggest_command(text: str, surface: str | None = None, max_suggestions: int = 3) -> list[str]:
    token = _token(text)
    if not token or max_suggestions < 1:
        return []
    matches = difflib.get_close_matches(token, command_names(surface), n=max_suggestions)
    return ["/" + m for m in matches]


def help_rows(surface: str = "cli", translate: Callable[[str], str] | None = None) -> list[tuple[str, str]]:
    rows = []
    for cmd in COMMANDS:
        if _on_surface(cmd, surface):
            desc = translate(cmd.description) if callable(translate) else cmd.description
            rows.append((cmd.usage, desc))
    return rows


def help_text(surface: str = "cli", translate: Callable[[str], str] | None = None) -> str:
    return "\n".join(
        f"{usage:<{_USAGE_WIDTH}}  {desc}" for usage, desc in help_rows(surface, translate)
    )


def hint_text(surface: str = "cli") -> str:
    return "Commands: " + " ".join(usage for usage, _ in help_rows(surface))


def unknown_command_message(text: str, surface: str = "cli") -> str:
    raw = text.strip().split(None, 1)[0] if isinstance(text, str) and text.strip() else ""
    shown = raw[:_MAX_ECHO] + ("…" if len(raw) > _MAX_ECHO else "")
    msg = f"Unknown command: {shown}."
    suggestions = suggest_command(text, surface)
    if suggestions:
        msg += f" Did you mean {suggestions[0]}?"
    return msg + " Type /help for the full list."
