"""Channel-agnostic plumbing for the ``ask_user`` tool.

The model asks 1-5 structured questions; a surface (CLI, Telegram, ...) installs a
handler on the module-level ``GATEWAY`` that renders them, and later calls
``GATEWAY.resolve(request_id, reply)`` with the answers. The tool thread blocks on
an event until the reply arrives, the turn is cancelled, or the policy timeout hits.

Handler contract: ``handler(request: ClarifyRequest) -> ClarifyReply | None``.
Returning a reply resolves the request immediately (blocking surfaces such as the
CLI); returning ``None`` means "delivered, the answer will come via resolve()".
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_QUESTIONS = 5
MAX_CHOICES = 4
MAX_CHOICE_CHARS = 2000
RECOMMENDED_LABEL = "(Recommended)"
POLL_SECONDS = 0.25

_SHAPE = "Pass questions=[{question, choices?, multi_select?}]; a single question is a one-entry array."
_NO_CHANNEL = "No interactive channel is available; decide with your best judgment."

OUTCOME_SUBMITTED = "submitted"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_TIMED_OUT = "timed_out"
OUTCOME_UNDELIVERED = "undelivered"


# ── Choice decoration ─────────────────────────────────────────────────────────

def strip_recommended(text) -> str:
    """Remove the trailing recommendation label (idempotent)."""
    stripped = str(text).strip()
    if stripped.casefold().endswith(RECOMMENDED_LABEL.casefold()):
        return stripped[: -len(RECOMMENDED_LABEL)].strip()
    return stripped


def mark_recommended(choices: list[str]) -> list[str]:
    """Suffix the first choice with the recommendation label.

    Only when there are at least two choices and the first is not already marked.
    """
    if len(choices) < 2:
        return list(choices)
    first = str(choices[0]).strip()
    if first != strip_recommended(first):
        return list(choices)
    return [f"{first} {RECOMMENDED_LABEL}"] + list(choices[1:])


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_questions(questions) -> tuple[list[dict] | None, str | None]:
    """Validate raw tool input -> ``(normalized, error)``; exactly one is None."""
    if not isinstance(questions, list) or not questions:
        return None, f"questions must be a non-empty array. {_SHAPE}"
    if len(questions) > MAX_QUESTIONS:
        return None, f"questions supports at most {MAX_QUESTIONS} items, got {len(questions)}. {_SHAPE}"
    normalized: list[dict] = []
    for index, item in enumerate(questions):
        if not isinstance(item, dict):
            return None, f"questions[{index}] must be an object. {_SHAPE}"
        text = str(item.get("question") or "").strip()
        if not text:
            return None, f"questions[{index}].question must be non-empty text. {_SHAPE}"
        choices = item.get("choices")
        if choices is not None:
            if not isinstance(choices, list) or not all(isinstance(c, str) for c in choices):
                return None, f"questions[{index}].choices must be a list of strings. {_SHAPE}"
            for pos, choice in enumerate(choices):
                length = len(choice.strip())
                if length > MAX_CHOICE_CHARS:
                    return None, (
                        f"questions[{index}].choices[{pos}] is {length} characters; the limit is "
                        f"{MAX_CHOICE_CHARS}. Move detail into the question text and resend."
                    )
            cleaned = [c.strip() for c in choices if c.strip()][:MAX_CHOICES]
            if choices and not cleaned:
                return None, (
                    f"questions[{index}].choices has {len(choices)} entries but all are blank. "
                    "Send real labels, or omit choices to ask an open-ended question."
                )
            choices = cleaned or None
        normalized.append({
            "qid": f"q{index}",
            "question": text,
            "choices": mark_recommended(choices) if choices else None,
            "choices_offered": list(choices) if choices else None,
            "multi_select": bool(item.get("multi_select")) and bool(choices),
        })
    return normalized, None


# ── Policy / wire types ───────────────────────────────────────────────────────

def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
    return default


def _as_seconds(value, default: float) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return default
    return seconds if math.isfinite(seconds) else default


@dataclass(frozen=True)
class ClarifyPolicy:
    enabled: bool = True
    timeout_seconds: float = 300.0
    allow_other: bool = True

    @classmethod
    def from_config(cls, cfg) -> ClarifyPolicy:
        """Read ``cfg["clarify"]``; any missing or malformed value falls back to its default."""
        default = cls()
        try:
            block = cfg.get("clarify") if isinstance(cfg, dict) else None
            if not isinstance(block, dict):
                return default
            return cls(
                enabled=_as_bool(block.get("enabled"), default.enabled),
                timeout_seconds=_as_seconds(block.get("timeout_seconds"), default.timeout_seconds),
                allow_other=_as_bool(block.get("allow_other"), default.allow_other),
            )
        except Exception:
            return default


@dataclass(frozen=True)
class ClarifyRequest:
    request_id: str
    questions: tuple[dict, ...]
    created_at: float
    # Policy hints for surfaces (how long the gateway waits, whether "Other" is allowed).
    timeout_seconds: float = 300.0
    allow_other: bool = True


@dataclass
class ClarifyReply:
    answers: dict[str, object] = field(default_factory=dict)
    outcome: str = OUTCOME_UNDELIVERED
    notice: str | None = None

    @classmethod
    def submitted(cls, answers: dict[str, object]) -> ClarifyReply:
        return cls(answers=dict(answers or {}), outcome=OUTCOME_SUBMITTED)

    @classmethod
    def cancelled(cls, notice: str | None = None) -> ClarifyReply:
        return cls(outcome=OUTCOME_CANCELLED, notice=notice or "The user dismissed the question.")

    @classmethod
    def timed_out(cls, notice: str | None = None) -> ClarifyReply:
        return cls(outcome=OUTCOME_TIMED_OUT, notice=notice or "The user did not answer in time.")

    @classmethod
    def undelivered(cls, notice: str | None = None) -> ClarifyReply:
        return cls(outcome=OUTCOME_UNDELIVERED, notice=notice or _NO_CHANNEL)


# ── Result building ───────────────────────────────────────────────────────────

def _clean_answer(raw, multi: bool):
    """Strip presentation from an answer. Multi-select accepts a list, a JSON array
    string, or a single typed answer."""
    if not multi:
        if isinstance(raw, (list, tuple)):
            raw = ", ".join(str(item) for item in raw if str(item).strip())
        return strip_recommended(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        raw = parsed if isinstance(parsed, list) else [raw]
    elif not isinstance(raw, (list, tuple)):
        raw = [raw]
    cleaned = [strip_recommended(item) for item in raw if item is not None and str(item).strip()]
    return [item for item in cleaned if item]


def build_result(normalized: list[dict], reply: ClarifyReply) -> str:
    """Render the tool result JSON for ``normalized`` questions and a surface reply."""
    answers = reply.answers if isinstance(reply.answers, dict) else {}
    responses = []
    for entry in normalized:
        qid = entry["qid"]
        raw = answers.get(qid)
        value = _clean_answer(raw, entry["multi_select"]) if raw is not None else None
        if value:
            status = "answered"
        else:
            status = "skipped" if qid in answers else "unanswered"
            value = None
        responses.append({
            "question": entry["question"],
            "choices_offered": entry["choices_offered"],
            "status": status,
            "user_response": value,
        })
    result: dict[str, object] = {"responses": responses, "outcome": reply.outcome}
    if reply.notice:
        result["notice"] = str(reply.notice)
    return json.dumps(result, ensure_ascii=False)


def _error(message: str) -> str:
    return json.dumps({"error": message, "outcome": "invalid"}, ensure_ascii=False)


# ── Gateway ───────────────────────────────────────────────────────────────────

ClarifyHandler = Callable[[ClarifyRequest], ClarifyReply | None]


class _Pending:
    __slots__ = ("event", "reply")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.reply: ClarifyReply | None = None


class ClarifyGateway:
    """Routes ``ask_user`` calls to whichever surface installed a handler."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handler: ClarifyHandler | None = None
        self._owner: str | None = None
        self._pending: dict[str, _Pending] = {}

    # handler management

    def set_handler(self, handler: ClarifyHandler, owner: str | None = None) -> None:
        with self._lock:
            self._handler = handler
            self._owner = owner

    def clear_handler(self, owner: str | None = None) -> bool:
        """Clear the handler only when ``owner`` still owns it."""
        with self._lock:
            if self._handler is None or self._owner != owner:
                return False
            self._handler = None
            self._owner = None
            return True

    def has_handler(self) -> bool:
        with self._lock:
            return self._handler is not None

    def owner(self) -> str | None:
        """Who installed the current handler (``None`` when there is none)."""
        with self._lock:
            return self._owner

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def reset(self) -> None:
        """Drop the handler and wake every waiter (tests / shutdown)."""
        with self._lock:
            self._handler = None
            self._owner = None
            pending = list(self._pending.values())
            self._pending.clear()
        for entry in pending:
            entry.event.set()

    # request lifecycle

    def resolve(self, request_id: str, reply: ClarifyReply) -> bool:
        """Deliver ``reply``; False when the request is unknown, expired or already answered."""
        with self._lock:
            entry = self._pending.get(request_id)
            if entry is None or entry.event.is_set():
                return False
            entry.reply = reply
            entry.event.set()
            return True

    def ask(self, questions, policy: ClarifyPolicy | None = None,
            cancel_check: Callable[[], bool] | None = None) -> str:
        """Ask the user and block until answered; always returns JSON text."""
        try:
            normalized, error = normalize_questions(questions)
            if error:
                return _error(error)
            policy = policy or ClarifyPolicy()
            with self._lock:
                handler = self._handler
            if handler is None or not policy.enabled or policy.timeout_seconds <= 0:
                return build_result(normalized, ClarifyReply.undelivered())
            reply = self._wait_for_reply(handler, normalized, policy, cancel_check)
            return build_result(normalized, reply)
        except Exception as exc:  # never let a surface bug crash the turn
            logger.debug("ask_user failed", exc_info=True)
            return _error(f"ask_user failed internally ({type(exc).__name__}); decide with your best judgment.")

    def _wait_for_reply(self, handler: ClarifyHandler, normalized: list[dict],
                        policy: ClarifyPolicy,
                        cancel_check: Callable[[], bool] | None) -> ClarifyReply:
        request = ClarifyRequest(
            request_id=uuid.uuid4().hex[:12],
            questions=tuple(dict(q) for q in normalized),
            created_at=time.time(),
            timeout_seconds=policy.timeout_seconds,
            allow_other=policy.allow_other,
        )
        entry = _Pending()
        with self._lock:
            self._pending[request.request_id] = entry

        def _deliver() -> None:
            try:
                immediate = handler(request)
            except Exception as exc:
                logger.debug("clarify handler raised", exc_info=True)
                immediate = ClarifyReply.undelivered(
                    f"The question could not be shown to the user ({type(exc).__name__}); "
                    "decide with your best judgment."
                )
            if isinstance(immediate, ClarifyReply):
                self.resolve(request.request_id, immediate)

        try:
            threading.Thread(target=_deliver, daemon=True,
                             name=f"ask-user-{request.request_id}").start()
            deadline = time.monotonic() + policy.timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if entry.event.wait(min(POLL_SECONDS, max(remaining, 0.0))):
                    break
                if cancel_check is not None:
                    try:
                        if cancel_check():
                            return ClarifyReply.cancelled("The turn was cancelled while waiting for the answer.")
                    except Exception:
                        logger.debug("clarify cancel_check raised", exc_info=True)
                if time.monotonic() >= deadline:
                    return ClarifyReply.timed_out()
            return entry.reply or ClarifyReply.undelivered("The question was withdrawn before it was answered.")
        finally:
            with self._lock:
                self._pending.pop(request.request_id, None)


GATEWAY = ClarifyGateway()
