import os
import time
from typing import Dict, Any, List

def init_hands_skill():
    try:
        import pyautogui
        # Fail-safe allows moving mouse to corners to abort
        pyautogui.FAILSAFE = True
    except ImportError:
        pass

def handle_hands_command(action: str, params: Dict[str, Any]) -> str:
    """Execute a GUI interaction command using pyautogui."""
    try:
        import pyautogui
    except ImportError:
        return "Error: pyautogui is not installed. Please run 'pip install pyautogui'."

    try:
        if action == "mouse_move":
            x, y = params.get("x"), params.get("y")
            duration = params.get("duration", 0.2)
            if x is None or y is None:
                return "Error: x and y coordinates are required for mouse_move."
            pyautogui.moveTo(int(x), int(y), duration=duration)
            return f"Mouse moved to ({x}, {y})"

        elif action == "mouse_click":
            button = params.get("button", "left")
            clicks = params.get("clicks", 1)
            pyautogui.click(button=button, clicks=clicks)
            return f"Mouse clicked {clicks} times with {button} button"

        elif action == "mouse_drag":
            x, y = params.get("x"), params.get("y")
            duration = params.get("duration", 0.5)
            button = params.get("button", "left")
            if x is None or y is None:
                return "Error: x and y coordinates are required for mouse_drag."
            pyautogui.dragTo(int(x), int(y), duration=duration, button=button)
            return f"Mouse dragged to ({x}, {y}) using {button} button"

        elif action == "keyboard_type":
            text = params.get("text", "")
            interval = params.get("interval", 0.05)
            pyautogui.write(text, interval=interval)
            return f"Typed text: {text}"

        elif action == "keyboard_press":
            keys = params.get("keys", [])
            if isinstance(keys, str):
                keys = [keys]
            if not keys:
                return "Error: no keys provided to press."
            
            if len(keys) > 1:
                pyautogui.hotkey(*keys)
                return f"Pressed hotkey: {' + '.join(keys)}"
            else:
                pyautogui.press(keys[0])
                return f"Pressed key: {keys[0]}"

        elif action == "get_screen_size":
            width, height = pyautogui.size()
            return f"Screen size: {width}x{height}"
            
        elif action == "get_mouse_position":
            x, y = pyautogui.position()
            return f"Mouse position: ({x}, {y})"

        else:
            return f"Error: Unknown hands action '{action}'"

    except Exception as e:
        return f"Error executing {action}: {str(e)}"

TOOL_DEFINITIONS = [
    {
        "name": "hands_action",
        "description": "Perform GUI interactions (mouse movement, clicking, dragging, typing, key presses) to control the system.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["mouse_move", "mouse_click", "mouse_drag", "keyboard_type", "keyboard_press", "get_screen_size", "get_mouse_position"],
                    "description": "The type of interaction to perform."
                },
                "params": {
                    "type": "object",
                    "description": "Parameters for the action: x/y (int), duration (float), button ('left', 'right', 'middle'), clicks (int), text (str), keys (list of str, e.g. ['ctrl', 'c'] or ['enter']).",
                    "additionalProperties": True
                }
            },
            "required": ["action", "params"]
        }
    }
]

def _hands_action_handler(args: Dict[str, Any]) -> str:
    action = args.get("action", "")
    params = args.get("params", {})
    return handle_hands_command(action, params)

HANDLERS = {
    "hands_action": _hands_action_handler
}
