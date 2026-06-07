import os
import json
import time
from pathlib import Path

TRAJECTORIES_DIR = Path.home() / ".Koza" / "trajectories"

def record_trajectory(session_id: str, turn_data: dict) -> None:
    """Record a single turn's trajectory to a JSONL file in ~/.Koza/trajectories/."""
    try:
        TRAJECTORIES_DIR.mkdir(parents=True, exist_ok=True)
        file_path = TRAJECTORIES_DIR / f"{session_id}.jsonl"
        
        payload = {
            "timestamp": time.time(),
            **turn_data
        }
        
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass
