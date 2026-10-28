"""
Terminal surface for the ``ask_user`` tool.

Usage (once per chat session):
    from cli.clarify_cli import install_clarify_handler
    install_clarify_handler()

The handler blocks its own thread while the user answers in the terminal and returns
the reply directly to ``utils.clarify.GATEWAY``. It never raises.
"""
from __future__ import annotations

import logging

from utils.clarify import GATEWAY, ClarifyReply, ClarifyRequest

logger = logging.getLogger(__name__)

_OTHER = "Other (type your answer)"
_SKIP = "Skip"
_TERMINAL_TIMEOUT = 3600  # upper bound for the run_in_terminal round-trip; the gateway times out first


def _ask_single(entry: dict, allow_other: bool, select_fn):
    choices = entry["choices"]
    offered = entry["choices_offered"]
    options = list(choices) + ([_OTHER] if allow_other else []) + [_SKIP]
    picked = select_fn(entry["question"], options, default_idx=0)
    if picked == _SKIP:
        return ""
    if picked == _OTHER:
        return input("  Your answer: ").strip()
    if picked in choices:
        return offered[choices.index(picked)]
    return str(picked or "").strip()


def _ask_multi(entry: dict, allow_other: bool, color):
    offered = entry["choices_offered"]
    print(color(f"  {entry['question']}", "cyan", "bold"))
    for pos, label in enumerate(entry["choices"], 1):
        print(f"    {pos}. {label}")
    hint = "numbers, e.g. 1,3" + (", or type your own answer" if allow_other else "")
    raw = input(f"  Pick ({hint}; blank to skip): ").strip()
    picked: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit() and 1 <= int(token) <= len(offered):
            label = offered[int(token) - 1]
            if label not in picked:
                picked.append(label)
    if not picked and raw and allow_other:
        return [raw]
    return picked


def _render(request: ClarifyRequest, select_fn, color) -> ClarifyReply:
    print()
    print(color("  ┌─ Koza needs your input ", "yellow", "bold") + color("─" * 34, "gold"))
    answers: dict[str, object] = {}
    for entry in request.questions:
        if entry["choices"] and entry["multi_select"]:
            answers[entry["qid"]] = _ask_multi(entry, request.allow_other, color)
        elif entry["choices"]:
            answers[entry["qid"]] = _ask_single(entry, request.allow_other, select_fn)
        else:
            print(color(f"  {entry['question']}", "cyan", "bold"))
            answers[entry["qid"]] = input("  ❯ ").strip()
    print(color("  └" + "─" * 58, "yellow"))
    return ClarifyReply.submitted(answers)


def _make_handler():
    from cli.ui import _C, _select_menu, _spinner_stop

    try:
        from prompt_toolkit.application import get_app_or_none
        _has_pt = True
    except ImportError:
        get_app_or_none = lambda: None
        _has_pt = False

    def _safe_render(request: ClarifyRequest) -> ClarifyReply:
        try:
            return _render(request, _select_menu, _C)
        except (KeyboardInterrupt, EOFError):
            return ClarifyReply.cancelled()
        except Exception:
            logger.debug("CLI clarify render failed", exc_info=True)
            return ClarifyReply.undelivered("CLI could not render the question")

    def handler(request: ClarifyRequest) -> ClarifyReply:
        try:
            try:
                _spinner_stop()
            except Exception:
                pass

            pt_app = get_app_or_none() if _has_pt else None
            if (pt_app is not None and pt_app.is_running
                    and pt_app.loop is not None and pt_app.loop.is_running()):
                import asyncio

                from prompt_toolkit.application import run_in_terminal

                result: list[ClarifyReply] = []

                def _in_terminal():
                    result.append(_safe_render(request))

                coro = run_in_terminal(_in_terminal, render_cli_done=False)
                try:
                    future = asyncio.run_coroutine_threadsafe(coro, pt_app.loop)
                except Exception:
                    coro.close()
                    return _safe_render(request)
                try:
                    future.result(timeout=_TERMINAL_TIMEOUT)
                except Exception:
                    if not result:
                        return _safe_render(request)
                return result[0] if result else ClarifyReply.undelivered("CLI could not render the question")

            return _safe_render(request)
        except (KeyboardInterrupt, EOFError):
            return ClarifyReply.cancelled()
        except Exception:
            logger.debug("CLI clarify handler failed", exc_info=True)
            return ClarifyReply.undelivered("CLI could not render the question")

    return handler


def install_clarify_handler() -> None:
    """Route ``ask_user`` questions to this terminal."""
    GATEWAY.set_handler(_make_handler(), owner="cli")
