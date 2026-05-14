"""Smart home skill — Philips Hue, MQTT, Home Assistant."""
import urllib.request
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "hue_list_lights",
            "description": "List all Philips Hue lights.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bridge_ip": {"type": "string", "default": ""},
                    "api_key": {"type": "string", "default": ""},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hue_set_light",
            "description": "Control a Philips Hue light (on/off, brightness, color).",
            "parameters": {
                "type": "object",
                "properties": {
                    "light_id": {"type": "string"},
                    "on": {"type": "boolean", "default": True},
                    "brightness": {"type": "integer", "description": "0-254", "default": 254},
                    "color_temp": {"type": "integer", "description": "Mirek 153-500", "default": 0},
                    "bridge_ip": {"type": "string", "default": ""},
                    "api_key": {"type": "string", "default": ""},
                },
                "required": ["light_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mqtt_publish",
            "description": "Publish a message to an MQTT broker topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "message": {"type": "string"},
                    "broker": {"type": "string", "default": "localhost"},
                    "port": {"type": "integer", "default": 1883},
                },
                "required": ["topic", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "home_assistant_call",
            "description": "Call a Home Assistant service (e.g. light.turn_on, switch.toggle).",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "e.g. light, switch, script"},
                    "service": {"type": "string", "description": "e.g. turn_on, turn_off, toggle"},
                    "entity_id": {"type": "string"},
                    "ha_url": {"type": "string", "default": "http://homeassistant.local:8123"},
                    "token": {"type": "string", "default": ""},
                },
                "required": ["domain", "service", "entity_id"],
            },
        },
    },
]

_smarthome_cfg: dict = {}


def init_smarthome(cfg: dict):
    global _smarthome_cfg
    _smarthome_cfg = cfg.get("smarthome", {})


def _hue_request(bridge_ip: str, api_key: str, path: str, method: str = "GET", data: dict = None):
    ip = bridge_ip or _smarthome_cfg.get("hue_bridge_ip", "")
    key = api_key or _smarthome_cfg.get("hue_api_key", "")
    url = f"http://{ip}/api/{key}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def hue_list_lights(bridge_ip: str = "", api_key: str = "") -> str:
    try:
        lights = _hue_request(bridge_ip, api_key, "/lights")
        if not lights:
            return "No lights found."
        lines = [f"{'ID':<5}  {'NAME':<30}  {'STATE':<6}  BRIGHTNESS"]
        for lid, light in lights.items():
            state = light.get("state", {})
            on = "ON" if state.get("on") else "OFF"
            bri = state.get("bri", 0)
            lines.append(f"{lid:<5}  {light['name']:<30}  {on:<6}  {bri}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e} (Check bridge IP and API key in config)"


def hue_set_light(light_id: str, on: bool = True, brightness: int = 254,
                  color_temp: int = 0, bridge_ip: str = "", api_key: str = "") -> str:
    try:
        body: dict = {"on": on}
        if on and brightness:
            body["bri"] = max(0, min(254, brightness))
        if on and color_temp:
            body["ct"] = max(153, min(500, color_temp))
        result = _hue_request(bridge_ip, api_key, f"/lights/{light_id}/state", method="PUT", data=body)
        return f"Light {light_id}: {result}"
    except Exception as e:
        return f"ERROR: {e}"


def mqtt_publish(topic: str, message: str, broker: str = "localhost", port: int = 1883) -> str:
    try:
        import paho.mqtt.publish as publish
        publish.single(topic, message, hostname=broker, port=port)
        return f"Published to {broker}:{port}/{topic}: {message}"
    except ImportError:
        return "paho-mqtt not installed. Run: pip install paho-mqtt"
    except Exception as e:
        return f"ERROR: {e}"


def home_assistant_call(domain: str, service: str, entity_id: str,
                        ha_url: str = "", token: str = "") -> str:
    try:
        url = ha_url or _smarthome_cfg.get("ha_url", "http://homeassistant.local:8123")
        tok = token or _smarthome_cfg.get("ha_token", "")
        api_url = f"{url}/api/services/{domain}/{service}"
        data = json.dumps({"entity_id": entity_id}).encode()
        req = urllib.request.Request(
            api_url, data=data, method="POST",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = resp.read().decode()
        return f"HA service called: {domain}.{service} on {entity_id}\n{result[:200]}"
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "hue_list_lights": hue_list_lights,
    "hue_set_light": hue_set_light,
    "mqtt_publish": mqtt_publish,
    "home_assistant_call": home_assistant_call,
}
