import pytest

from skills.devops import git_operation
from skills.environments import LocalEnvironment
from utils.command_policy import (
    BLOCKED_PATTERN_MESSAGE,
    BLOCKED_PUSH_MESSAGE,
    CommandPolicy,
    check_command,
    is_git_push,
)

DEFAULT_CFG = {"security": {"block_git_push": True}}

BLOCKED = [
    "git push",
    "git push -u origin HEAD",
    "git push --dry-run",
    "git -C /tmp/x push --force",
    "git --git-dir=/r/.git push",
    "git --no-pager -c user.name=x push",
    "cd /r && git push",
    "echo hi; git push",
    "echo hi || git push",
    "git status && git push origin main",
    "git status | git push",
    "git status\ngit push",
    'bash -c "git push origin main"',
    "sh -c 'cd /r; git push'",
    "bash -lc 'git push'",
    "bash -c \"sh -c 'git push'\"",
    "sudo git push",
    "sudo -u root git push",
    "env FOO=1 git push",
    "FOO=1 git push",
    "nohup git push &",
    "git.exe push",
    "/usr/bin/git push",
    "(git push)",
    'echo "$(git push)"',
    "echo `git push`",
    "git -c alias.p=push p",
    "env -S 'git push origin main'",
    "env --split-string='git push'",
    "find . -name '*.txt' -exec git push ;",
    "find . -name x -execdir git push '{}' \\;",
]

ALLOWED = [
    "git status",
    "git pull",
    'git commit -am "wip"',
    "git log --oneline -5",
    'git commit -m "git push is disabled"',
    'git commit -m "wip; git push origin main"',
    'echo "git push"',
    "echo 'git push'",
    "legit-git push",
    "git pushx",
    "git push-me",
    "git --version",
    "git log --grep push",
    "ls -la",
    "",
    "   ",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_push_spellings_are_blocked(command):
    assert is_git_push(command)
    assert check_command(command, DEFAULT_CFG) == BLOCKED_PUSH_MESSAGE


@pytest.mark.parametrize("command", ALLOWED)
def test_non_push_commands_are_allowed(command):
    assert not is_git_push(command)
    assert check_command(command, DEFAULT_CFG) is None


def test_unbalanced_quotes_do_not_raise():
    assert is_git_push("git push 'unterminated")
    assert not is_git_push('echo "unterminated')


def test_shell_recursion_stops_at_depth_limit():
    nested = "git push"
    for _ in range(5):
        nested = "bash -c " + repr(nested)
    assert not is_git_push(nested)


def test_default_config_blocks_push():
    from config import default_config

    assert check_command("git push", default_config()) == BLOCKED_PUSH_MESSAGE
    assert check_command("git push", {}) == BLOCKED_PUSH_MESSAGE


def test_disabling_push_block_keeps_pattern_block():
    policy = CommandPolicy(block_push=False, blocked_patterns=(r"rm\s+-rf\s+/",))

    assert policy.check("git push origin main") is None
    assert policy.check("rm -rf /") == BLOCKED_PATTERN_MESSAGE


def test_from_config_reads_security_keys():
    policy = CommandPolicy.from_config({"security": {
        "block_git_push": False,
        "blocked_command_patterns": [r"^curl\b"],
    }})

    assert policy.check("git push") is None
    assert policy.check("curl https://example.com") == BLOCKED_PATTERN_MESSAGE


def test_allow_list_is_checked_first():
    cfg = {"security": {"blocked_command_allow": [r"^git push origin hotfix"]}}

    assert check_command("git push origin hotfix", cfg) is None
    assert check_command("git push", cfg) == BLOCKED_PUSH_MESSAGE


def test_invalid_regex_does_not_raise():
    cfg = {"security": {
        "blocked_command_patterns": ["[unclosed", r"^danger"],
        "blocked_command_allow": ["(unclosed"],
    }}

    assert check_command("ls", cfg) is None
    assert check_command("danger zone", cfg) == BLOCKED_PATTERN_MESSAGE
    assert check_command("git push", cfg) == BLOCKED_PUSH_MESSAGE


def test_local_environment_refuses_push_before_spawning(tmp_path):
    ret, out, err = LocalEnvironment().execute("git push origin main", cwd=str(tmp_path))

    assert ret == 126
    assert "blocked" in (out + err).lower()
    assert "fatal:" not in out + err
    assert "Everything up-to-date" not in out + err


def test_chained_command_after_push_never_runs(tmp_path):
    sentinel = tmp_path / "sentinel"
    ret, _out, _err = LocalEnvironment().execute(
        "git push; touch " + str(sentinel), cwd=str(tmp_path)
    )

    assert ret == 126
    assert not sentinel.exists()


def test_local_environment_still_runs_normal_commands(tmp_path):
    ret, out, _err = LocalEnvironment().execute("echo ok", cwd=str(tmp_path))

    assert ret == 0
    assert out.strip() == "ok"


def test_devops_push_returns_shared_message():
    assert git_operation("push") == BLOCKED_PUSH_MESSAGE
