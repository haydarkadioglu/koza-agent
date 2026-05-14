"""System info skill — OS, env vars, processes."""
import os
import platform
import psutil

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_os_info",
            "description": "Get operating system and hardware information.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_env_var",
            "description": "Get the value of an environment variable. Pass empty name to list all.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "default": ""}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "List running processes. Optionally filter by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {"type": "string", "description": "Substring filter on process name", "default": ""},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        },
    },
]


def get_os_info() -> str:
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/") if platform.system() != "Windows" else psutil.disk_usage("C:\\")
        return (
            f"OS: {platform.system()} {platform.release()} ({platform.machine()})\n"
            f"Python: {platform.python_version()}\n"
            f"CPU: {psutil.cpu_count(logical=False)} cores ({psutil.cpu_count()} logical), {psutil.cpu_percent(interval=0.5)}% used\n"
            f"RAM: {mem.used // 1024**2} MB / {mem.total // 1024**2} MB ({mem.percent}% used)\n"
            f"Disk: {disk.used // 1024**3} GB / {disk.total // 1024**3} GB ({disk.percent}% used)"
        )
    except Exception as e:
        return f"ERROR: {e}"


def get_env_var(name: str = "") -> str:
    if name:
        val = os.environ.get(name)
        return f"{name}={val}" if val else f"{name} not set"
    return "\n".join(f"{k}={v}" for k, v in sorted(os.environ.items()))


def list_processes(filter: str = "", limit: int = 20) -> str:
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
            try:
                info = p.info
                if filter and filter.lower() not in info["name"].lower():
                    continue
                mem_mb = (info["memory_info"].rss // 1024**2) if info["memory_info"] else 0
                procs.append((info["pid"], info["name"], info["status"], mem_mb))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs = procs[:limit]
        lines = [f"{'PID':>7}  {'NAME':<30}  {'STATUS':<10}  {'MEM(MB)':>8}"]
        lines += [f"{pid:>7}  {name:<30}  {status:<10}  {mem:>8}" for pid, name, status, mem in procs]
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {"get_os_info": get_os_info, "get_env_var": get_env_var, "list_processes": list_processes}
