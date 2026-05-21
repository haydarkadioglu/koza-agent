"""
Capability groups — named bundles of tool names.
Used by spawn_subagent(capabilities="browser,files") to give sub-agents
a focused tool set without listing individual tool names.
"""

CAPABILITY_GROUPS: dict[str, list[str]] = {
    # Web access and searching
    "browser": ["fetch_url", "web_search"],

    # Local filesystem operations
    "files": ["read_file", "write_file", "list_dir", "create_dir", "delete_file"],

    # Code execution
    "code": ["run_python", "run_node", "run_command", "run_script"],

    # Data science / analysis
    "data": ["pandas_query", "jupyter_run_cell", "matplotlib_plot"],

    # DevOps / infra
    "devops": ["docker_run", "git_operations", "webhook_listen"],

    # GitHub operations
    "github": ["github_search_code", "github_create_issue", "github_pr_review", "github_clone_repo"],

    # Research tools
    "research": ["arxiv_search", "wikipedia_search", "web_search", "fetch_url"],

    # Persistent + working memory
    "memory": ["memory_store", "memory_recall", "memory_search", "wm_add", "wm_get"],

    # Messaging channels
    "messaging": ["send_telegram", "send_email"],

    # Security / network tools
    "security": ["port_scan", "http_headers_check", "whois_lookup", "ssl_check"],

    # Creative tools (diagrams, images)
    "creative": ["architecture_diagram", "ascii_art", "image_gen"],

    # OS / system info
    "system": ["get_os_info", "get_env_var", "list_processes", "run_command"],

    # Finance / market data
    "finance": ["crypto_price", "stock_price", "portfolio_summary"],

    # Social media lookup
    "social": ["twitter_search", "reddit_search"],

    # Note-taking / Obsidian
    "notes": ["obsidian_create_note", "obsidian_search"],
}

# All known capability group names (for validation / LLM enum hints)
CAPABILITY_NAMES: list[str] = sorted(CAPABILITY_GROUPS.keys())


def resolve_capabilities(names: list[str]) -> list[str]:
    """
    Expand capability group names to a deduplicated list of tool names.

    Unknown names are silently skipped so the caller can freely mix
    group names and individual tool names without crashing.
    """
    tools: list[str] = []
    seen: set[str] = set()
    for name in names:
        for tool in CAPABILITY_GROUPS.get(name, []):
            if tool not in seen:
                seen.add(tool)
                tools.append(tool)
    return tools
