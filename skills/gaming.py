"""Gaming skill — Minecraft RCON, PokéAPI lookups."""
import socket
import struct
import json
import urllib.request

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "minecraft_command",
            "description": "Send a command to a Minecraft server via RCON protocol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "host": {"type": "string", "default": "localhost"},
                    "port": {"type": "integer", "default": 25575},
                    "password": {"type": "string", "default": ""},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pokemon_lookup",
            "description": "Look up Pokémon stats, moves, and abilities from PokéAPI (no key required).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Pokémon name or Pokédex number"},
                },
                "required": ["name"],
            },
        },
    },
]


class _RCONClient:
    """Minimal RCON client."""
    LOGIN, COMMAND = 3, 2

    def __init__(self, host, port, password):
        self.sock = socket.socket()
        self.sock.connect((host, port))
        self._send(0, self.LOGIN, password)

    def _send(self, req_id, pkt_type, payload):
        data = struct.pack("<ii", req_id, pkt_type) + payload.encode("utf-8") + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(data)) + data)
        size = struct.unpack("<i", self.sock.recv(4))[0]
        resp = self.sock.recv(size)
        _, out_id, out_type = struct.unpack("<iii", resp[:12])
        return resp[12:-2].decode("utf-8", errors="replace")

    def command(self, cmd):
        return self._send(1, self.COMMAND, cmd)

    def close(self):
        self.sock.close()


def minecraft_command(command: str, host: str = "localhost", port: int = 25575, password: str = "") -> str:
    try:
        client = _RCONClient(host, port, password)
        result = client.command(command)
        client.close()
        return result or "(no output)"
    except ConnectionRefusedError:
        return f"Cannot connect to Minecraft RCON at {host}:{port}. Is the server running with RCON enabled?"
    except Exception as e:
        return f"ERROR: {e}"


def pokemon_lookup(name: str) -> str:
    try:
        url = f"https://pokeapi.co/api/v2/pokemon/{name.lower().strip()}"
        req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        pname = data["name"].capitalize()
        pid = data["id"]
        types = ", ".join(t["type"]["name"].capitalize() for t in data["types"])
        stats = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}
        abilities = ", ".join(a["ability"]["name"] for a in data["abilities"])
        moves_count = len(data["moves"])
        stat_str = "  ".join(f"{k[:3].upper()}:{v}" for k, v in stats.items())
        return (
            f"#{pid} {pname}\n"
            f"Type: {types}\n"
            f"Abilities: {abilities}\n"
            f"Stats: {stat_str}\n"
            f"Moves: {moves_count} available"
        )
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {"minecraft_command": minecraft_command, "pokemon_lookup": pokemon_lookup}
