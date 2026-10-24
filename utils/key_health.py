"""Health tracking and rotation for provider API keys."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from utils.redact import mask_secret

AUTH = "auth"
BILLING = "billing"
RATE_LIMIT = "rate_limit"
DEFAULT = "default"

STATUS_OK = "ok"
STATUS_COOLDOWN = "cooldown"
STATUS_DISABLED = "disabled"

ROTATABLE_REASONS = frozenset({AUTH, BILLING, RATE_LIMIT})


def should_rotate(reason: str, attempts: int, max_attempts: int) -> bool:
    return reason in ROTATABLE_REASONS and attempts < max_attempts


@dataclass(frozen=True)
class KeyRotationPolicy:
    auth_disables_key: bool = True
    billing_cooldown_seconds: int = 1800
    rate_limit_cooldown_seconds: int = 60
    default_cooldown_seconds: int = 300

    @classmethod
    def from_config(cls, cfg: dict | None) -> "KeyRotationPolicy":
        if not isinstance(cfg, dict):
            return cls()
        if "key_rotation" in cfg:
            cfg = cfg["key_rotation"]
        if not isinstance(cfg, dict):
            return cls()

        defaults = cls()
        values = {}
        auth_disables_key = cfg.get("auth_disables_key")
        values["auth_disables_key"] = (
            auth_disables_key
            if isinstance(auth_disables_key, bool)
            else defaults.auth_disables_key
        )
        for name in (
            "billing_cooldown_seconds",
            "rate_limit_cooldown_seconds",
            "default_cooldown_seconds",
        ):
            value = cfg.get(name)
            values[name] = (
                value
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                else getattr(defaults, name)
            )
        return cls(**values)


@dataclass
class KeyHealth:
    index: int
    label: str
    status: str = STATUS_OK
    failures: int = 0
    last_reason: str = ""
    last_status_code: int | None = None
    cooldown_until: float | None = None

    def available(self, now: float) -> bool:
        if self.status == STATUS_DISABLED:
            return False
        if self.status == STATUS_COOLDOWN:
            if self.cooldown_until is not None and now < self.cooldown_until:
                return False
            self.status = STATUS_OK
            self.cooldown_until = None
        return True

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "label": self.label,
            "status": self.status,
            "failures": self.failures,
            "last_reason": self.last_reason,
            "last_status_code": self.last_status_code,
            "cooldown_until": self.cooldown_until,
        }


class KeyPool:
    def __init__(
        self,
        keys: list[str],
        policy: KeyRotationPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._keys = list(keys)
        self._policy = policy or KeyRotationPolicy()
        self._clock = clock
        self._current_index = 0
        self._health = [
            KeyHealth(index=index, label=mask_secret(key))
            for index, key in enumerate(self._keys)
        ]

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def current_key(self) -> str:
        if not self._keys:
            return ""
        return self._keys[self._current_index]

    @property
    def current_index(self) -> int:
        return self._current_index

    def available_count(self) -> int:
        now = self._clock()
        return sum(entry.available(now) for entry in self._health)

    def mark_success(self, index: int | None = None) -> None:
        if not self._health:
            return
        entry = self._health[self._current_index if index is None else index]
        if entry.status == STATUS_DISABLED:
            # A key rejected for authentication stays out of rotation for the
            # lifetime of the process: a success elsewhere must not revive it.
            return
        entry.status = STATUS_OK
        entry.failures = 0
        entry.last_reason = ""
        entry.last_status_code = None
        entry.cooldown_until = None

    def mark_failure(
        self,
        reason: str,
        status_code: int | None = None,
        index: int | None = None,
    ) -> None:
        if not self._health:
            return
        entry = self._health[self._current_index if index is None else index]
        entry.failures += 1
        entry.last_reason = reason
        entry.last_status_code = status_code

        if reason == AUTH and self._policy.auth_disables_key:
            entry.status = STATUS_DISABLED
            entry.cooldown_until = None
            return

        if reason == BILLING:
            ttl = self._policy.billing_cooldown_seconds
        elif reason == RATE_LIMIT:
            ttl = self._policy.rate_limit_cooldown_seconds
        else:
            ttl = self._policy.default_cooldown_seconds
        entry.status = STATUS_COOLDOWN
        entry.cooldown_until = self._clock() + ttl

    def rotate(self, reason: str = "") -> bool:
        if not self._keys:
            return False
        if reason:
            self.mark_failure(reason)
        now = self._clock()
        for offset in range(1, len(self._keys) + 1):
            index = (self._current_index + offset) % len(self._keys)
            if index == self._current_index:
                continue
            if self._health[index].available(now):
                self._current_index = index
                return True
        return False

    def snapshot(self) -> list[dict]:
        return [entry.to_dict() for entry in self._health]
