"""Self-Evolution Loop — analyze conversation log and update memories or skill templates."""
import logging
import time

from config import load_config
from providers.factory import get_provider
from skills.shared_memory import TOOL_DEFINITIONS as MEM_TOOLS, HANDLERS as MEM_HANDLERS
from skills.skill_ecosystem import TOOL_DEFINITIONS as SKILL_TOOLS, HANDLERS as SKILL_HANDLERS

logger = logging.getLogger(__name__)

COMBINED_REVIEW_PROMPT = """Review the conversation above and update two things:

**Memory**: who the user is. Did the user reveal persona, desires, preferences, personal details, or expectations about how you should behave? Save facts about the user and durable preferences with the `memory_store` tool.

**Skills**: how to do this class of task. Be ACTIVE — most sessions produce at least one skill update, even if small. If a new technique, fix, workaround, or debugging path emerged, or if you got corrected on a sequence of steps, tone, or format, encode this as a reusable skill using `skill_save`.
A skill should have:
- name: short-hyphenated-name (e.g. 'npm-install-fix', 'react-routing')
- description: what class of task it solves and when to load it
- steps: ordered list of action steps / workflow to follow
- tags: comma-separated tags

If genuinely nothing stands out on either, say 'Nothing to save.' and stop — but do not default to this conclusion if there is learning potential.
"""


def run_self_improvement(db_path: str, messages_snapshot: list[dict], model_override: str = None) -> str:
    """Analyze conversation history snapshot and update memories or skills."""
    cfg = load_config()
    if model_override:
        cfg["model"] = model_override
    
    # Initialize the provider
    prov = get_provider(cfg)
    
    # Filter tools to only memory & skill ecosystem
    from tools.registry import _normalize
    tools = _normalize(MEM_TOOLS + SKILL_TOOLS)
    handlers = {**MEM_HANDLERS, **SKILL_HANDLERS}
    
    # Set up message history for review
    messages = list(messages_snapshot)
    
    # Prepend quiet system instruction
    system_msg = {
        "role": "system",
        "content": "You are the Koza self-improvement agent. Your task is to analyze the conversation history and update the shared memory or skill templates if needed. You only have access to memory and skill tools."
    }
    
    if messages and messages[0].get("role") == "system":
        messages[0] = system_msg
    else:
        messages.insert(0, system_msg)
        
    # Append the combined review instruction prompt
    messages.append({
        "role": "user",
        "content": COMBINED_REVIEW_PROMPT + "\n\nYou can only call memory and skill management tools. Other tools will be denied at runtime — do not attempt them."
    })
    
    # Run the quiet tool loop
    max_iter = 5
    actions = []
    
    for iteration in range(max_iter):
        try:
            response = prov.chat(messages, tools=tools)
        except Exception as e:
            logger.error("Self-improvement turn error: %s", e)
            break
            
        content = response.get("content")
        tool_calls = response.get("tool_calls")
        
        if not tool_calls:
            if content:
                messages.append({"role": "assistant", "content": content})
            break
            
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        
        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("arguments", {})
            handler = handlers.get(name)
            
            if handler:
                try:
                    res = handler(**args)
                    # Record actions
                    if name == "memory_store":
                        actions.append(f"Memory updated ({args.get('key')})")
                    elif name == "skill_save":
                        actions.append(f"Skill saved ({args.get('name')})")
                    elif name == "skill_delete":
                        actions.append(f"Skill deleted ({args.get('name')})")
                except Exception as e:
                    res = f"Error: {e}"
            else:
                res = f"Unknown tool: {name}"
                
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", name),
                "name": name,
                "content": str(res)
            })
            
    if not actions:
        return "Nothing to save."
        
    return " · ".join(dict.fromkeys(actions))
