"""Tests for CI failure gates and test-file tracking."""

import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ci_commands_do_not_swallow_failures_and_run_pytest():
    """CI commands must preserve failures and include the test suite."""
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    )
    steps = workflow["jobs"]["build"]["steps"]
    commands = [step["run"] for step in steps if "run" in step]

    assert all("|| echo" not in command for command in commands)
    assert any("pytest" in command for command in commands)


def test_test_files_are_not_git_ignored():
    """Test files should be visible to git in a checkout."""
    git_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if git_root.returncode != 0:
        pytest.skip("not a git checkout")

    result = subprocess.run(
        ["git", "check-ignore", "-q", "tests/test_ci_gates.py"],
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 1
