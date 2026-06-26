"""GitHub skill — code search, issues, PRs, repo operations via PyGithub."""
import urllib.request
import json
from pathlib import Path
from urllib.parse import urlparse

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
    {
        "type": "function",
        "function": {
            "name": "github_prepare_repo",
            "description": (
                "Clone or update a GitHub repository into Koza's stable workspace "
                "so the path is not lost between tool calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo or full GitHub URL"},
                    "branch": {"type": "string", "default": "", "description": "Optional branch/tag to checkout when cloning"},
                    "dest": {"type": "string", "default": "", "description": "Optional destination path; defaults to ~/.Koza/workspace/repos/github/<owner_repo>"},
                    "update": {"type": "boolean", "default": True, "description": "If destination already exists, run git pull --ff-only"},
                },
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_create_pr",
            "description": "Create a new pull request on GitHub.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo"},
                    "title": {"type": "string", "description": "Title of the pull request"},
                    "head": {"type": "string", "description": "The name of the branch where your changes are implemented"},
                    "base": {"type": "string", "default": "main", "description": "The name of the branch you want the changes pulled into"},
                    "body": {"type": "string", "default": "", "description": "The contents of the pull request description"},
                },
                "required": ["repo", "title", "head"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_get_pr",
            "description": "Get detailed information about a pull request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo"},
                    "number": {"type": "integer", "description": "PR number"},
                },
                "required": ["repo", "number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_merge_pr",
            "description": "Merge a pull request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "owner/repo"},
                    "number": {"type": "integer", "description": "PR number"},
                    "commit_title": {"type": "string", "default": "", "description": "Title for the automatic commit message"},
                    "commit_message": {"type": "string", "default": "", "description": "Extra description for the commit message"},
                    "merge_method": {"type": "string", "default": "merge", "enum": ["merge", "squash", "rebase"], "description": "The merge method to use"},
                },
                "required": ["repo", "number"],
            },
        },
    },
]

_github_token: str = ""


def init_github(token: str):
    global _github_token
    _github_token = token


def _get_github_token() -> str:
    global _github_token
    if _github_token:
        return _github_token
    try:
        import os
        from config import load_config
        cfg = load_config()
        token = cfg.get("github_token") or cfg.get("github", {}).get("token") or os.environ.get("GITHUB_TOKEN") or ""
        return token
    except Exception:
        return ""


def _gh_request(path: str, method: str = "GET", data: dict = None) -> dict:
    url = f"https://api.github.com{path}"
    headers = {
        "User-Agent": "KozaAgent/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
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
    from skills import shell as _shell

    url = repo if repo.startswith("http") else f"https://github.com/{repo}.git"

    def _repo_dir_name(value: str) -> str:
        parsed = urlparse(value)
        path = parsed.path if parsed.scheme else value
        name = path.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name or "repository"

    base_dir = Path(_shell.get_cwd()).resolve()
    if dest:
        target_dir = Path(_shell.resolve_path(dest))
        cmd = ["git", "clone", url, str(target_dir)]
    else:
        target_dir = base_dir / _repo_dir_name(repo)
        cmd = ["git", "clone", url]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(base_dir))
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            return f"ERROR: git clone failed in {base_dir}\n{output}"
        _shell.set_cwd(str(target_dir))
        details = f"\n\nOutput:\n{output}" if output else ""
        return f"Cloned successfully.\nPath: {target_dir}\nWorking directory set to: {target_dir}{details}"
    except Exception as e:
        return f"ERROR: {e}"


def _repo_dir_name(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path if parsed.scheme else value
    bits = [part for part in path.rstrip("/").split("/") if part]
    if len(bits) >= 2:
        owner, name = bits[-2], bits[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return f"{owner}_{name}"
    name = bits[-1] if bits else "repository"
    if name.endswith(".git"):
        name = name[:-4]
    return name or "repository"


def github_prepare_repo(repo: str, branch: str = "", dest: str = "", update: bool = True) -> str:
    """Clone or update a repo in a stable workspace path and set shell CWD there."""
    import subprocess
    from skills import shell as _shell

    url = repo if repo.startswith("http") else f"https://github.com/{repo}.git"
    if dest:
        target_dir = Path(_shell.resolve_path(dest))
    else:
        target_dir = Path.home() / ".Koza" / "workspace" / "repos" / "github" / _repo_dir_name(repo)

    try:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if (target_dir / ".git").exists():
            actions = [f"Repository already exists: {target_dir}"]
            if update:
                pull = subprocess.run(
                    ["git", "-C", str(target_dir), "pull", "--ff-only"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                output = (pull.stdout + pull.stderr).strip()
                if pull.returncode != 0:
                    return f"ERROR: git pull failed in {target_dir}\n{output}"
                actions.append(output or "Already up to date.")
        else:
            cmd = ["git", "clone"]
            if branch:
                cmd.extend(["--branch", branch])
            cmd.extend([url, str(target_dir)])
            clone = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            output = (clone.stdout + clone.stderr).strip()
            if clone.returncode != 0:
                return f"ERROR: git clone failed into {target_dir}\n{output}"
            actions = [output or "Clone complete."]

        _shell.set_cwd(str(target_dir))
        return (
            "Repository ready.\n"
            f"Path: {target_dir.resolve()}\n"
            f"Working directory set to: {target_dir.resolve()}\n\n"
            + "\n".join(actions)
        )
    except Exception as e:
        return f"ERROR: {e}"


def github_create_pr(repo: str, title: str, head: str, base: str = "main", body: str = "") -> str:
    try:
        payload = {
            "title": title,
            "head": head,
            "base": base,
        }
        if body:
            payload["body"] = body
        data = _gh_request(f"/repos/{repo}/pulls", method="POST", data=payload)
        return f"Pull Request created successfully: #{data['number']} — {data['html_url']}"
    except Exception as e:
        return f"ERROR: {e}"


def github_get_pr(repo: str, number: int) -> str:
    try:
        data = _gh_request(f"/repos/{repo}/pulls/{number}")
        return (
            f"PR #{data['number']}: {data['title']}\n"
            f"State: {data['state']}  (Merged: {data.get('merged', False)})\n"
            f"Created by: {data['user']['login']}  Created at: {data['created_at']}\n"
            f"Branches: {data['head']['ref']} -> {data['base']['ref']}\n"
            f"Commits: {data.get('commits', 0)}  Changes: +{data.get('additions', 0)} -{data.get('deletions', 0)} ({data.get('changed_files', 0)} files)\n\n"
            f"Description:\n{data.get('body') or 'No description provided.'}\n\n"
            f"URL: {data['html_url']}"
        )
    except Exception as e:
        return f"ERROR: {e}"


def github_merge_pr(repo: str, number: int, commit_title: str = "", commit_message: str = "", merge_method: str = "merge") -> str:
    try:
        payload = {}
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message
        if merge_method:
            payload["merge_method"] = merge_method
        data = _gh_request(f"/repos/{repo}/pulls/{number}/merge", method="PUT", data=payload)
        if data.get("merged"):
            return f"PR #{number} merged successfully: {data.get('message', 'Success')}"
        return f"PR #{number} merge failed: {data.get('message')}"
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "github_search_code": github_search_code,
    "github_create_issue": github_create_issue,
    "github_list_prs": github_list_prs,
    "github_repo_info": github_repo_info,
    "github_clone_repo": github_clone_repo,
    "github_prepare_repo": github_prepare_repo,
    "github_create_pr": github_create_pr,
    "github_get_pr": github_get_pr,
    "github_merge_pr": github_merge_pr,
}
