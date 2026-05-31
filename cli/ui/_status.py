"""Enriched status bar composer.

Provides helpers to format the status bar with model info, tokens, elapsed time,
background task count, shortened CWD, and memory usage.
"""

import os
import time


def shorten_path(path: str) -> str:
    """Return last two segments of a path.

    Handles both forward-slash and backslash separators.
    For paths with fewer than two segments, returns the original path unchanged.
    """
    parts = path.replace("\\", "/").rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else path


def format_status(
    state_text: str,
    model_name: str,
    total_tokens: int,
    token_limit: int,
    session_start: float,
    bg_task_count: int = 0,
    coding_mode: bool = False,
    mode: str = "",
) -> str:
    """Compose the full status bar string with all segments.

    Segments are separated by " │ " (space-pipe-space) delimiters.
    Includes: state, mode (if set), model, tokens, elapsed time, bg tasks (if > 0),
    shortened CWD, and memory usage.
    """
    # Elapsed time
    elapsed = int(time.time() - session_start)
    h, m = divmod(elapsed // 60, 60)
    s_time = f"{h}h {m:02d}m" if h else f"{m}m"

    # Token string
    if total_tokens >= 1000:
        tok_str = f"{total_tokens // 1000}K/{token_limit // 1000}K"
    else:
        tok_str = f"{total_tokens}/{token_limit // 1000}K"

    # Memory usage (psutil with ImportError fallback)
    mem_segment = None
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem_mb = proc.memory_info().rss / (1024 * 1024)
        mem_segment = f"{mem_mb:.0f}MB"
    except (ImportError, Exception):
        pass

    # Shortened CWD
    cwd = shorten_path(os.getcwd())

    # Build segments list
    segments = []
    if coding_mode:
        segments.append("🎯 Coding Mode")
    segments.append(state_text)
    if mode:
        segments.append(mode)
    segments.append(model_name)
    segments.append(tok_str)
    segments.append(s_time)
    if bg_task_count > 0:
        segments.append(f"⧗ {bg_task_count} tasks")
    segments.append(f"📁 {cwd}")
    if mem_segment:
        segments.append(mem_segment)

    return "  │  ".join(segments)
