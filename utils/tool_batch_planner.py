"""Split one model turn's tool calls into ordered parallel/sequential segments.

The loop used to run a batch concurrently only if every call was on a fixed
allowlist, so one outsider serialized the whole batch. Each call is now
classified on its own: stateless tools join a parallel run, path-scoped readers
and writers join it unless their paths conflict, and everything else is a
barrier that runs alone. Call order is preserved exactly.

The planner must never be able to break a turn: any failure degrades to one
sequential segment, which is the loop's old behaviour.

Config (``tool_batching`` section, all keys optional): ``enabled``,
``path_scoped``, ``parallel_safe_tools``, ``never_parallel_tools``, plus
``path_scoped_readers`` / ``path_scoped_writers`` for extra tools that take a
path argument.
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

DEFAULT_PARALLEL_SAFE_TOOLS: frozenset[str] = frozenset({
    "web_search", "fetch_url",
    "memory_recall", "memory_store",
    "get_config", "set_config",
    "read_file", "read_document", "list_dir",
    "wm_list", "wm_get", "wm_add",
})

DEFAULT_NEVER_PARALLEL_TOOLS: frozenset[str] = frozenset({
    "ask_user", "delegate_task", "spawn_subagent",
    "start_coding_session", "start_tracked_coding_task", "browser_task",
    "run_command", "run_python", "run_node", "run_script", "run_jupyter_cell",
})

PATH_SCOPED_READERS: frozenset[str] = frozenset({
    "read_file", "read_file_range", "read_document", "list_dir", "search_files", "find_files",
})
PATH_SCOPED_WRITERS: frozenset[str] = frozenset({"write_file", "patch_file", "koza_edit"})

_PATH_ARG_KEYS = ("path", "paths", "file", "directory", "dir", "target")
_FALSE_STRINGS = frozenset({"false", "0", "no", "off"})


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str) and value.strip():
        return value.strip().lower() not in _FALSE_STRINGS
    return default


def _name_set(value) -> frozenset[str]:
    """Tool names from a config value; a lone string counts as one name."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(v.strip() for v in value if isinstance(v, str) and v.strip())


def _section(settings) -> dict:
    section = settings.get("tool_batching") if isinstance(settings, dict) else None
    return section if isinstance(section, dict) else {}


def tool_batching_policy(settings: dict | None) -> dict:
    """Resolve the ``tool_batching`` config; malformed values fall back to defaults."""
    section = _section(settings)
    return {
        "enabled": _as_bool(section.get("enabled"), True),
        "path_scoped": _as_bool(section.get("path_scoped"), True),
        "parallel_safe": DEFAULT_PARALLEL_SAFE_TOOLS | _name_set(section.get("parallel_safe_tools")),
        "never_parallel": DEFAULT_NEVER_PARALLEL_TOOLS | _name_set(section.get("never_parallel_tools")),
    }


def _canonical(path: str, cwd: str) -> str:
    # Expand ~ first: the file tools do, so "~/a" and "/home/me/a" are one file.
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd, expanded)
    return os.path.normcase(os.path.realpath(expanded))


def _extract_paths(args: dict, cwd: str) -> frozenset[str] | None:
    """Canonical paths named by ``args``; ``None`` when there are none to trust.

    A malformed value also yields ``None``: dropping it could hide the path a
    call really touches.
    """
    paths = set()
    for key in _PATH_ARG_KEYS:
        value = args.get(key)
        if value is None:
            continue
        for item in value if isinstance(value, (list, tuple)) else [value]:
            if not isinstance(item, str) or not item.strip():
                return None
            try:
                paths.add(_canonical(item, cwd))
            except (OSError, ValueError):  # e.g. an embedded NUL byte
                return None
    return frozenset(paths) or None


def _is_ancestor(parent: str, child: str) -> bool:
    return child.startswith(parent.rstrip(os.sep) + os.sep)


def _paths_overlap(left: frozenset[str], right: frozenset[str]) -> bool:
    return any(a == b or _is_ancestor(a, b) or _is_ancestor(b, a) for a in left for b in right)


def _admit(call, policy: dict, readers: frozenset, writers: frozenset, cwd: str):
    """Return ``(paths, is_writer)`` for a call that may join a run, else ``None``."""
    name = call.get("name") if isinstance(call, dict) else None
    args = call.get("arguments") if isinstance(call, dict) else None
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    if name in policy["never_parallel"]:
        return None
    if name in writers:
        if not policy["path_scoped"]:
            return None  # a writer never runs unscoped, even if allowlisted
        paths = _extract_paths(args, cwd)
        return None if paths is None else (paths, True)
    if policy["path_scoped"] and name in readers:
        paths = _extract_paths(args, cwd)
        if paths is None:
            # No path argument at all reads the tool's own default (cwd). A malformed
            # one stays a barrier, so a bad value cannot hide a file it really touches.
            if any(key in args for key in _PATH_ARG_KEYS):
                return None
            return frozenset({_canonical(".", cwd)}), False
        return paths, False
    if name in policy["parallel_safe"]:
        return frozenset(), False
    return None


def _build_segments(calls: list, settings, execution_cwd) -> list[tuple[str, list[dict]]]:
    policy = tool_batching_policy(settings)
    if not policy["enabled"]:
        return [("sequential", calls)]

    section = _section(settings)
    writers = PATH_SCOPED_WRITERS | _name_set(section.get("path_scoped_writers"))
    readers = PATH_SCOPED_READERS | _name_set(section.get("path_scoped_readers"))
    cwd = execution_cwd or os.getcwd()

    segments: list[tuple[str, list[dict]]] = []

    def emit(run: list[dict]) -> None:
        # A run of one has nothing to run alongside: it demotes to sequential.
        kind = "parallel" if len(run) >= 2 else "sequential"
        if kind == "sequential" and segments and segments[-1][0] == "sequential":
            segments[-1][1].extend(run)
        elif run:
            segments.append((kind, list(run)))

    run: list[dict] = []
    reservations: list[tuple[frozenset[str], bool]] = []
    for call in calls:
        admission = _admit(call, policy, readers, writers, cwd)
        if admission is None:
            emit(run)
            emit([call])
            run, reservations = [], []
            continue
        paths, is_writer = admission
        if any(
            (is_writer or held_writer) and _paths_overlap(paths, held)
            for held, held_writer in reservations
        ):
            emit(run)
            run, reservations = [], []
        run.append(call)
        reservations.append((paths, is_writer))
    emit(run)
    return segments


def plan_tool_batch(
    calls: list[dict],
    *,
    settings: dict | None = None,
    execution_cwd: str | None = None,
) -> list[tuple[str, list[dict]]]:
    """Plan ``calls`` as ordered ``("parallel" | "sequential", [call, ...])`` segments.

    The segments concatenate to exactly ``calls``; a parallel segment holds at
    least two calls; adjacent sequential segments are merged. Any internal error
    returns one sequential segment.
    """
    try:
        segments = _build_segments(calls, settings, execution_cwd)
        _log.debug(
            "tool batch: %d call(s) -> segments %s",
            len(calls), [(kind, len(segment)) for kind, segment in segments],
        )
        return segments
    except Exception:  # noqa: BLE001 - the planner must never break a turn
        _log.debug("tool batch planner failed; running the batch sequentially", exc_info=True)
        return [("sequential", calls)]


def batch_is_fully_parallel(
    calls: list[dict],
    *,
    settings: dict | None = None,
    execution_cwd: str | None = None,
) -> bool:
    """Whether the whole batch runs as a single parallel segment."""
    segments = plan_tool_batch(calls, settings=settings, execution_cwd=execution_cwd)
    return len(segments) == 1 and segments[0][0] == "parallel"
