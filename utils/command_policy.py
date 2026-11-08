"""Shell command policy — the single place that decides whether a command may run.

Every model-driven shell command funnels through ``check_command`` in
``skills/environments.py`` right before the process is spawned, so the
``git push`` guard is enforced where the process starts and the shell tool
cannot bypass it with ``cd x && git push``, ``bash -c "git push"``,
``env FOO=1 git push`` and similar spellings.

Scope: this is a guard against direct spellings of a command, not a sandbox.
Obfuscated construction (``eval``, base64-decoded scripts, variables expanded
into a command name, git aliases defined in a gitconfig file) is out of scope.
"""

import logging
import re
import shlex
from typing import Any

logger = logging.getLogger(__name__)

BLOCKED_PUSH_MESSAGE = (
    "ERROR: git push is blocked by Koza's safety policy "
    "(security.block_git_push). Push changes manually after reviewing them."
)
BLOCKED_PATTERN_MESSAGE = "Blocked by policy: matches security.blocked_command_patterns"

_MAX_SHELL_DEPTH = 3

# Wrapper commands that run their arguments as a command, mapped to the
# options of theirs that consume the following token.
_WRAPPERS: dict[str, frozenset[str]] = {
    "sudo": frozenset({"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U"}),
    "doas": frozenset({"-u", "-C"}),
    "env": frozenset({"-u", "-C", "-S"}),
    "command": frozenset(),
    "exec": frozenset({"-a"}),
    "nohup": frozenset(),
    "time": frozenset({"-f", "-o"}),
    "nice": frozenset({"-n"}),
    "xargs": frozenset({"-I", "-n", "-L", "-P", "-d", "-E", "-s", "-a"}),
}

_GIT_VALUE_OPTIONS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--exec-path", "--super-prefix", "--config-env",
})

_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "pwsh", "powershell", "cmd"})
_EXEC_FLAGS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_SHELL_SCRIPT_FLAGS = frozenset({"-c", "/c", "/C", "/k", "/K", "-Command", "-command"})

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_OPERATOR_CHARS = frozenset(";|&\n()")


def _basename(token: str) -> str:
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.removesuffix(".exe")


def _read_substitution(command: str, start: int) -> tuple[str, int]:
    """Return the body of ``$(...)`` or a backtick block starting at ``start``."""
    if command[start] == "`":
        end = command.find("`", start + 1)
        end = len(command) if end == -1 else end
        return command[start + 1:end], end + 1
    depth, i = 0, start + 1
    while i < len(command):
        if command[i] == "(":
            depth += 1
        elif command[i] == ")":
            depth -= 1
            if depth == 0:
                return command[start + 2:i], i + 1
        i += 1
    return command[start + 2:], len(command)


def _split_segments(command: str) -> list[str]:
    """Split a command line into simple commands on unquoted control operators.

    Command substitutions (``$(...)`` and backticks) also run inside double
    quotes, so their bodies are returned as segments of their own.
    """
    segments: list[str] = []
    buf: list[str] = []
    quote = ""
    i = 0
    while i < len(command):
        ch = command[i]
        if quote == "'":
            buf.append(ch)
            quote = "" if ch == "'" else quote
            i += 1
            continue
        if ch == "\\" and i + 1 < len(command):
            buf.append(command[i:i + 2])
            i += 2
            continue
        if ch == "`" or (quote == '"' and command.startswith("$(", i)):
            body, i = _read_substitution(command, i)
            segments.extend(_split_segments(body))
            buf.append("_")
            continue
        if quote == '"':
            buf.append(ch)
            quote = "" if ch == '"' else quote
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in _OPERATOR_CHARS:
            segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [s for s in segments if s.strip()]


def _tokenize(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _strip_wrappers(argv: list[str]) -> list[str]:
    i = 0
    while i < len(argv):
        token = argv[i]
        if _ASSIGNMENT.match(token):
            i += 1
            continue
        wrapper = _basename(token)
        value_options = _WRAPPERS.get(wrapper)
        if value_options is None:
            break
        i += 1
        while i < len(argv) and argv[i].startswith("-") and argv[i] != "-":
            option = argv[i]
            flag, sep, inline_value = option.partition("=")
            if wrapper == "env" and flag in ("-S", "--split-string") and (sep or i + 1 < len(argv)):
                # `env -S '<cmd> <args>'` re-splits its value and runs that command.
                if sep:
                    return _strip_wrappers(_tokenize(inline_value) + argv[i + 1:])
                return _strip_wrappers(_tokenize(argv[i + 1]) + argv[i + 2:])
            i += 2 if option in value_options else 1
    return argv[i:]


def _git_subcommand(args: list[str]) -> tuple[str | None, dict[str, str]]:
    """Return git's subcommand and any ``-c alias.<name>=...`` definitions."""
    aliases: dict[str, str] = {}
    i = 0
    while i < len(args):
        token = args[i]
        if token in _GIT_VALUE_OPTIONS:
            if token == "-c" and i + 1 < len(args):
                key, _, value = args[i + 1].partition("=")
                if key.lower().startswith("alias."):
                    aliases[key[len("alias."):]] = value
            i += 2
        elif token.startswith("-"):
            i += 1
        else:
            return token, aliases
    return None, aliases


def _alias_pushes(value: str, depth: int) -> bool:
    if value.startswith("!"):
        return _is_push(value[1:], depth + 1)
    words = _tokenize(value)
    return bool(words) and words[0] == "push"


def _segment_pushes(argv: list[str], depth: int) -> bool:
    argv = _strip_wrappers(argv)
    if not argv:
        return False
    name = _basename(argv[0])
    if name == "git":
        sub, aliases = _git_subcommand(argv[1:])
        if sub == "push":
            return True
        return sub in aliases and _alias_pushes(aliases[sub], depth)
    if name in ("find", "fd"):
        # `find ... -exec <cmd> ;` runs <cmd> once per match.
        for idx in range(1, len(argv) - 1):
            if argv[idx] in _EXEC_FLAGS and _segment_pushes(argv[idx + 1:], depth + 1):
                return True
    if name in _SHELLS:
        for idx, token in enumerate(argv[1:-1], start=1):
            is_combined = (token.startswith("-") and not token.startswith("--")
                           and token[1:].isalpha() and "c" in token[1:])
            if token in _SHELL_SCRIPT_FLAGS or (name not in {"pwsh", "powershell"} and is_combined):
                return _is_push(argv[idx + 1], depth + 1)
    return False


def _is_push(command: str, depth: int) -> bool:
    if depth > _MAX_SHELL_DEPTH or not command or not command.strip():
        return False
    return any(_segment_pushes(_tokenize(seg), depth) for seg in _split_segments(command))


def is_git_push(command: str) -> bool:
    """True when any simple command in ``command`` invokes ``git push``."""
    return _is_push(command, 0)


def _compile(patterns: Any) -> tuple[re.Pattern[str], ...]:
    if isinstance(patterns, str):
        patterns = [patterns]
    compiled = []
    for pattern in patterns or ():
        try:
            compiled.append(re.compile(pattern))
        except (re.error, TypeError) as exc:
            logger.debug("Ignoring invalid command policy pattern %r: %s", pattern, exc)
    return tuple(compiled)


class CommandPolicy:
    def __init__(self, block_push: bool = True, blocked_patterns: tuple[str, ...] = (),
                 allow_patterns: tuple[str, ...] = ()) -> None:
        self.block_push = bool(block_push)
        self.blocked_patterns = _compile(blocked_patterns)
        self.allow_patterns = _compile(allow_patterns)

    @classmethod
    def from_config(cls, cfg: dict | None = None) -> "CommandPolicy":
        """Build the policy from ``cfg["security"]``; loads the live config when ``cfg`` is None."""
        if cfg is None:
            try:
                from config import load_config

                cfg = load_config()
            except Exception as exc:  # noqa: BLE001 — fail closed on the defaults
                logger.debug("Could not load config for command policy: %s", exc)
                cfg = {}
        security = cfg.get("security") if isinstance(cfg, dict) else None
        security = security if isinstance(security, dict) else {}
        return cls(
            block_push=security.get("block_git_push", True),
            blocked_patterns=security.get("blocked_command_patterns") or (),
            allow_patterns=security.get("blocked_command_allow") or (),
        )

    def check(self, command: str) -> str | None:
        """Return None when ``command`` may run, else a human-readable refusal."""
        if not isinstance(command, str) or not command.strip():
            return None
        if any(p.search(command) for p in self.allow_patterns):
            return None
        if self.block_push and is_git_push(command):
            return BLOCKED_PUSH_MESSAGE
        if any(p.search(command) for p in self.blocked_patterns):
            return BLOCKED_PATTERN_MESSAGE
        return None


def check_command(command: str, cfg: dict | None = None) -> str | None:
    """Check ``command`` against the policy configured in ``cfg`` (default: live config)."""
    return CommandPolicy.from_config(cfg).check(command)
