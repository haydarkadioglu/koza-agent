# -*- coding: utf-8 -*-
"""Verify-on-stop gate: a last check before the agent declares a turn finished.

Koza used to end the turn the moment the model produced a text-only response,
even when that same turn had just edited source files and never ran a test,
lint or build command afterwards. The final answer could then claim the work
was done while it had never been verified. This module watches the tool calls
made during a turn and, when the turn is about to end with edited code that has
no verification run after the last edit, returns a synthetic nudge the loop
injects so the model gets a bounded number of extra rounds to actually verify.

Fail-open by design: every error inside the gate disables it for the call,
never blocks the answer.
"""
import os
import re

# Tools that can change code on disk.
_MUTATING_TOOLS = frozenset({
    "write_file", "patch_file", "create_project", "extract_project",
    "run_script", "format_code",
})

# Tools that verify by name alone (their handler runs the checks itself).
_VERIFY_TOOL_NAMES = frozenset({"run_tests", "lint_code"})

# Tools whose arguments may contain a verification command.
_EXEC_TOOLS = frozenset({
    "run_command", "run_tests", "lint_code", "run_python", "run_node",
    "run_jupyter_cell",
})

# A command that counts as verification evidence for the edited code.
_VERIFY_COMMAND_RE = re.compile(
    r"\b(pytest|py\.test|unittest|nose2|ruff|flake8|mypy|pylint|black|isort|"
    r"eslint|prettier|tsc|vitest|jest|mocha|karma|cypress|playwright[\s-]?test|"
    r"npm[\s-]+test|yarn[\s-]+test|pnpm[\s-]+test|go[\s-]+test|go[\s-]+vet|"
    r"cargo[\s-]+test|cargo[\s-]+clippy|dotnet[\s-]+test|mvn[\s-]+test|"
    r"gradle[\s-]+test|make[\s-]+test|ctest|tox|nix-build)\b",
    re.IGNORECASE,
)

# Prose and data files: editing them leaves nothing to run or lint.
_NON_CODE_SUFFIXES = frozenset({
    ".md", ".rst", ".txt", ".log", ".csv", ".tsv",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".lock",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".pdf",
    ".mp3", ".mp4", ".wav", ".zip", ".tar", ".gz",
})
_NON_CODE_BASENAMES = frozenset({
    "license", "readme", "changelog", "code_of_conduct", "notice", "authors",
})

_DEFAULT_MAX_ATTEMPTS = 2


def _is_code_path(path: str) -> bool:
    name = os.path.basename(str(path or "").strip())
    if not name:
        return False
    stem, _, ext = name.rpartition(".")
    base = (stem or ext).lower()
    if base in _NON_CODE_BASENAMES:
        return False
    if ext and f".{ext.lower()}" in _NON_CODE_SUFFIXES:
        return False
    return True


def _resolve_settings(cfg) -> tuple[bool, int]:
    cfg = cfg if isinstance(cfg, dict) else {}
    section = cfg.get("verify_on_stop")
    section = section if isinstance(section, dict) else {}
    enabled = bool(section.get("enabled", True))
    try:
        max_attempts = int(section.get("max_attempts", _DEFAULT_MAX_ATTEMPTS))
    except (TypeError, ValueError):
        max_attempts = _DEFAULT_MAX_ATTEMPTS
    return enabled, max(0, max_attempts)


def _arg_str(args: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value
    # Fall back to a shallow join of any string values (path may be nested).
    parts = []
    for value in args.values():
        if isinstance(value, str) and len(value) < 4096:
            parts.append(value)
    return " ".join(parts)


class VerifyOnStopGate:
    """Tracks edits vs. verification across one turn's tool calls."""

    def __init__(self, cfg=None) -> None:
        self._enabled, self._max_attempts = _resolve_settings(cfg)
        self._edited: list[str] = []
        self._verified_after_last_edit = False
        self._attempts = 0

    @property
    def attempts(self) -> int:
        return self._attempts

    def observe(self, name: str, args: dict) -> None:
        """Record one executed tool call (called before the tool runs)."""
        if not self._enabled:
            return
        try:
            args = args if isinstance(args, dict) else {}
            if name in _MUTATING_TOOLS:
                paths = _arg_str(args, ("path", "file_path", "file", "project", "name"))
                code_paths = [p for p in paths.split() if _is_code_path(p)]
                if code_paths:
                    self._edited.extend(code_paths)
                    self._verified_after_last_edit = False
            elif name in _VERIFY_TOOL_NAMES:
                # run_tests / lint_code verify by name — no command string to match.
                self._verified_after_last_edit = True
            elif name in _EXEC_TOOLS:
                command = _arg_str(args, ("command", "cmd", "code", "script"))
                if _VERIFY_COMMAND_RE.search(command):
                    self._verified_after_last_edit = True
        except Exception:
            self._enabled = False  # fail open: never block the answer

    def build_nudge(self) -> str | None:
        """Synthetic follow-up when code was edited without fresh verification.

        Returns ``None`` when the turn may end: nothing to verify, already
        verified after the last edit, disabled, or the retry budget is spent.
        """
        if not self._enabled or self._attempts >= self._max_attempts:
            return None
        paths = sorted(set(self._edited))
        if not paths or self._verified_after_last_edit:
            return None
        self._attempts += 1
        shown = paths[:8]
        listed = "\n".join(f"- {p}" for p in shown)
        if len(paths) > len(shown):
            listed += f"\n- ... and {len(paths) - len(shown)} more"
        return (
            "[System: You edited code in this turn, but no verification command "
            "has run since the last edit. The final answer must not claim the "
            "work is verified until something actually ran.\n\n"
            f"Changed code paths:\n{listed}\n\n"
            "Run the relevant test/lint/build command now (for example pytest, "
            "ruff, or the project's own test command), read any failure, repair "
            "the code, and summarize what passed. If verification is genuinely "
            "impossible here, state the concrete blocker instead of claiming "
            "the work is fully verified.]"
        )


__all__ = ["VerifyOnStopGate", "_is_code_path"]
