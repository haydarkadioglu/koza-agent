"""Tool execution middleware pipeline.

Allows registering middleware hooks to run pre-flight checks, argument coercion,
SSRF guards, logging, and other filters prior to tool handler execution.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List

logger = logging.getLogger(__name__)


class MiddlewareChain:
    """Chain of middleware callables executed in sequence.

    Each middleware should have the signature:
        def middleware(agent: Any, name: str, args: dict, next_call: Callable[[dict], Any]) -> Any
    """

    def __init__(self, middlewares: List[Callable] = None) -> None:
        self.middlewares = list(middlewares) if middlewares is not None else []

    def execute(
        self,
        agent: Any,
        name: str,
        args: dict,
        terminal_call: Callable[[dict], Any]
    ) -> Any:
        """Execute the middleware chain, ending with the terminal_call."""
        def call_at(index: int, current_args: dict) -> Any:
            if index >= len(self.middlewares):
                return terminal_call(current_args)

            middleware = self.middlewares[index]

            def next_call(next_args: dict | None = None) -> Any:
                nonlocal current_args
                payload = next_args if next_args is not None else current_args
                return call_at(index + 1, payload)

            try:
                return middleware(agent, name, current_args, next_call)
            except Exception as e:
                # If a middleware fails (outside downstream execution errors), we log it and fallback
                logger.warning(
                    "Middleware error in %s: %s",
                    getattr(middleware, "__name__", repr(middleware)),
                    e
                )
                # Fallback to the rest of the chain with current arguments
                return call_at(index + 1, current_args)

        return call_at(0, args)


def coerce_arguments_middleware(
    agent: Any,
    name: str,
    args: dict,
    next_call: Callable[[dict], Any]
) -> Any:
    """Middleware that coerces arguments based on the tool's JSON Schema."""
    from tools.registry import coerce_tool_args
    coerced = coerce_tool_args(name, args)
    return next_call(coerced)


def ssrf_guard_middleware(
    agent: Any,
    name: str,
    args: dict,
    next_call: Callable[[dict], Any]
) -> Any:
    """Middleware that scans arguments and blocks private/unsafe URLs."""
    from skills.web import is_safe_url
    for k, v in args.items():
        if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")):
            if not is_safe_url(v):
                raise ValueError(f"SSRF violation: target host is private, loopback, or invalid: {v}")
    return next_call(args)


def logging_middleware(
    agent: Any,
    name: str,
    args: dict,
    next_call: Callable[[dict], Any]
) -> Any:
    """Middleware that logs the tool call start and result to working memory."""
    from skills import working_memory
    try:
        result = next_call(args)
        arg_preview = ", ".join(f"{k}={str(v)[:40]}" for k, v in args.items())
        summary = f"{name}({arg_preview})"
        detail = str(result)[:300]
        working_memory.wm_add(summary=summary, detail=detail, event_type="tool")
        return result
    except Exception as e:
        working_memory.wm_add(summary=f"{name} failed: {e}", event_type="error")
        raise


def special_tools_middleware(
    agent: Any,
    name: str,
    args: dict,
    next_call: Callable[[dict], Any]
) -> Any:
    """Middleware for special core-level tools (save_session, browser_task)."""
    if name == "save_session" and not args.get("messages"):
        return agent.auto_save(
            title=str(args.get("title") or ""),
            summary=str(args.get("summary") or ""),
        )
    if name == "browser_task":
        try:
            from skills import browser_control as _browser_control
            _browser_control.set_permission_callback(agent.permission_callback)
        except Exception:
            pass
    return next_call(args)


# Default pipeline middleware sequence
DEFAULT_MIDDLEWARES: List[Callable] = [
    coerce_arguments_middleware,
    ssrf_guard_middleware,
    logging_middleware,
    special_tools_middleware,
]
