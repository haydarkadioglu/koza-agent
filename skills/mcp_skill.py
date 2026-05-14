"""MCP (Model Context Protocol) skill — bridge to external MCP servers."""
import json
import urllib.request

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "mcp_list_tools",
            "description": "List available tools from an MCP server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_url": {"type": "string", "description": "MCP server URL, e.g. http://localhost:3000"},
                },
                "required": ["server_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_call_tool",
            "description": "Call a tool on an MCP server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "server_url": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "arguments": {"type": "object", "default": {}},
                },
                "required": ["server_url", "tool_name"],
            },
        },
    },
]


def _mcp_post(server_url: str, method: str, params: dict = None) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        server_url.rstrip("/") + "/",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "KozaAgent/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def mcp_list_tools(server_url: str) -> str:
    try:
        resp = _mcp_post(server_url, "tools/list")
        tools = resp.get("result", {}).get("tools", [])
        if not tools:
            return "No tools found on MCP server."
        lines = [f"MCP Server: {server_url}\nAvailable tools ({len(tools)}):"]
        for t in tools:
            lines.append(f"  • {t['name']}: {t.get('description','')[:80]}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR connecting to MCP server: {e}"


def mcp_call_tool(server_url: str, tool_name: str, arguments: dict = None) -> str:
    try:
        resp = _mcp_post(server_url, "tools/call", {"name": tool_name, "arguments": arguments or {}})
        result = resp.get("result", {})
        content = result.get("content", [])
        if isinstance(content, list):
            return "\n".join(c.get("text", str(c)) for c in content)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR calling MCP tool: {e}"


HANDLERS = {"mcp_list_tools": mcp_list_tools, "mcp_call_tool": mcp_call_tool}
