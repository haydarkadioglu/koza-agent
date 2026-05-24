"""
Koza system prompt — modular sections to save tokens.

CORE_PROMPT  : always sent (identity + core rules, ~300 tokens)
PROMPT_SECTIONS : keyword-triggered sections sent only when relevant
"""

from prompt_loader import PromptLoader

# ── Initialize loader ─────────────────────────────────────────────────────────
_loader = PromptLoader()

# ── Always-sent core ──────────────────────────────────────────────────────────
CORE_PROMPT: str = _loader.load("core/system.md")

# ── Optional sections — loaded dynamically from prompts/sections/ ─────────────
PROMPT_SECTIONS: dict[str, str] = {
    name: "\n" + _loader.load_section(name)
    for name in _loader.list_sections()
}

# ── Channel-specific context prompts ─────────────────────────────────────────
# Loaded dynamically from prompts/channels/
CHANNEL_PROMPTS: dict[str, str] = {}
for _channel_name in ["telegram", "discord", "whatsapp", "cli"]:
    _channel_content = _loader.load_channel(_channel_name)
    if _channel_content is not None:
        CHANNEL_PROMPTS[_channel_name] = "\n" + _channel_content

# ── Keyword → section name mapping ───────────────────────────────────────────
_SECTION_KEYWORDS: dict[str, list[str]] = {
    "workspace":  ["project", "build", "create app", "create project", "workspace", "script", "write code"],
    "code":       ["python", "code", "script", "execute", "jupyter", "pandas", "install", "package", "run"],
    "web":        ["search", "google", "url", "website", "fetch", "browse", "find info", "research", "linkedin"],
    "shell":      ["run", "command", "terminal", "powershell", "bash", "cmd", "shell"],
    "memory":     ["remember", "forget", "recall", "memory", "store", "save fact"],
    "agent":      ["agent", "subagent", "parallel", "spawn", "sub-agent"],
    "security":   ["port", "ssl", "whois", "scan", "security", "pentest", "hack"],
    "devops":     ["docker", "container", "git", "webhook", "deploy", "ci"],
    "background": ["background", "background task", "coding task", "delegate", "long running",
                   "write", "build", "create", "implement", "fix", "refactor", "develop",
                   "add", "modify", "update", "generate", "code"],
}


def build_system_prompt(user_input: str = "", extra_context: str = "", channel: str = "") -> str:
    """
    Build the system prompt by combining CORE_PROMPT with only the sections
    relevant to the user's message. Falls back to all sections if input is empty.

    Args:
        user_input:     The user's latest message (used for keyword matching).
        extra_context:  Working memory / cwd context injected by the agent.
        channel:        Channel identifier ("telegram", "discord", "whatsapp", "cli").
    """
    lower = user_input.lower()
    matched: set[str] = set()

    for section_name, keywords in _SECTION_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            matched.add(section_name)

    # If very short input or no match, add workspace + code as sensible defaults
    if not matched or len(user_input.strip()) < 10:
        matched.update({"workspace", "code"})

    sections = "".join(PROMPT_SECTIONS[s] for s in matched if s in PROMPT_SECTIONS)
    base = CORE_PROMPT + sections

    # Inject channel-specific context
    if channel and channel in CHANNEL_PROMPTS:
        base += CHANNEL_PROMPTS[channel]

    if extra_context:
        base = base + "\n\n" + extra_context

    return base


# Legacy alias — kept so anything importing SYSTEM_PROMPT still works
SYSTEM_PROMPT = CORE_PROMPT
