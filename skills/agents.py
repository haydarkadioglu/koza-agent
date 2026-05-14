"""Autonomous AI Agents skill — spawn sub-agents."""
import subprocess
import sys
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "spawn_agent",
            "description": (
                "Spawn a sub-agent (another Hermes instance) to handle a task autonomously. "
                "Returns the agent's final output. Good for parallelizing complex tasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Task for the sub-agent"},
                    "provider": {"type": "string", "default": "", "description": "Override provider (e.g. ollama)"},
                    "model": {"type": "string", "default": "", "description": "Override model"},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_hermes_task",
            "description": "Run a single Hermes agent task in no-TUI mode and capture the output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "timeout": {"type": "integer", "default": 60},
                },
                "required": ["task"],
            },
        },
    },
]

# Lazy imports to avoid circular dependency
def spawn_agent(prompt: str, provider: str = "", model: str = "") -> str:
    """Spawn a Hermes sub-agent via subprocess."""
    try:
        cmd = [sys.executable, "main.py", "--no-tui"]
        if provider:
            cmd += ["--provider", provider]
        if model:
            cmd += ["--model", model]

        # Pass prompt via stdin
        result = subprocess.run(
            cmd,
            input=f"{prompt}\nexit\n",
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip()
        # Strip "You: " / "Hermes: " prompts from output
        lines = [l for l in output.splitlines() if not l.startswith("You:") and l.strip()]
        return "\n".join(lines) or "(no output)"
    except subprocess.TimeoutExpired:
        return "Sub-agent timed out."
    except Exception as e:
        return f"ERROR spawning agent: {e}"


def run_hermes_task(task: str, timeout: int = 60) -> str:
    return spawn_agent(task, timeout=timeout)


HANDLERS = {"spawn_agent": spawn_agent, "run_hermes_task": run_hermes_task}
