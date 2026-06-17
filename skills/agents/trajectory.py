import os
import json
import time
from pathlib import Path

TRAJECTORIES_DIR = Path.home() / ".Koza" / "trajectories"

def convert_messages_to_sharegpt(messages: list[dict], user_input: str) -> list[dict]:
    """Convert raw conversation messages to Hermes-style ShareGPT trajectory format."""
    trajectory = []
    
    # 1. Look for the system prompt or fallback
    system_content = ""
    for msg in messages:
        if msg.get("role") == "system":
            system_content = msg.get("content", "")
            break
    
    if not system_content:
        system_content = "You are a helpful AI assistant with access to tools."
        
    trajectory.append({
        "from": "system",
        "value": system_content
    })
    
    # 2. Add the first human message
    trajectory.append({
        "from": "human",
        "value": user_input
    })
    
    # 3. Process remaining messages (skipping system/first user message)
    # We track if we've seen the first user message to skip it
    seen_first_user = False
    
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue
        if role == "user":
            if not seen_first_user:
                seen_first_user = True
                continue
            trajectory.append({
                "from": "human",
                "value": msg.get("content", "")
            })
        elif role == "assistant":
            value = ""
            # Include reasoning block if present
            reasoning = msg.get("reasoning", "")
            if reasoning and reasoning.strip():
                value += f"<think>\n{reasoning.strip()}\n</think>\n"
            
            content = msg.get("content", "")
            if content and content.strip():
                value += content.strip() + "\n"
                
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    # Normalize tool call arguments
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            pass
                    
                    tc_val = {
                        "name": name,
                        "arguments": args
                    }
                    value += f"<tool_call>\n{json.dumps(tc_val, ensure_ascii=False)}\n</tool_call>\n"
            
            # Ensure every assistant turn starts with a think block for training uniformity
            if "<think>" not in value:
                value = "<think>\n</think>\n" + value
                
            trajectory.append({
                "from": "gpt",
                "value": value.strip()
            })
        elif role == "tool":
            tool_name = msg.get("name", "unknown")
            content = msg.get("content", "")
            val = f"<tool_response>\n{content}\n</tool_response>"
            trajectory.append({
                "from": "tool",
                "name": tool_name,
                "value": val
            })
            
    return trajectory


def record_trajectory(session_id: str, turn_data: dict) -> None:
    """Record a single turn's trajectory (including full ShareGPT history) to a JSONL file."""
    try:
        TRAJECTORIES_DIR.mkdir(parents=True, exist_ok=True)
        file_path = TRAJECTORIES_DIR / f"{session_id}.jsonl"
        
        # Build the ShareGPT conversations trajectory
        messages = turn_data.get("messages", [])
        user_input = turn_data.get("user_input", "")
        
        conversations = convert_messages_to_sharegpt(messages, user_input)
        
        payload = {
            "timestamp": time.time(),
            "elapsed_time": turn_data.get("elapsed_time", 0.0),
            "provider": turn_data.get("provider", "unknown"),
            "model": turn_data.get("model", ""),
            "user_input": user_input,
            "response": turn_data.get("response", ""),
            "conversations": conversations
        }
        
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
