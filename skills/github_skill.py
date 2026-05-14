"""GitHub skill — code search, issues, PRs, repo operations via PyGithub."""
import urllib.request
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "github_search_code",
            "description": "Search GitHub code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_create_issue",
            "description": "Create a GitHub issue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo"},
                    "title": {"type": "string"},
                    "body": {"type": "string", "default": ""},
                    "labels": {"type": "string", "default": "", "description": "Comma-separated labels"},
                },
                "required": ["repo", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_list_prs",
            "description": "List open pull requests in a GitHub repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo"},
                    "state": {"type": "string", "default": "open", "enum": ["open", "closed", "all"]},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_repo_info",
            "description": "Get information about a GitHub repository.",
            "parameters": {
                "type": "object",
                "properties": {"repo": {"type": "string", "description": "owner/repo"}},
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_clone_repo",
            "description": "Clone a GitHub repository locally.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo or full URL"},
                    "dest": {"type": "string", "default": "", "description": "Local destination path"},
                },
                "required": ["repo"],
            },
        },
    },
]

_github_token: str = ""


def init_github(token: str):
    global _github_token
    _github_token = token


def _gh_request(path: str, method: str = "GET", data: dict = None) -> dict:
    url = f"https://api.github.com{path}"
    headers = {
        "User-Agent": "KozaAgent/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if _github_token:
        headers["Authorization"] = f"Bearer {_github_token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def github_search_code(query: str, limit: int = 5) -> str:
    try:
        import urllib.parse
        path = f"/search/code?q={urllib.parse.quote(query)}&per_page={limit}"
        data = _gh_request(path)
        items = data.get("items", [])
        if not items:
            return "No results found."
        lines = []
        for item in items:
            lines.append(f"📄 {item['repository']['full_name']} — {item['path']}\n   {item['html_url']}")
        return f"Found {data.get('total_count',0)} results:\n\n" + "\n\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


def github_create_issue(repo: str, title: str, body: str = "", labels: str = "") -> str:
    try:
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = [l.strip() for l in labels.split(",")]
        data = _gh_request(f"/repos/{repo}/issues", method="POST", data=payload)
        return f"Issue created: #{data['number']} — {data['html_url']}"
    except Exception as e:
        return f"ERROR: {e}"


def github_list_prs(repo: str, state: str = "open", limit: int = 10) -> str:
    try:
        data = _gh_request(f"/repos/{repo}/pulls?state={state}&per_page={limit}")
        if not data:
            return "No pull requests found."
        lines = [f"{'#':>5}  {'TITLE':<50}  AUTHOR"]
        for pr in data:
            lines.append(f"#{pr['number']:>4}  {pr['title'][:50]:<50}  {pr['user']['login']}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


def github_repo_info(repo: str) -> str:
    try:
        data = _gh_request(f"/repos/{repo}")
        return (
            f"Repo: {data['full_name']}\n"
            f"Description: {data.get('description','')}\n"
            f"Language: {data.get('language','N/A')}\n"
            f"Stars: {data['stargazers_count']:,}  Forks: {data['forks_count']:,}  Issues: {data['open_issues_count']:,}\n"
            f"License: {data.get('license',{}).get('name','N/A')}\n"
            f"URL: {data['html_url']}"
        )
    except Exception as e:
        return f"ERROR: {e}"


def github_clone_repo(repo: str, dest: str = "") -> str:
    import subprocess
    url = repo if repo.startswith("http") else f"https://github.com/{repo}.git"
    cmd = ["git", "clone", url] + ([dest] if dest else [])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return (result.stdout + result.stderr).strip() or "Cloned successfully."
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "github_search_code": github_search_code,
    "github_create_issue": github_create_issue,
    "github_list_prs": github_list_prs,
    "github_repo_info": github_repo_info,
    "github_clone_repo": github_clone_repo,
}
